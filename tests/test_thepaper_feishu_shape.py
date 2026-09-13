#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
thepaper → 飞书写入「形状契约」回归测试（离线，无外网）。

背景（根因）：sites/thepaper.py 的 collect() 曾返回**扁平 dict**，而飞书批写层
FeishuService._align_records_with_fields 要求每条记录是 {"fields": item} 形状，
对「缺 'fields' 键」的记录直接 `continue` 静默丢弃 → thepaper 采到 100 条、
入库 0 条（且不报错、无日志）。其余 8 个站点都做了包装，唯 thepaper 漏了。

本测试用 thepaper 的**真实 collect() 输出**喂进**真实的 _align_records_with_fields**，
断言：
  ① collect() 输出非空；
  ② 每个元素都有 "fields" 键（{"fields": item} 形状契约）；
  ③ 内层 fields 键集合 == TABLE_PLANS['headlines'] 的 12 个字段（field_rules.py:176）；
  ④ 每条 site_code == 'thepaper'；
  ⑤ 经真实对齐后**一条都不被丢**（len 相等且 > 0），字段集完整、site_code 保留。

变异对照（证明有鉴别力）：把 thepaper.py 返回处的包装去掉 → ②③⑤ 必 FAIL。

依赖桩（**条件桩**；判据同 tests/test_thepaper_collection.py：
「桩的合法性 = 被桩模块的行为是否被断言依赖」）：
  aiohttp / httpx / lark_oapi / pydantic_settings 等只在 ImportError 时才补桩——
  它们的行为**不被**本测试的断言依赖，仅需让 import 通过；采集/对齐是纯逻辑、不联网。

    python tests/test_thepaper_feishu_shape.py     # 期望 RC=0（修复后；修复前/变异后 RC=1）
"""

import asyncio
import os
import sys
import types

# ---------------------------------------------------------------------------
# 条件依赖桩（仅在缺失时注入，绝不覆盖已安装的真实包）
# ---------------------------------------------------------------------------
def _stub_module(name):
    m = types.ModuleType(name)
    # 返回「类」，兼容 `from x import Base` + `class Y(Base)`
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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.collection.sites.thepaper import ThepaperSite, MAX_RESULTS  # noqa: E402
from app.services.feishu.feishu_service import FeishuService                   # noqa: E402
from app.services.feishu.field_rules import TABLE_PLANS                       # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


def _thepaper_item(i):
    """thepaper.py 采集层产出的 item 键集合（须与 headlines 12 字段一致）。"""
    return {
        "id": f"tp{i}",
        "title": f"澎湃标题{i}",
        "url": f"https://www.thepaper.cn/newsDetail_forward_{i}",
        "hot": str(100000 - i),
        "rank": str(i + 1),
        "published_at": "2026-09-14 00:00:00",
        "collected_at": "2026-09-14 00:00:00",
        "site_code": "thepaper",
        "category": "热榜",
        "content": "",
        "author": "澎湃新闻",
        "status": "collected",
    }


def _make_offline_site(items):
    """不联网的 ThepaperSite：主页解析直接返回 items，并跳过 7 个分类页
    （否则 collect() 会对分类页做 2+3+...+8 秒 sleep，测试会拖到 ~35s）。
    口径与 tests/test_thepaper_collection.py 一致。"""
    site = ThepaperSite("thepaper", {"timeout": 15})
    site.category_urls = []

    class _FakeResp:
        status = 200

        async def text(self):
            return "<html></html>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def get(self, *args, **kwargs):
            return _FakeResp()

        async def close(self):
            return None

    async def _fake_get_session():
        return _FakeSession()

    site.get_session = _fake_get_session
    site._parse_thepaper_hot_ranking = lambda text: list(items)
    site._parse_category_page = lambda text, url: []
    return site


async def main():
    print("=" * 66)
    print("thepaper → 飞书 形状契约回归（离线）")
    print("=" * 66)

    expected_fields = set(TABLE_PLANS["headlines"]["fields"])
    check("headlines 规划字段数为 12（field_rules.py:176）",
          len(expected_fields) == 12, f"{sorted(expected_fields)}")

    n = 30
    site = _make_offline_site([_thepaper_item(i) for i in range(n)])
    out = await site.collect({})

    check("① collect() 返回非空 list",
          isinstance(out, list) and len(out) > 0, f"len={len(out)}")

    # ② 形状契约：每个元素都必须含 "fields" 键
    all_wrapped = all(isinstance(r, dict) and "fields" in r for r in out)
    check("② 每个元素都含 'fields' 键（{'fields': item} 形状）", all_wrapped,
          f"首个元素键={list(out[0].keys()) if out else 'N/A'}")

    # ③ 内层键集合 == headlines 12 字段
    inner_ok = all(set(r.get("fields", {}).keys()) == expected_fields for r in out)
    check("③ 内层字段集 == headlines 12 字段", inner_ok,
          f"首条内层键={sorted(out[0].get('fields', {}).keys()) if out else 'N/A'}")

    # ④ site_code 归属
    site_ok = all(r.get("fields", {}).get("site_code") == "thepaper" for r in out)
    check("④ 每条 site_code == 'thepaper'", site_ok)

    # ⑤ 真实对齐：一条都不丢（这是与线上写入层同一段逻辑）
    svc = object.__new__(FeishuService)  # 绕过 __init__，不联网、不读配置
    aligned = svc._align_records_with_fields(out, expected_fields)
    check("⑤ 真实对齐后一条都不丢（len 相等且 > 0）",
          len(aligned) == len(out) and len(aligned) > 0,
          f"out={len(out)} aligned={len(aligned)}")
    check("⑤b 对齐后字段集完整且 site_code 保留",
          all(set(a["fields"].keys()) == expected_fields
              and a["fields"].get("site_code") == "thepaper" for a in aligned),
          f"样例={aligned[0] if aligned else 'N/A'}")

    # ⑥ 授权2：形状不符（扁平 dict）时必须**发出 warning**，不得再静默丢弃
    import logging
    from app.services.feishu import feishu_service as _fsmod

    records_log = []

    class _MemHandler(logging.Handler):
        def emit(self, record):
            records_log.append(record)

    handler = _MemHandler()
    _fsmod.logger.addHandler(handler)
    try:
        dropped_out = svc._align_records_with_fields(
            [_thepaper_item(0)], expected_fields)  # 故意喂扁平项（模拟未修复）
    finally:
        _fsmod.logger.removeHandler(handler)

    check("⑥ 扁平记录确实被丢弃（len==0，模拟未修复时的行为）",
          len(dropped_out) == 0, f"len={len(dropped_out)}")
    check("⑥b 丢弃时确实发出 warning 且含条数/样例（授权2）",
          any("丢弃" in r.getMessage() for r in records_log),
          f"captured={[r.getMessage()[:50] for r in records_log]}")

    print("=" * 66)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
