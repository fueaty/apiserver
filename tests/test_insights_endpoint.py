#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_insights 端点契约回归测试（需求③）

覆盖 /analysis/insights/generate 与 /analysis/insights/preflight：
  - record_ids/urls 均空 -> 400；headlines 记录全不存在 -> 404
  - Mock 模式端到端 written>=1
  - 写入前 schema 未确认 -> 逐条 TABLE_SCHEMA_UNCONFIRMED 且不写入
  - preflight 返回 llm{...} + table{schema_confirmed, missing_fields}
  - dry_run 不写入

桩化 FeishuService（真 LLM 走 Mock 分支）、fastapi / pydantic，不联网、不装依赖：

    python tests/test_insights_endpoint.py
"""

import os
import sys
import types
import asyncio
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.join(ROOT, "app", "services", "analysis")
FA_DIR = os.path.join(ANALYSIS_DIR, "feature_analysis")
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
# 2. 第三方依赖桩
# ---------------------------------------------------------------------------
httpx_stub = types.ModuleType("httpx")
httpx_stub.AsyncClient = object
httpx_stub.Client = object
sys.modules["httpx"] = httpx_stub

lark_stub = types.ModuleType("lark_oapi")
lark_stub.__path__ = []
lark_stub.LogLevel = types.SimpleNamespace(INFO=1, DEBUG=2)
sys.modules["lark_oapi"] = lark_stub
for name in ("lark_oapi.api", "lark_oapi.api.bitable", "lark_oapi.api.bitable.v1"):
    m = types.ModuleType(name)
    m.__path__ = []
    sys.modules[name] = m
sys.modules["lark_oapi.api.bitable.v1"].__dict__["*"] = None

# ---------------------------------------------------------------------------
# 3. app 包骨架 + 轻量桩
# ---------------------------------------------------------------------------
for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.utils", os.path.join(ROOT, "app", "utils")),
    ("app.api", os.path.join(ROOT, "app", "api")),
    ("app.api.v1", os.path.join(ROOT, "app", "api", "v1")),
    ("app.api.v1.endpoints", os.path.join(ROOT, "app", "api", "v1", "endpoints")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.analysis", ANALYSIS_DIR),
    ("app.services.analysis.feature_analysis", FA_DIR),
    ("app.services.feishu", FEISHU_DIR),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

CREDS = {
    "feishu": {"tables": {
        "headlines": {"app_token": "hlTok", "table_id": "hlTbl"},
        "ai_insights": {"app_token": "aiTok", "table_id": "aiTbl"},
    }},
    "llm": {},  # 无 api_key -> 必须走 Mock
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


llm_clients = _load("app.services.analysis.feature_analysis.llm_clients",
                    os.path.join(FA_DIR, "llm_clients.py"))
_load("app.services.feishu.limits", os.path.join(FEISHU_DIR, "limits.py"))
_load("app.services.feishu.field_rules", os.path.join(FEISHU_DIR, "field_rules.py"))
_load("app.services.feishu.feishu_service", os.path.join(FEISHU_DIR, "feishu_service.py"))
insights_service = _load("app.services.analysis.insights_service",
                         os.path.join(ANALYSIS_DIR, "insights_service.py"))
insights = _load("app.api.v1.endpoints.insights",
                 os.path.join(ROOT, "app", "api", "v1", "endpoints", "insights.py"))

InsightsService = insights_service.InsightsService
AI_INSIGHT_FIELDS = insights_service.AI_INSIGHT_FIELDS
TABLE_SCHEMA_UNCONFIRMED = insights_service.TABLE_SCHEMA_UNCONFIRMED
InsightsGenerateRequest = insights.InsightsGenerateRequest

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
        self.added = []

    async def list_records(self, app_token, table_id, page_size=10, page_token=None):
        return {"items": self.items, "page_token": None}

    async def get_table_fields_uncached(self, app_token, table_id):
        return self.online_fields

    async def batch_add_records(self, app_token, table_id, records, _retry_on_full=True):
        self.added.append(records)
        return {"code": 0, "msg": "success",
                "data": {"records": [{"record_id": "r%d" % i} for i in range(len(records))]}}


HEADLINE_ITEM = {
    "record_id": "rec1",
    "fields": {
        "id": "biz1",
        "title": "热点标题",
        "url": "https://a/1",
        "content": "正文",
        "author": "作者",
        "category": "分类",
        "published_at": "2025-01-01 12:00:00",
    },
}

ALL_ONLINE = {f: {"id": f, "type": 1, "property": {}} for f in AI_INSIGHT_FIELDS}


def expect_http_error(fn, code):
    try:
        asyncio.run(fn())
    except _HTTPException as exc:
        return exc.status_code == code, exc.status_code
    except Exception as exc:  # noqa: BLE001
        return False, "other:%r" % exc
    return False, "no-raise"


def _install_service(fake):
    insights._get_service = lambda: InsightsService(feishu_service=fake)


def run():
    print("=" * 72)
    print("ai_insights 端点契约回归测试")
    print("=" * 72)

    # [1] 400：来源为空
    print("\n[1] generate: 400 分支")
    ok, got = expect_http_error(
        lambda: insights.generate_insights(InsightsGenerateRequest(), payload={}), 400)
    check("均空 -> 400", ok, got)

    # [2] 404：记录全不存在
    print("\n[2] generate: 404 分支")
    _install_service(FakeFeishu(items=[HEADLINE_ITEM], online_fields=ALL_ONLINE))
    ok, got = expect_http_error(
        lambda: insights.generate_insights(InsightsGenerateRequest(record_ids=["nope"]), payload={}), 404)
    check("全不存在 -> 404", ok, got)

    # [3] Mock 模式端到端 written>=1
    print("\n[3] generate: Mock 端到端 written>=1")
    fake = FakeFeishu(items=[HEADLINE_ITEM], online_fields=ALL_ONLINE)
    _install_service(fake)
    resp = asyncio.run(insights.generate_insights(
        InsightsGenerateRequest(record_ids=["rec1"]), payload={}))
    data = resp["data"]
    check("code=200", resp["code"] == 200)
    check("llm_client='mock'", data["llm_client"] == "mock", data["llm_client"])
    check("generated>=1", data["generated"] >= 1, data["generated"])
    check("written>=1", data["written"] >= 1, data["written"])
    check("确实调用 batch_add_records", len(fake.added) == 1, len(fake.added))
    fields0 = data["results"][0]["fields"]
    check("ai_insights 字段集 == 14", len(fields0) == 14, len(fields0))
    check("status=='generated'", fields0["status"] == "generated", fields0["status"])

    # [4] 业务 id 也能反查
    print("\n[4] generate: 业务 id 反查")
    fake = FakeFeishu(items=[HEADLINE_ITEM], online_fields=ALL_ONLINE)
    _install_service(fake)
    resp = asyncio.run(insights.generate_insights(
        InsightsGenerateRequest(record_ids=["biz1"]), payload={}))
    check("业务字段 id 命中 -> written>=1", resp["data"]["written"] >= 1, resp["data"]["written"])

    # [5] schema 未确认 -> 逐条失败且不写入
    print("\n[5] generate: schema 未确认")
    partial = {f: {} for f in AI_INSIGHT_FIELDS[:5]}  # 缺 9 个字段
    fake = FakeFeishu(items=[HEADLINE_ITEM], online_fields=partial)
    _install_service(fake)
    resp = asyncio.run(insights.generate_insights(
        InsightsGenerateRequest(record_ids=["rec1"]), payload={}))
    r0 = resp["data"]["results"][0]
    check("该条 failed", r0["status"] == "failed", r0["status"])
    check("error_code=TABLE_SCHEMA_UNCONFIRMED",
          r0.get("error_code") == TABLE_SCHEMA_UNCONFIRMED, r0.get("error_code"))
    check("未写入", resp["data"]["written"] == 0, resp["data"]["written"])
    check("未调用 batch_add_records", fake.added == [], fake.added)

    # [6] dry_run 不写入
    print("\n[6] generate: dry_run 不写入")
    fake = FakeFeishu(items=[HEADLINE_ITEM], online_fields=ALL_ONLINE)
    _install_service(fake)
    resp = asyncio.run(insights.generate_insights(
        InsightsGenerateRequest(record_ids=["rec1"], dry_run=True), payload={}))
    check("generated>=1", resp["data"]["generated"] >= 1, resp["data"]["generated"])
    check("written=0", resp["data"]["written"] == 0, resp["data"]["written"])
    check("未调用 batch_add_records", fake.added == [], fake.added)

    # [7] preflight
    print("\n[7] preflight")
    fake = FakeFeishu(items=[HEADLINE_ITEM], online_fields=ALL_ONLINE)
    _install_service(fake)
    resp = asyncio.run(insights.insights_preflight(payload={}))
    check("code=200", resp["code"] == 200)
    check("llm.client='mock'", resp["data"]["llm"]["client"] == "mock", resp["data"]["llm"])
    check("llm.has_api_key=False", resp["data"]["llm"]["has_api_key"] is False)
    check("table.schema_confirmed=True", resp["data"]["table"]["schema_confirmed"] is True,
          resp["data"]["table"])
    check("table.name='ai_insights'", resp["data"]["table"]["name"] == "ai_insights")

    fake2 = FakeFeishu(items=[HEADLINE_ITEM], online_fields=partial)
    _install_service(fake2)
    resp2 = asyncio.run(insights.insights_preflight(payload={}))
    check("缺字段时 schema_confirmed=False", resp2["data"]["table"]["schema_confirmed"] is False)
    check("missing_fields 非空", len(resp2["data"]["table"]["missing_fields"]) > 0,
          resp2["data"]["table"]["missing_fields"])

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
