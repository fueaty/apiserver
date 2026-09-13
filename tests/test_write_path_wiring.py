#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
写路径**行为级**接线锁（Task #44 / P0-B + N3）—— 离线，无外网。

为什么要行为级（而不是文本锁）：#42 的两把"接线锁"只断言**源码文本里出现过某函数名**，
对**行为失效**完全无感。典型变异（本文件必须全部检出，见随附突变脚本）：
  · G2：`if is_mock_record(x): ...; continue` 里的 `continue` 改成 `pass`
        —— "检查了，却不生效"，mock 会继续被重建并静默入库；文本锁 RC=0。
  · G3：调用了按标记剔除的函数，却**忽略其返回值**（仍用未过滤的列表）——文本锁亦 RC=0。

本文件用**纯函数 + 桩驱动**两层行为断言：
  [1] write_set.split_write_set(collection_results)：喂「真实站 + mock 站」混合批次，
      断言返回的 real 里 mock==0、mock 里 100%（G3 的直击点）。
  [2] write_set.build_headline_records(results)：喂「真实行 + 带标记 mock 行」混合批次，
      断言最终 feishu_records 里 mock==0、mock_skipped 计数正确（G2 的直击点）。
  [3] **桩驱动跑真实 script/collection_pipeline.py**：把引擎/飞书/通知换成假件，
      运行 test_collection_pipeline()，断言**真正传给 batch_add_records 的记录**里 mock==0。
  [4] **桩驱动跑真实 app/api/v1/endpoints/feishu.py 的 /sync**（N3）：混入带标记 mock，
      断言**真正传给 batch_add_records 的记录**里 mock==0。

依赖桩（**条件桩**；判据：桩的合法性 = 被桩模块的行为是否被断言依赖）：
  这里断言的是**写路径自身**的过滤行为；被桩的采集引擎/飞书 SDK/通知的行为**不被断言依赖**。
  fastapi/jose 桩仅用于让端点模块可导入（装饰器透传），其行为不参与断言。

    python tests/test_write_path_wiring.py     # 期望 RC=0
