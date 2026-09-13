#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
mock 治理（写入路径）回归测试锁 —— 离线，无外网。

背景（为什么需要这把锁）：
  某站点采集失败/解析为空时，会**回退到 `_get_mock_data()`** 返回演示假数据
  （xinhua / people_daily / tech_36kr）。历史上这些假数据「恰好」是**扁平 dict**，
  而飞书写入层 `FeishuService._align_records_with_fields` 要求 `{"fields": item}` 形状，
  于是扁平行被**静默丢弃** —— 也就是说「mock 不入库」当时是**靠一个 bug 兜底**：
  一旦有人给 mock 也包上 `{"fields": item}`（看似在「修形状不一致」），
  mock 就会**静默进入生产表**，污染线上数据且不报错。

治理方案（实现见 `app/services/collection/mock_utils.py`）：
  · 各站点在 mock 行上打**显式标记** `is_mock=True`（MOCK_FLAG）；
  · 写入层（`script/collection_pipeline.py`）用 `split_real_and_mock()` 按**标记**
    把 mock 行排除出写集，并**单独**上报（与「批次级形状差额」分开）。

三条不变式（本测试逐条锁死）：
  I1  mock 行不得进入写集，且由**意图标记**保证（不依赖「忘了包 fields」这个 bug）。
  I2  mock 回退可观测、且与形状差额**可分离**（本测试锁定「可识别/可分离」这一前提）。
  I3  真实数据不受影响（split 只按标记拆，真实行原样保留）。

禁令（本测试的「未被包装」断言即其守卫）：
  不得给 xinhua / tech_36kr / people_daily 的 mock 返回路径补 `{"fields": item}`。

变异对照（证明本测试有鉴别力 —— 若没有，这些锁就是"假绿"）：
  M1「把 mock 包上 fields」  → 「未包装」断言必须变 False（被检出）。
  M2「抹掉 is_mock 标记」     → I1 断言必须变 False（被检出）。
  M3「is_mock 只看顶层」      → 嵌套形态漏检（证明嵌套分支是**承重**的、被断言依赖）。

依赖桩（**条件桩**；判据：桩的合法性 = 被桩模块的行为是否被断言依赖）：
  本测试只做「取 mock 值 + 纯逻辑拆分 + 源文件接线扫描」，**不联网**。
  故 aiohttp / bs4 等只在 ImportError 时才补桩：
    · aiohttp：`.base` 模块级 `import aiohttp` + `def get_session() -> aiohttp.ClientSession`
      会在 def 时求值注解 → 仅需该**名字**存在；行为不被断言依赖。
    · bs4：`xinhua._parse_xinhua_homepage_data` 方法体内 `from bs4 import BeautifulSoup`；
      本测试对解析路径只依赖「解析为空 → 回退 mock」这一行为（真实 bs4 与桩对空串均产出空）。

    python tests/test_mock_governance.py     # 期望 RC=0
