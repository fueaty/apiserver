#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
mock 治理（写入路径）回归测试锁 —— 离线，无外网。

背景：站点采集失败/解析为空时会**回退到 `_get_mock_data()`** 返回演示假数据。
这些假数据**绝不允许进入飞书表**。历史上部分站点 mock「恰好」是扁平 dict，
因写入层要求 {"fields": item} 形状而被**顺带丢弃** —— 即「mock 不入库」曾**靠 bug 兜底**。
一旦有人给 mock 也包上 {"fields": item}（看似在「修形状不一致」），mock 就会静默入库。
P1 只给 3 站打了标记，而 baidu/cctv/weibo/xiaohongshu 的 mock **本就已经是包装体**
（且都在活跃失败路径上）→ 会被判为真实、进入写集（潜在泄漏，非正在发生）。

治理方案（见 app/services/collection/mock_utils.py）：
  · 各站点在 mock 行**内部**打显式标记 MOCK_FLAG(is_mock)=True；
  · 写入路径（script/collection_pipeline.py）用 split_real_and_mock() 按标记剔除。

本测试（**动态枚举**，不写死站点）：
  [A] 禁令：仅 xinhua/people_daily/tech_36kr 的 mock 返回路径必须**不被包装**（保持扁平）。
  [B] 动态枚举 sites/*.py 中**所有**定义 _get_mock_data 的站点：
      逐站 mock 100% 判为 mock、split 后 real==0；并做**负控**（真实记录判为 real，防误伤）。
  [C] xinhua 解析路径回退 mock：即便被包成 {"fields": item} 也不得入写集。
  [D] I3：真实数据不受影响。
  [E] 变异对照（M1 包装 / M2 抹标记 / M3 仅顶层）。
  [F] 接线锁（文本层）：pipeline / enhanced_collection 均接入共享写集实现 write_set。
      行为层强锁见 tests/test_write_path_wiring.py（桩驱动跑真实写路径）。
  [G] N2：xiaohongshu._is_mock_data 改为基于标记；真实路径不被替换。
  [H] N1：enhanced_collection 第二条写入路径在重建记录前过滤 mock。

依赖桩（**条件桩**；判据：桩的合法性 = 被桩模块的行为是否被断言依赖）：
  aiohttp/bs4/yaml 等只在 ImportError 时注入（本测试不联网、不断言其行为）。

    python tests/test_mock_governance.py     # 期望 RC=0
"""

import asyncio
import importlib
import os
import sys
import types

# ---------------------------------------------------------------------------
# 条件依赖桩（仅缺失时注入，绝不覆盖已安装的真实包）
# ---------------------------------------------------------------------------
def _stub_module(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda attr: type(attr, (object,), {})
    m.__all__ = []
    return m


for _name in (
    "aiohttp",
    "httpx",
    "lark_oapi",
    "lark_oapi.api",
    "lark_oapi.api.bitable",
    "lark_oapi.api.bitable.v1",
    "pydantic",
    "pydantic_settings",
):
    if _name in sys.modules:
        continue
    try:
        __import__(_name)
    except Exception:
        sys.modules[_name] = _stub_module(_name)

# bs4：对空/无效输入产出空 soup（真实 bs4 对 "<html></html>" 也解析不出条目 → 行为一致）
if "bs4" not in sys.modules:
    try:
        import bs4  # noqa: F401
    except Exception:
        _bs4 = types.ModuleType("bs4")

        class _FakeSoup:
            def __init__(self, *args, **kwargs):
                pass

            def find_all(self, *args, **kwargs):
                return []

        _bs4.BeautifulSoup = _FakeSoup
        sys.modules["bs4"] = _bs4

# yaml：xiaohongshu/zhihu 仅在 __init__ 里读配置（失败即回退 {}）；其行为不被断言依赖。
if "yaml" not in sys.modules:
    try:
        import yaml  # noqa: F401
    except Exception:
        _yaml = types.ModuleType("yaml")
        _yaml.safe_load = lambda *a, **k: {}
        sys.modules["yaml"] = _yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from app.services.collection.mock_utils import (  # noqa: E402
    MOCK_FLAG,
    ALLOW_MOCK_ENV,
    is_mock_record,
    split_real_and_mock,
)
from app.services.collection.sites.base import BaseSite  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


SITES_DIR = os.path.join(ROOT, "app", "services", "collection", "sites")

# 3 个**必须保持扁平** mock 返回路径的站点（禁令范围）。
FLAT_MOCK_SITES = ("xinhua", "people_daily", "tech_36kr")


def _sites_with_mock():
    """动态枚举：扫描 sites/*.py 中所有定义 `_get_mock_data` 的站点（不写死名单）。

    用**源码扫描**决定要 import 哪些模块，避免为无关站点引入额外依赖解析。
    将来新增带 mock 的站点会自动纳入。
    """
    codes = []
    for fn in sorted(os.listdir(SITES_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        with open(os.path.join(SITES_DIR, fn), encoding="utf-8") as f:
            if "def _get_mock_data" in f.read():
                codes.append(fn[:-3])
    return codes


def _load_site_class(code):
    mod_name = f"app.services.collection.sites.{code}"
    mod = importlib.import_module(mod_name)
    for obj in vars(mod).values():
        if (isinstance(obj, type)
                and getattr(obj, "__module__", "") == mod_name
                and issubclass(obj, BaseSite)
                and hasattr(obj, "_get_mock_data")):
            return obj
    return None


def test_ban_on_wrapping():
    """[A] 禁令：3 站的 mock 返回路径必须保持扁平（未被包装成 {'fields': item}）。"""
    print("\n[A] 禁令：仅 xinhua/people_daily/tech_36kr 的 mock 返回路径不得被包装")
    for code in FLAT_MOCK_SITES:
        cls = _load_site_class(code)
        check(f"[A:{code}] 站点类可加载", cls is not None, "未找到 BaseSite 子类")
        if cls is None:
            continue
        rows = cls(code, {"timeout": 10})._get_mock_data()
        check(f"[A:{code}] 禁令：mock 每条都无 'fields' 键（未包装）",
              all(isinstance(r, dict) and "fields" not in r for r in rows),
              f"首条键={list(rows[0].keys()) if rows else 'N/A'}")


def test_dynamic_enumeration():
    """[B] 动态枚举：所有含 _get_mock_data 的站点，mock 100% 被判为 mock + 负控。"""
    print("\n[B] 动态枚举：sites/*.py 中所有 _get_mock_data 站点")

    codes = _sites_with_mock()
    check("[B] 发现的 mock 站点数 >= 7（防枚举退化）",
          len(codes) >= 7, f"发现={codes}")

    for code in codes:
        cls = _load_site_class(code)
        check(f"[B:{code}] 站点类可加载", cls is not None, "未找到 BaseSite 子类")
        if cls is None:
            continue

        rows = cls(code, {"timeout": 10})._get_mock_data()
        check(f"[B:{code}] mock 非空 list",
              isinstance(rows, list) and len(rows) > 0,
              f"len={len(rows) if isinstance(rows, list) else 'N/A'}")

        n_mock = sum(1 for r in rows if is_mock_record(r))
        check(f"[B:{code}] 100% 判为 mock（每一条都带标记，含包装体内层）",
              len(rows) > 0 and n_mock == len(rows),
              f"{n_mock}/{len(rows)} 判为 mock；首条={rows[0] if rows else 'N/A'}")

        real, mock = split_real_and_mock(rows)
        check(f"[B:{code}] split_real_and_mock：real==0、mock==全量",
              len(real) == 0 and len(mock) == len(rows),
              f"real={len(real)} mock={len(mock)} 输入={len(rows)}")

        # 负控：真实记录（无标记，扁平 + 包装两种形态）必须判为 real，防误伤
        neg_flat = {"id": "r1", "title": "真实标题", "url": "https://x/1", "site_code": code}
        neg_wrapped = {"fields": dict(neg_flat)}
        neg_real, neg_mock = split_real_and_mock([neg_flat, neg_wrapped])
        check(f"[B:{code}] 负控：真实记录（扁平/包装）判为 real、不误伤",
              (not is_mock_record(neg_flat)) and (not is_mock_record(neg_wrapped))
              and len(neg_mock) == 0 and len(neg_real) == 2,
              f"flat_mock={is_mock_record(neg_flat)} wrapped_mock={is_mock_record(neg_wrapped)}")


def test_xinhua_parse_path_leak_closed():
    """[C] xinhua 解析路径回退 mock：即便被包成 {'fields': item} 也不得入写集。

    #44 起回退改显式 opt-in：**默认**解析为空直接返回 []（不伪造）。
    这里在 opt-in 下取 mock，再验证"被包装后仍被识别/排除"这条**标记透传**保证；
    并额外断言默认模式下不再产出 mock。
    """
    print("\n[C] xinhua 解析路径回退 mock：即便被包装也不得入写集")

    site = _load_site_class("xinhua")("xinhua", {"timeout": 10})

    # 默认（opt-in 关闭）：解析为空 → 不再伪造
    os.environ.pop(ALLOW_MOCK_ENV, None)
    parsed_default = site._parse_xinhua_homepage_data("<html></html>")
    check("[C] 默认（不伪造）：解析为空时返回空 list",
          isinstance(parsed_default, list) and len(parsed_default) == 0,
          f"len={len(parsed_default) if isinstance(parsed_default, list) else 'N/A'}")

    # opt-in 打开：取 mock，验证标记透传保证
    os.environ[ALLOW_MOCK_ENV] = "1"
    try:
        parsed = site._parse_xinhua_homepage_data("<html></html>")
    finally:
        os.environ.pop(ALLOW_MOCK_ENV, None)

    check("[C] opt-in：解析路径回退时确实产出了记录（走了 mock 回退）",
          isinstance(parsed, list) and len(parsed) > 0,
          f"len={len(parsed) if isinstance(parsed, list) else 'N/A'}")
    check("[C] 输出是 {'fields': item} 包裹形态（泄漏的危险形状）",
          all(isinstance(e, dict) and isinstance(e.get("fields"), dict) for e in parsed),
          f"首元素键={list(parsed[0].keys()) if parsed else 'N/A'}")
    check("[C] 泄漏关闭①：包裹后的 mock 仍被 is_mock_record 识别（嵌套标记透传）",
          all(is_mock_record(e) for e in parsed),
          f"识别={sum(1 for e in parsed if is_mock_record(e))}/{len(parsed)}")
    real_c, mock_c = split_real_and_mock(parsed)
    check("[C] 泄漏关闭②：包裹后的 mock 仍被排除出写集（real==0）",
          len(real_c) == 0 and len(mock_c) == len(parsed),
          f"real={len(real_c)} mock={len(mock_c)} 输入={len(parsed)}")


def test_real_records_unaffected():
    """[D] I3：真实（无标记）记录不得被误伤。"""
    print("\n[D] I3：真实数据不受影响")

    real_rows = [
        {"id": "r1", "title": "真实新闻1", "url": "https://example.com/1", "site_code": "cctv"},
        {"fields": {"id": "r2", "title": "真实新闻2", "url": "https://example.com/2",
                    "site_code": "cctv"}},
    ]
    real_d, mock_d = split_real_and_mock(real_rows)
    check("[D] 真实记录一条都不被误判为 mock",
          len(mock_d) == 0 and len(real_d) == len(real_rows),
          f"real={len(real_d)} mock={len(mock_d)}")
    check("[D] 真实记录原样保留（顺序/内容不变）", real_d == real_rows, f"got={real_d}")


def test_mutation_controls():
    """[E] 变异对照：证明断言有鉴别力。"""
    print("\n[E] 变异对照（证明测试有鉴别力）")

    rows = _load_site_class("xinhua")("xinhua", {"timeout": 10})._get_mock_data()

    wrapped = [{"fields": dict(r)} for r in rows]
    check("M1 变异：把 mock 包上 fields → 『未包装』断言变 False（被检出）",
          not all("fields" not in r for r in wrapped), "变异体未被检出 = 无鉴别力")

    real_m1, mock_m1 = split_real_and_mock(wrapped)
    check("M1b 纵深防御：mock 被包装后仍按嵌套标记排除出写集",
          len(real_m1) == 0 and len(mock_m1) == len(wrapped),
          f"real={len(real_m1)} mock={len(mock_m1)}")

    stripped = [{k: v for k, v in r.items() if k != MOCK_FLAG} for r in rows]
    real_m2, mock_m2 = split_real_and_mock(stripped)
    check("M2 变异：抹掉 is_mock 标记 → 这些行会进入写集（证明标记承重）",
          len(mock_m2) == 0 and len(real_m2) == len(rows),
          f"real={len(real_m2)} mock={len(mock_m2)}")

    nested = {"fields": {MOCK_FLAG: True, "site_code": "xinhua"}}
    check("M3 变异：is_mock_record 对嵌套标记返回 True，仅顶层检查会漏检（嵌套分支承重）",
          is_mock_record(nested) is True and (nested.get(MOCK_FLAG) is True) is False,
          f"nested={is_mock_record(nested)}")


def test_pipeline_and_endpoint_wiring():
    """[F] 接线锁（文本层）：pipeline 与 enhanced_collection 都接入**共享写集实现**。

    行为层的强保证在 tests/test_write_path_wiring.py（桩驱动跑真实 pipeline / 真端点，
    断言真正传给 batch_add_records 的记录里 mock==0）——那里能抓 `continue→pass` 与
    「忽略返回值」。此处只保留"**接线存在**"这一层（谁被接进写路径）。
    """
    print("\n[F] 接线锁：写路径接入共享写集实现 write_set")

    with open(os.path.join(ROOT, "script", "collection_pipeline.py"), encoding="utf-8") as f:
        pipe = f.read()
    check("[F] collection_pipeline.py 导入并调用 split_write_set",
          "from app.services.collection.write_set import split_write_set" in pipe
          and "split_write_set(" in pipe,
          "写入层未接入共享写集实现")
    check("[F] collection_pipeline.py 使用站点级检测器 get_available_sites()",
          "get_available_sites()" in pipe, "缺少站点级检测器")

    with open(os.path.join(ROOT, "app", "api", "v1", "endpoints", "enhanced_collection.py"),
              encoding="utf-8") as f:
        ec = f.read()
    check("[N1:F] enhanced_collection 导入并调用 build_headline_records",
          "from app.services.collection.write_set import build_headline_records" in ec
          and "build_headline_records(" in ec,
          "第二条写入路径未接入共享写集实现")
    check("[N1:F] enhanced_collection 不再自行内联过滤（治理收敛到 write_set 单一实现）",
          "is_mock_record(news_item)" not in ec,
          "仍在端点内联过滤 → 与共享实现漂移风险")

    with open(os.path.join(ROOT, "app", "services", "collection", "write_set.py"),
              encoding="utf-8") as f:
        ws = f.read()
    check("[N1:F] write_set.build_headline_records 的过滤**早于**重建 feishu_record",
          ws.index("if is_mock_record(news_item):") < ws.index("feishu_record = {"),
          "过滤点在重建之后 → 标记会被洗白")


def test_n2_xiaohongshu_marker_based():
    """[G] N2：xiaohongshu._is_mock_data 必须基于标记；真实路径不被替换。"""
    print("\n[G] N2：xiaohongshu 判定改为基于显式标记")

    xhs_cls = _load_site_class("xiaohongshu")
    xhs = xhs_cls("xiaohongshu", {"timeout": 10})

    # 真实批次：首条标题恰好含「示例」→ 旧启发式会误判 → 丢整批真实数据
    real_batch = [{"id": "r1", "title": "示例代码：从零复现", "url": "https://x/1",
                   "hot": "9999", "rank": "1", "site_code": "xiaohongshu"}]
    check("[G] N2：真实批次（首条标题含『示例』）**不**被判为 mock（消除误伤）",
          xhs._is_mock_data(real_batch) is False,
          f"_is_mock_data={xhs._is_mock_data(real_batch)}")

    mock_batch = xhs._get_mock_data()
    check("[G] N2：带标记的 mock 批次被判为 mock",
          xhs._is_mock_data(mock_batch) is True,
          f"_is_mock_data={xhs._is_mock_data(mock_batch)}")

    stripped = [{k: v for k, v in m.items() if k != MOCK_FLAG} for m in mock_batch]
    check("[G] N2 变异：抹掉标记后不再判为 mock（证明判定基于标记而非标题）",
          xhs._is_mock_data(stripped) is False,
          f"抹标记后 _is_mock_data={xhs._is_mock_data(stripped)}")

    # 真实路径行为：collect() 首条含「示例」仍返回真实批次（:49-52 包装逻辑不变）
    async def _fake_web():
        return [dict(r) for r in real_batch]

    xhs._collect_via_web = _fake_web
    out = asyncio.run(xhs.collect({}))
    titles = [r.get("fields", {}).get("title") for r in out]
    check("[G] N2 真实路径：collect() 返回**真实**批次（未被替换成 mock）",
          titles == ["示例代码：从零复现"], f"titles={titles}")
    check("[G] N2 真实路径：输出为 {'fields': item} 且无 is_mock 标记",
          all(isinstance(r, dict) and "fields" in r for r in out)
          and all(not is_mock_record(r) for r in out),
          f"out[0]={out[0] if out else 'N/A'}")

    # mock 路径：网页为空 → 默认返回 []（不伪造）；opt-in 才返回带标记的 mock
    async def _fake_empty():
        return []

    xhs._collect_via_web = _fake_empty
    os.environ.pop(ALLOW_MOCK_ENV, None)
    out_default = asyncio.run(xhs.collect({}))
    check("[G] N2 mock 路径（默认）：collect() 返回空、不伪造",
          isinstance(out_default, list) and len(out_default) == 0,
          f"out_default={out_default}")

    os.environ[ALLOW_MOCK_ENV] = "1"
    try:
        out2 = asyncio.run(xhs.collect({}))
    finally:
        os.environ.pop(ALLOW_MOCK_ENV, None)
    check("[G] N2 mock 路径（opt-in）：collect() 返回带标记的 mock（可被写入层剔除）",
          len(out2) > 0 and all(is_mock_record(r) for r in out2),
          f"out2={out2}")


def main():
    print("=" * 70)
    print("mock 治理回归锁（离线，动态枚举）：标记 / 剔除 / 泄漏关闭 / 变异 / 接线 / N1 / N2")
    print("=" * 70)

    test_ban_on_wrapping()
    test_dynamic_enumeration()
    test_xinhua_parse_path_leak_closed()
    test_real_records_unaffected()
    test_mutation_controls()
    test_pipeline_and_endpoint_wiring()
    test_n2_xiaohongshu_marker_based()

    print("=" * 70)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