"""

import asyncio
import datetime
import importlib
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


# ---------------------------------------------------------------------------
# 假件（写路径的行为不依赖它们的真实性，只借用其"接口"）
# ---------------------------------------------------------------------------
class _FakeFeishuService:
    """记下最后一次 batch_add_records 收到的记录（断言的核心）。"""

    last = None

    def __init__(self):
        _FakeFeishuService.last = self
        self.added = None
        self.deleted_count = 0

    async def ensure_table_fields(self, *a, **k):
        return True, "ok"

    async def list_records(self, *a, **k):
        return {"items": []}          # 今日无既有记录 → 不触发去重/删除分支

    async def delete_records(self, *a, **k):
        return 0

    async def ensure_capacity(self, app_token, table_id, incoming=0):
        return {"ok": True, "message": "ok", "count_after": incoming,
                "deleted_total": 0, "deleted_by_capacity": 0}

    async def batch_add_records(self, app_token, table_id, records):
        self.added = list(records or [])
        return {"code": 0, "data": {"records": [{"record_id": f"r{i}"} for i, _ in enumerate(records or [])]}}


class _FakeEngine:
    results = []

    def __init__(self):
        pass

    async def collect(self, params):
        return _FakeEngine.results

    def get_available_sites(self):
        return [{"site_code": r["site_code"]} for r in _FakeEngine.results]


class _FakeSelectionEngine:
    def __init__(self):
        pass


def _parse_record_time(value):
    return datetime.datetime.now()


def _install_light_stubs():
    """装桩：使 script/collection_pipeline.py 与 feishu 端点可在离线环境导入。"""
    from app.services.collection.mock_utils import MOCK_FLAG  # noqa  (real)

    # 采集/选材引擎 + 飞书 SDK + 通知 + 配置 + 字段规划：全部替换为假件
    _mod("app.services.collection.engine", CollectionEngine=_FakeEngine)
    _mod("app.services.selection.engine", SelectionEngine=_FakeSelectionEngine)
    _mod("app.services.feishu.feishu_service",
         FeishuService=_FakeFeishuService, parse_record_time=_parse_record_time)
    _mod("app.services.feishu.limits",
         LIST_PAGE_SIZE=500, TABLE_RECORD_LIMIT=20000,
         ERR_RECORD_EXCEED_LIMIT=1254103, describe=lambda c: f"count={c}")
    _mod("app.services.feishu.field_rules",
         TABLE_PLANS={"headlines": {"fields": []}, "content_selection": {"fields": []}})
    _mod("app.core.config",
         settings=type("S", (), {"LOG_LEVEL": "INFO", "LOG_FILE": "", "SECRET_KEY": "x",
                                 "ALGORITHM": "HS256", "ACCESS_TOKEN_EXPIRE_MINUTES": 120})(),
         config_manager=type("CM", (), {
             "get_credentials": staticmethod(lambda *a, **k: {
                 "feishu": {"tables": {
                     "headlines": {"app_token": "app", "table_id": "tbl"},
                     "content_selection": {"app_token": "app2", "table_id": "tbl2"},
                 }},
             }),
         })())
    _mod("app.wework")
    _mod("app.wework.notification_push", send_message=lambda msg: None)


def _install_fastapi_stubs():
    """最小 fastapi/jose 桩：只为让端点模块可导入（装饰器透传给原函数）。"""
    try:
        import fastapi  # noqa: F401
        import jose     # noqa: F401
        return
    except Exception:
        pass

    class _Any:
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return self

        def __getattr__(self, name):
            return _Any()

    def _deco(*a, **k):
        def _wrap(fn):
            return fn
        return _wrap

    class _Router:
        def __init__(self, *a, **k):
            pass

        def post(self, *a, **k):
            return _deco()

        def get(self, *a, **k):
            return _deco()

        def put(self, *a, **k):
            return _deco()

        def delete(self, *a, **k):
            return _deco()

    fastapi = _mod("fastapi", APIRouter=_Router, Depends=lambda *a, **k: _Any(),
                   Body=lambda *a, **k: _Any(), Query=lambda *a, **k: _Any(),
                   Path=lambda *a, **k: _Any(), status=_Any(),
                   HTTPException=type("HTTPException", (Exception,), {}))
    sec = _mod("fastapi.security", HTTPBearer=lambda *a, **k: _Any(),
               HTTPAuthorizationCredentials=_Any)
    fastapi.security = sec
    _mod("jose", JWTError=type("JWTError", (Exception,), {}), jwt=_Any())


# ---------------------------------------------------------------------------
# [1] split_write_set：G3 的直击点
# ---------------------------------------------------------------------------
def _mk_news(title, mock=False, wrapped=True):
    body = {"title": title, "url": f"https://x/{title}", "hot": 100, "rank": 1,
            "site_code": "s"}
    if mock:
        body["is_mock"] = True
    return {"fields": body} if wrapped else body


def test_split_write_set_behavior():
    print("\n[1] split_write_set：混合批次 → real 里 mock==0（G3 直击点）")
    from app.services.collection.write_set import split_write_set
    from app.services.collection.mock_utils import is_mock_record

    real_rows = [_mk_news("真实A"), _mk_news("真实B")]
    mock_rows = [_mk_news("示例C", mock=True), _mk_news("示例D", mock=True)]
    results = [
        {"site_code": "s_real", "collect_time": "t", "data_count": 2, "news": real_rows},
        {"site_code": "s_mock", "collect_time": "t", "data_count": 2, "news": mock_rows},
    ]

    real, mock = split_write_set(results)
    check("[1] real 里 mock==0", len([r for r in real if is_mock_record(r)]) == 0,
          f"real={real!r}")
    check("[1] mock 里 100% 判为 mock", len(mock) == 2 and all(is_mock_record(r) for r in mock),
          f"mock={mock!r}")
    check("[1] real==2 且内容为真实行", len(real) == 2, f"real_len={len(real)}")

    # G3 变异语义：若"忽略了 split 的返回值、直接用未过滤的 raw" → real 会含 mock → 变红
    raw = [r for res in results for r in res["news"]]
    check("[1] G3 对照：未过滤 raw 里确实含 mock（证明『忽略返回值』会被本断言检出）",
          len([r for r in raw if is_mock_record(r)]) == 2, f"raw_mock={len(raw)}")


# ---------------------------------------------------------------------------
# [2] build_headline_records：G2 的直击点
# ---------------------------------------------------------------------------
def test_build_headline_records_behavior():
    print("\n[2] build_headline_records：混合批次 → feishu_records 里 mock==0（G2 直击点）")
    from app.services.collection.write_set import build_headline_records
    from app.services.collection.mock_utils import is_mock_record

    news = [
        _mk_news("真实1"),
        _mk_news("示例2", mock=True),
        _mk_news("真实3"),
        {"fields": {"is_mock": True, "title": "示例4", "url": "u"}},
    ]
    results = [{"site_code": "s1", "collect_time": "t", "data_count": 4, "news": news}]

    optimized, records, skipped = build_headline_records(results, category="科技")

    check("[2] mock_skipped 计数 == 2", skipped == 2, f"skipped={skipped}")
    check("[2] feishu_records 里 mock==0", len([r for r in records if is_mock_record(r)]) == 0,
          f"records={records!r}")
    check("[2] feishu_records 条数 == 真实行 2 条", len(records) == 2, f"len={len(records)}")
    check("[2] optimized.news 里 mock==0",
          len([n for n in optimized[0]["news"] if is_mock_record(n)]) == 0,
          f"optimized={optimized!r}")
    check("[2] 真实标题被保留（真实1、真实3）",
          sorted(r["fields"]["title"] for r in records) == ["真实1", "真实3"],
          f"titles={[r['fields']['title'] for r in records]}")

    # G2 变异语义：若把过滤里的 `continue` 改成 `pass`，filter 行会被重建并 append
    #   （因为过滤分支下面的代码不再被跳过）→ records 里会出现 mock → 变红。
    check("[2] G2 对照：批次里确实混入了带标记 mock（证明 continue→pass 会被本断言检出）",
          any(is_mock_record(n) for n in news), "")


# ---------------------------------------------------------------------------
# [3] 桩驱动跑真实 pipeline：真正传给 batch_add_records 的记录里 mock==0
# ---------------------------------------------------------------------------
def test_stub_driven_pipeline():
    print("\n[3] 桩驱动真实 script/collection_pipeline.py：batch_add_records 里 mock==0")
    _install_light_stubs()

    _FakeEngine.results = [
        {"site_code": "s_real", "collect_time": "t", "data_count": 2,
         "news": [_mk_news("真实A"), _mk_news("真实B")]},
        {"site_code": "s_mock", "collect_time": "t", "data_count": 2,
         "news": [_mk_news("示例C", mock=True), _mk_news("示例D", mock=True)]},
    ]

    spec = importlib.util.spec_from_file_location(
        "_pipeline_under_test", os.path.join(ROOT, "script", "collection_pipeline.py"))
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)

    ok = asyncio.run(pipeline.test_collection_pipeline())

    from app.services.collection.mock_utils import is_mock_record
    captured = _FakeFeishuService.last.added
    check("[3] 流水线执行成功返回 True", ok is True, f"ok={ok}")
    check("[3] batch_add_records 确实被调用", captured is not None, "未捕获到写入记录")
    if captured is not None:
        mocked = [r for r in captured if is_mock_record(r)]
        check("[3] **真正写入的记录**里 mock==0", len(mocked) == 0, f"mocked={mocked!r}")
        check("[3] 只写入 2 条真实记录", len(captured) == 2, f"len={len(captured)}")


# ---------------------------------------------------------------------------
# [4] 桩驱动跑真实 feishu 端点 /sync（N3）
# ---------------------------------------------------------------------------
def test_stub_driven_feishu_sync_n3():
    print("\n[4] N3：真实 feishu.py /sync → batch_add_records 里 mock==0")
    _install_light_stubs()
    _install_fastapi_stubs()

    # 让 app.api.v1 走轻量桩，避免导入 v1/__init__.py（它会拉起全部端点）
    v1 = types.ModuleType("app.api.v1")
    v1.__path__ = [os.path.join(ROOT, "app", "api", "v1")]
    sys.modules["app.api.v1"] = v1

    feishu_ep = importlib.import_module("app.api.v1.endpoints.feishu")

    mixed = [
        _mk_news("真实X"),
        _mk_news("示例Y", mock=True),
        {"is_mock": True, "title": "示例Z", "url": "u"},  # 扁平带标记
        _mk_news("真实W", wrapped=False),
    ]
    asyncio.run(feishu_ep.sync_to_feishu(app_token="app", table_id="tbl",
                                         records=mixed, current_user=None))

    from app.services.collection.mock_utils import is_mock_record
    captured = _FakeFeishuService.last.added
    check("[4] /sync 调用了 batch_add_records", captured is not None, "未捕获到写入记录")
    if captured is not None:
        mocked = [r for r in captured if is_mock_record(r)]
        check("[4] /sync **真正写入的记录**里 mock==0", len(mocked) == 0, f"mocked={mocked!r}")
        check("[4] /sync 仅保留 2 条真实记录", len(captured) == 2, f"len={len(captured)}")


def main():
    print("=" * 70)
    print("写路径行为级接线锁（离线）：split_write_set / build_headline_records / 桩驱动 pipeline / N3")
    print("=" * 70)

    test_split_write_set_behavior()
    test_build_headline_records_behavior()
    test_stub_driven_pipeline()
    test_stub_driven_feishu_sync_n3()

    print("=" * 70)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
