#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正文采集端点契约回归测试（需求②）

覆盖 /collection/content/fetch 与 /collection/content/backfill：
  - urls/record_ids 均空 -> 400；record_ids 全查不到 -> 404；部分成功 -> 200
  - 逐条 status；单条失败不 500
  - write_back 覆盖策略（仅空时写 / overwrite）
  - backfill dry_run 只返回计划、不抓取不写入

桩化 FeishuService / ContentFetcher / fastapi / pydantic，不联网、不装依赖：

    python tests/test_content_endpoint.py
"""

import os
import sys
import types
import asyncio
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_DIR = os.path.join(ROOT, "app", "services", "collection")
FEISHU_DIR = os.path.join(ROOT, "app", "services", "feishu")

# ---------------------------------------------------------------------------
# 1. fastapi / pydantic 桩
# ---------------------------------------------------------------------------
fastapi_stub = types.ModuleType("fastapi")


class _Router:
    def post(self, *a, **k):
        def deco(fn):
            return fn
        return deco

    def get(self, *a, **k):
        def deco(fn):
            return fn
        return deco


class _HTTPException(Exception):
    def __init__(self, status_code=500, detail=None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


fastapi_stub.APIRouter = lambda *a, **k: _Router()
fastapi_stub.Depends = lambda *a, **k: None
fastapi_stub.Query = lambda *a, **k: None
fastapi_stub.Body = lambda *a, **k: None
fastapi_stub.HTTPException = _HTTPException
sys.modules["fastapi"] = fastapi_stub


class _BaseModel:
    def __init__(self, **kwargs):
        annotations = getattr(type(self), "__annotations__", {}) or {}
        for name in annotations:
            setattr(self, name, kwargs.pop(name, getattr(type(self), name, None)))
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self):
        return dict(self.__dict__)


pydantic_stub = types.ModuleType("pydantic")
pydantic_stub.BaseModel = _BaseModel
sys.modules["pydantic"] = pydantic_stub

# ---------------------------------------------------------------------------
# 2. app 包骨架 + 轻量桩
# ---------------------------------------------------------------------------
for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.utils", os.path.join(ROOT, "app", "utils")),
    ("app.api", os.path.join(ROOT, "app", "api")),
    ("app.api.v1", os.path.join(ROOT, "app", "api", "v1")),
    ("app.api.v1.endpoints", os.path.join(ROOT, "app", "api", "v1", "endpoints")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.collection", COLLECTION_DIR),
    ("app.services.feishu", FEISHU_DIR),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

CREDS = {
    "feishu": {"tables": {
        "headlines": {"app_token": "hlTok", "table_id": "hlTbl"},
        "ai_insights": {"app_token": "aiTok", "table_id": "aiTbl"},
    }}
}
config_stub = types.ModuleType("app.core.config")
config_stub.config_manager = types.SimpleNamespace(
    get_credentials=lambda force_reload=False: CREDS,
    get_config=lambda force_reload=False: {},
    get_sites_config=lambda force_reload=False: {"sites": {}},
)
sys.modules["app.core.config"] = config_stub

logger_stub = types.ModuleType("app.utils.logger")


class _Logger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


logger_stub.logger = _Logger()
sys.modules["app.utils.logger"] = logger_stub

auth_stub = types.ModuleType("app.api.v1.endpoints.auth")
auth_stub.verify_token = lambda: None
sys.modules["app.api.v1.endpoints.auth"] = auth_stub


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cf = _load("app.services.collection.content_fetcher",
           os.path.join(COLLECTION_DIR, "content_fetcher.py"))
_load("app.services.feishu.limits", os.path.join(FEISHU_DIR, "limits.py"))
content = _load("app.api.v1.endpoints.content",
                os.path.join(ROOT, "app", "api", "v1", "endpoints", "content.py"))

FetchItem = cf.FetchItem
FetchOutcome = cf.FetchOutcome
ContentFetchRequest = content.ContentFetchRequest
ContentBackfillRequest = content.ContentBackfillRequest

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s" % name)
    else:
        FAILED.append(name + (" :: " + str(detail) if detail else ""))
        print("  [FAIL] %s  %s" % (name, detail))


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------
class FakeFeishu:
    def __init__(self, items=None, online_fields=None):
        self.items = items or []
        self.online_fields = online_fields or {}
        self.updates = []

    async def list_records(self, app_token, table_id, page_size=10, page_token=None):
        return {"items": self.items, "page_token": None}

    async def get_table_fields_uncached(self, app_token, table_id):
        return self.online_fields

    async def batch_update_records(self, app_token, table_id, records, align=False):
        self.updates.append(records)
        return {"code": 0, "msg": "success",
                "data": {"records": records, "updated": len(records)}}


class FakeFetcher:
    """按 url 返回预设 outcome。"""

    def __init__(self, outcomes):
        self.outcomes = outcomes  # Dict[url, FetchOutcome]
        self.calls = []

    async def fetch_many(self, items, concurrency=None, timeout=None):
        self.calls.append((len(items), concurrency, timeout))
        return [self.outcomes[it.url] for it in items]


def ok_outcome(url, content_text, record_id=None):
    return FetchOutcome(url=url, record_id=record_id, status="success",
                        content=content_text, content_length=len(content_text),
                        extractor="generic")


def fail_outcome(url, record_id=None, code="FETCH_TIMEOUT"):
    return FetchOutcome(url=url, record_id=record_id, status="failed",
                        error_code=code, error_message="boom", retryable=True)


def expect_http_error(fn, code):
    try:
        asyncio.run(fn())
    except _HTTPException as exc:
        return exc.status_code == code, exc.status_code
    except Exception as exc:  # noqa: BLE001
        return False, "other:%r" % exc
    return False, "no-raise"


def run():
    print("=" * 72)
    print("正文采集端点契约回归测试")
    print("=" * 72)

    # [1] 400：urls 与 record_ids 均空
    print("\n[1] fetch: 400 分支")
    ok, got = expect_http_error(
        lambda: content.fetch_content(ContentFetchRequest(), payload={}), 400)
    check("均空 -> 400", ok, got)

    # [2] 404：record_ids 全查不到
    print("\n[2] fetch: 404 分支")
    fake = FakeFeishu(items=[{"record_id": "recX", "fields": {"id": "bizX", "url": "https://x"}}])
    content._get_feishu_service = lambda: fake
    ok, got = expect_http_error(
        lambda: content.fetch_content(ContentFetchRequest(record_ids=["nope"]), payload={}), 404)
    check("全查不到 -> 404", ok, got)

    # [3] record_ids 部分命中 -> 200（双键：record_id / fields['id']）
    print("\n[3] fetch: record_ids 命中（双键索引）-> 200")
    fake = FakeFeishu(items=[
        {"record_id": "rec1", "fields": {"id": "biz1", "url": "https://a/1", "content": ""}},
        {"record_id": "rec2", "fields": {"id": "biz2", "url": "https://a/2", "content": "旧内容"}},
    ])
    content._get_feishu_service = lambda: fake
    content._get_fetcher = lambda sites: FakeFetcher({
        "https://a/1": ok_outcome("https://a/1", "正文1", record_id="rec1"),
        "https://a/2": ok_outcome("https://a/2", "正文2", record_id="rec2"),
    })
    resp = asyncio.run(content.fetch_content(
        ContentFetchRequest(record_ids=["rec1", "biz2"]), payload={}))
    check("返回 200 code", resp["code"] == 200, resp["code"])
    check("total=2", resp["data"]["total"] == 2, resp["data"]["total"])
    check("succeeded=2", resp["data"]["succeeded"] == 2, resp["data"]["succeeded"])
    check("逐条含 status", all("status" in r for r in resp["data"]["results"]))

    # [4] urls 路径 + 部分失败仍 200
    print("\n[4] fetch: urls 路径部分失败 -> 200")
    content._get_fetcher = lambda sites: FakeFetcher({
        "https://a/ok": ok_outcome("https://a/ok", "好的正文"),
        "https://a/bad": fail_outcome("https://a/bad"),
    })
    resp = asyncio.run(content.fetch_content(
        ContentFetchRequest(urls=["https://a/ok", "https://a/bad"]), payload={}))
    check("整体 200", resp["code"] == 200)
    check("succeeded=1", resp["data"]["succeeded"] == 1, resp["data"]["succeeded"])
    check("failed=1", resp["data"]["failed"] == 1, resp["data"]["failed"])
    statuses = {r["url"]: r["status"] for r in resp["data"]["results"]}
    check("失败条 error_code 透传",
          any(r.get("error_code") == "FETCH_TIMEOUT" for r in resp["data"]["results"]))

    # [5] write_back 覆盖策略
    print("\n[5] fetch: write_back 覆盖策略")
    fake = FakeFeishu(items=[
        {"record_id": "rec1", "fields": {"id": "biz1", "url": "https://a/1", "content": ""}},
        {"record_id": "rec2", "fields": {"id": "biz2", "url": "https://a/2", "content": "旧内容"}},
    ])
    content._get_feishu_service = lambda: fake
    content._get_fetcher = lambda sites: FakeFetcher({
        "https://a/1": ok_outcome("https://a/1", "新1", record_id="rec1"),
        "https://a/2": ok_outcome("https://a/2", "新2", record_id="rec2"),
    })
    resp = asyncio.run(content.fetch_content(
        ContentFetchRequest(record_ids=["rec1", "rec2"], write_back=True), payload={}))
    check("默认仅空 content 回写（1 条）", resp["data"]["written"] == 1, resp["data"]["written"])
    check("仅 rec1 被更新", fake.updates and
          [u["record_id"] for u in fake.updates[0]] == ["rec1"],
          fake.updates)

    fake2 = FakeFeishu(items=[
        {"record_id": "rec2", "fields": {"id": "biz2", "url": "https://a/2", "content": "旧内容"}},
    ])
    content._get_feishu_service = lambda: fake2
    resp2 = asyncio.run(content.fetch_content(
        ContentFetchRequest(record_ids=["rec2"], write_back=True, overwrite=True), payload={}))
    check("overwrite=True 覆盖旧值（1 条）", resp2["data"]["written"] == 1, resp2["data"]["written"])

    # [6] backfill dry_run
    print("\n[6] backfill: dry_run 只返回计划")
    fake = FakeFeishu(items=[
        {"record_id": "rec1", "fields": {"id": "b1", "url": "https://a/1", "content": "", "site_code": "s"}},
        {"record_id": "rec2", "fields": {"id": "b2", "url": "https://a/2", "content": "有内容", "site_code": "s"}},
    ])
    content._get_feishu_service = lambda: fake

    def _explode(sites):
        raise AssertionError("dry_run 不得构造 fetcher")

    content._get_fetcher = _explode
    resp = asyncio.run(content.backfill_content(
        ContentBackfillRequest(limit=50, dry_run=True), payload={}))
    check("planned=1（仅空 content）", resp["data"]["planned"] == 1, resp["data"]["planned"])
    check("fetched=0", resp["data"]["fetched"] == 0)
    check("written=0", resp["data"]["written"] == 0)
    check("dry_run 未构造 fetcher", True)

    # [7] backfill 实跑
    print("\n[7] backfill: 实跑抓取 + 回写")
    fake = FakeFeishu(items=[
        {"record_id": "rec1", "fields": {"id": "b1", "url": "https://a/1", "content": "", "site_code": "s"}},
    ])
    content._get_feishu_service = lambda: fake
    content._get_fetcher = lambda sites: FakeFetcher({
        "https://a/1": ok_outcome("https://a/1", "回填正文", record_id="rec1"),
    })
    resp = asyncio.run(content.backfill_content(
        ContentBackfillRequest(limit=10, dry_run=False), payload={}))
    check("planned=1", resp["data"]["planned"] == 1, resp["data"]["planned"])
    check("fetched=1", resp["data"]["fetched"] == 1, resp["data"]["fetched"])
    check("written=1", resp["data"]["written"] == 1, resp["data"]["written"])
    check("确实调用了 batch_update_records", fake.updates and len(fake.updates) == 1, fake.updates)

    print("\n" + "=" * 72)
    print("PASSED: %d    FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("-" * 72)
        for f in FAILED:
            print("  FAILED -> %s" % f)
    print("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(run())