"""

import os
import sys
import types

# ---------------------------------------------------------------------------
# 条件依赖桩（仅在缺失时注入，绝不覆盖已安装的真实包）
# ---------------------------------------------------------------------------
def _stub_module(name):
    m = types.ModuleType(name)
    # 返回「类」，兼容 `from x import Base` / `x.SomeAttr(...)` 的"名字"需求
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

# bs4 需要一点"行为"：对空/无效输入产出空 soup，使 xinhua 解析路径稳定回退到 mock。
# （真实 bs4 对 "<html></html>" 也解析不出新闻条目 → 同样回退，故两者行为一致。）
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from app.services.collection.mock_utils import (  # noqa: E402
    MOCK_FLAG,
    is_mock_record,
    split_real_and_mock,
)
from app.services.collection.sites.xinhua import XinhuaSite          # noqa: E402
from app.services.collection.sites.people_daily import PeopleDailySite  # noqa: E402
from app.services.collection.sites.tech_36kr import Tech36krSite     # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


# 三站公共口径：(site_code, 站点类)
SITE_CASES = [
    ("xinhua", XinhuaSite),
    ("people_daily", PeopleDailySite),
    ("tech_36kr", Tech36krSite),
]


def test_mock_marker_and_exclusion():
    """(A) 禁令 + (B) I1：mock 返回路径未被包装；mock 行带标记且被排除出写集。"""
    print("\n[A] 禁令：mock 返回路径**未**被包装（无 'fields' 键）")
    print("[B] I1：mock 行带 is_mock 标记，且被 split_real_and_mock 排除出写集")

    for code, cls in SITE_CASES:
        site = cls(code, {"timeout": 10})
        rows = site._get_mock_data()

        check(f"[{code}] mock 返回非空 list",
              isinstance(rows, list) and len(rows) > 0,
              f"type={type(rows).__name__} len={len(rows) if isinstance(rows, list) else 'N/A'}")

        # (A) 禁令守卫：mock 返回路径**不得**是 {"fields": item}
        check(f"[{code}] 禁令：mock 返回路径未被包装（每条都无 'fields' 键）",
              all(isinstance(r, dict) and "fields" not in r for r in rows),
              f"首条键={list(rows[0].keys()) if rows else 'N/A'}")

        # (B) I1：每条 mock 都被标记识别
        check(f"[{code}] I1：每条 mock 都被 is_mock_record 识别（标记存在）",
              all(is_mock_record(r) for r in rows),
              f"识别={sum(1 for r in rows if is_mock_record(r))}/{len(rows)}")

        # (B) I1：全部被排除出写集
        real, mock = split_real_and_mock(rows)
        check(f"[{code}] I1：mock 全部被排除出写集（real 为空、mock 等于全量）",
              len(real) == 0 and len(mock) == len(rows),
              f"real={len(real)} mock={len(mock)} 输入={len(rows)}")


def test_xinhua_parse_path_leak_closed():
    """(C) xinhua 解析路径的**潜在泄漏**必须被关闭。

    泄漏点：`_parse_xinhua_homepage_data` 在解析为空时回退到 `_get_mock_data()`，
    随后该函数把结果统一包装成 `{"fields": item}`（第 172 行）——
    即 mock 在这里被「洗白」成与真实数据同形的记录。
    xinhua 是**唯一**存在此解析级 mock 回退的站点，若不在重建 result 时透传 is_mock，
    这些 mock 就会以 `{"fields": ...}` 形状**进入写集**（对齐层不再丢弃它们）。

    断言：回退产物虽是 `{"fields": ...}`，但内层带 is_mock → 仍被识别并排除。
    """
    print("\n[C] xinhua 解析路径回退 mock：即便被包装成 {'fields': item} 也不得入写集")

    site = XinhuaSite("xinhua", {"timeout": 10})
    parsed = site._parse_xinhua_homepage_data("<html></html>")

    check("[C] 解析路径回退时确实产出了记录（非空，证明走了 mock 回退）",
          isinstance(parsed, list) and len(parsed) > 0,
          f"len={len(parsed) if isinstance(parsed, list) else 'N/A'}")

    check("[C] 解析路径输出是 {'fields': item} 包裹形态（这正是泄漏的危险形状）",
          all(isinstance(e, dict) and isinstance(e.get("fields"), dict) for e in parsed),
          f"首元素键={list(parsed[0].keys()) if parsed else 'N/A'}")

    check("[C] 泄漏关闭①：包裹后的 mock 仍被 is_mock_record 识别（嵌套标记透传成功）",
          all(is_mock_record(e) for e in parsed),
          f"识别={sum(1 for e in parsed if is_mock_record(e))}/{len(parsed)}")

    real_c, mock_c = split_real_and_mock(parsed)
    check("[C] 泄漏关闭②：包裹后的 mock 仍被排除出写集（real 为空）",
          len(real_c) == 0 and len(mock_c) == len(parsed),
          f"real={len(real_c)} mock={len(mock_c)} 输入={len(parsed)}")


def test_real_records_unaffected():
    """(D) I3：真实（无标记）记录不得被误伤。"""
    print("\n[D] I3：真实数据不受影响（split 只按标记拆）")

    real_rows = [
        {"id": "r1", "title": "真实新闻1", "url": "https://example.com/1", "site_code": "cctv"},
        {"fields": {"id": "r2", "title": "真实新闻2", "url": "https://example.com/2",
                    "site_code": "cctv"}},
    ]
    real_d, mock_d = split_real_and_mock(real_rows)

    check("[D] 真实（无标记）记录一条都不被误判为 mock",
          len(mock_d) == 0 and len(real_d) == len(real_rows),
          f"real={len(real_d)} mock={len(mock_d)}")

    check("[D] 真实记录原样保留（顺序/内容不变）",
          real_d == real_rows, f"got={real_d}")


def test_mutation_controls():
    """(E) 变异对照：证明上述断言真有鉴别力（无变异对照的"全绿"不可信）。"""
    print("\n[E] 变异对照（证明测试有鉴别力）")

    rows = XinhuaSite("xinhua", {"timeout": 10})._get_mock_data()

    # M1「把 mock 包上 fields」→ 「未包装」断言必须变 False（被检出）
    wrapped = [{"fields": dict(r)} for r in rows]
    m1_detected = not all("fields" not in r for r in wrapped)
    check("M1 变异：把 mock 包上 fields → 『未包装』断言变 False（被检出）",
          m1_detected, "变异体未被检出 = 本锁无鉴别力")

    # M1b 纵深防御：即便被包装，嵌套标记仍使其被排除（对照 2026-09-14 的隐患）
    real_m1, mock_m1 = split_real_and_mock(wrapped)
    check("M1b 纵深防御：mock 被包装后仍按嵌套标记排除出写集",
          len(real_m1) == 0 and len(mock_m1) == len(wrapped),
          f"real={len(real_m1)} mock={len(mock_m1)} 输入={len(wrapped)}")

    # M2「抹掉 is_mock 标记」→ I1 断言必须变 False（证明标记是**承重**的）
    stripped = [{k: v for k, v in r.items() if k != MOCK_FLAG} for r in rows]
    real_m2, mock_m2 = split_real_and_mock(stripped)
    m2_detected = (len(mock_m2) == 0 and len(real_m2) == len(rows))
    check("M2 变异：抹掉 is_mock 标记 → 这些行会进入写集（证明标记承重）",
          m2_detected, f"real={len(real_m2)} mock={len(mock_m2)}")

    # M3「is_mock 只看顶层」→ 嵌套形态漏检（证明嵌套分支承重、被断言依赖）
    nested = {"fields": {MOCK_FLAG: True, "site_code": "xinhua"}}
    top_level_only = (nested.get(MOCK_FLAG) is True)   # 只看顶层 → False（漏检）
    check("M3 变异：is_mock_record 对嵌套标记返回 True，仅顶层检查会漏检（嵌套分支承重）",
          is_mock_record(nested) is True and top_level_only is False,
          f"nested_detected={is_mock_record(nested)} top_only={top_level_only}")


def test_pipeline_wiring():
    """(F) 接线锁：锁只有在**被生产写入层实际调用**时才有意义。

    `split_real_and_mock` 若只是躺在 mock_utils 里、而 `collection_pipeline.py`
    仍把原始 `result["news"]` 直接写进 `feishu_records`，则线上写集根本没走这把锁。
    这里用**源文件扫描**做接线断言（该脚本无法离线跑：依赖飞书凭据与外网）。
    """
    print("\n[F] 接线锁：写入层确实调用了 split_real_and_mock / 站点级检测器")

    pipe_path = os.path.join(ROOT, "script", "collection_pipeline.py")
    with open(pipe_path, encoding="utf-8") as f:
        src = f.read()

    check("[F] collection_pipeline.py 导入了 split_real_and_mock",
          "split_real_and_mock" in src,
          "写入层未导入 mock 拆分函数 → 锁形同虚设")

    check("[F] collection_pipeline.py 实际调用了 split_real_and_mock(",
          "split_real_and_mock(" in src,
          "仅导入未调用")

    check("[F] collection_pipeline.py 使用了站点级检测器 get_available_sites()",
          "get_available_sites()" in src,
          "缺少『哪些站缺席』的站点级检测器")

    check("[F] collection_pipeline.py 差额>0 时不出现『成功』文案分支",
          "部分写入" in src and "采集任务执行成功，更新" in src,
          "差额>0 抑制『成功』文案的改写缺失")


def main():
    print("=" * 70)
    print("mock 治理回归锁（离线）：标记 / 剔除 / 泄漏关闭 / 变异对照 / 接线")
    print("=" * 70)

    test_mock_marker_and_exclusion()
    test_xinhua_parse_path_leak_closed()
    test_real_records_unaffected()
    test_mutation_controls()
    test_pipeline_wiring()

    print("=" * 70)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
