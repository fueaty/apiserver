#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正文抓取编排回归测试（需求②）

覆盖 ContentFetcher / 纯函数 / 飞书回写接口：
  - 并发不超过配置上限（计数器断言）
  - robots 禁止 -> skipped / ROBOTS_DISALLOWED
  - 单条超时 -> failed / FETCH_TIMEOUT 且不影响其余条目
  - 抽取为空 -> failed / EXTRACT_EMPTY
  - should_write_back 四种组合
  - infer_site_code 域名推断
  - batch_update_records 请求体为含 record_id 的对象数组、按 limits 分片、
    返回 data.updated

自带第三方依赖桩（httpx / lark_oapi / app.core.config），
不联网、不安装项目依赖，直接运行：

    python tests/test_content_fetcher.py
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
# 1. 第三方依赖桩
# ---------------------------------------------------------------------------
httpx_stub = types.ModuleType("httpx")
httpx_stub.AsyncClient = object          # 测试中会被替换
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

# app 包骨架
for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.collection", COLLECTION_DIR),
    ("app.services.feishu", FEISHU_DIR),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

config_stub = types.ModuleType("app.core.config")
config_stub.config_manager = types.SimpleNamespace(get_credentials=lambda: {})
sys.modules["app.core.config"] = config_stub


def _load(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# content_fetcher 通过相对 import 引用 content_extractor，先注册父模块。
ce = _load("app.services.collection.content_extractor",
           os.path.join(COLLECTION_DIR, "content_extractor.py"))
cf = _load("app.services.collection.content_fetcher",
           os.path.join(COLLECTION_DIR, "content_fetcher.py"))

limits = _load("app.services.feishu.limits", os.path.join(FEISHU_DIR, "limits.py"))
_load("app.services.feishu.field_rules", os.path.join(FEISHU_DIR, "field_rules.py"))
svc_mod = _load("app.services.feishu.feishu_service", os.path.join(FEISHU_DIR, "feishu_service.py"))

ContentFetcher = cf.ContentFetcher
FetchItem = cf.FetchItem
FetchOutcome = cf.FetchOutcome
should_write_back = cf.should_write_back
infer_site_code = cf.infer_site_code
BATCH = limits.BATCH_WRITE_LIMIT
FeishuService = svc_mod.FeishuService

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s" % name)
    else:
        FAILED.append(name + (" :: " + str(detail) if detail else ""))
        print("  [FAIL] %s  %s" % (name, detail))


HTML_OK = "<html><head><title>页面标题</title></head><body><article><p>正文内容一二三</p></article></body></html>"
HTML_EMPTY_EXTRACT = "<html><body><script>var x=1;</script></body></html>"


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
def test_should_write_back():
    print("\n[1] should_write_back 覆盖策略")
    check("空现有 + 新值 + 不覆盖 -> True", should_write_back("", "new", False) is True)
    check("有现有 + 新值 + 不覆盖 -> False", should_write_back("old", "new", False) is False)
    check("有现有 + 新值 + 覆盖 -> True", should_write_back("old", "new", True) is True)
    check("新值为空 -> 恒 False", should_write_back("old", "", False) is False)
    check("新值空白 -> 恒 False", should_write_back("old", "   ", True) is False)
    check("现有 None + 不覆盖 -> True", should_write_back(None, "new", False) is True)
    check("现有空白 + 不覆盖 -> True", should_write_back("  ", "new", False) is True)
    check("新值 None + 覆盖 -> False", should_write_back("old", None, True) is False)


def test_infer_site_code():
    print("\n[2] infer_site_code 域名推断")
    cfg = {
        "sites": {
            "thepaper": {"request": {"url": "https://www.thepaper.cn/"}},
            "zhihu": {"request": {"url": "https://www.zhihu.com/api/v3/feed"}},
            "cctv": {"request": {"url": "https://news.cctv.com/rss/news.xml"}},
            "tech_36kr": {"request": {"url": "https://36kr.com/"}},
            "dom_only": {"domains": ["foo.example.com"]},
        }
    }
    check("thepaper", infer_site_code("https://www.thepaper.cn/newsDetail_forward_1", cfg) == "thepaper",
          infer_site_code("https://www.thepaper.cn/newsDetail_forward_1", cfg))
    check("zhihu", infer_site_code("https://www.zhihu.com/question/123", cfg) == "zhihu",
          infer_site_code("https://www.zhihu.com/question/123", cfg))
    check("cctv", infer_site_code("https://news.cctv.com/2024/01/01/x.html", cfg) == "cctv",
          infer_site_code("https://news.cctv.com/2024/01/01/x.html", cfg))
    check("tech_36kr", infer_site_code("https://36kr.com/p/12345", cfg) == "tech_36kr",
          infer_site_code("https://36kr.com/p/12345", cfg))
    check("domains 列表命中", infer_site_code("https://foo.example.com/a/b", cfg) == "dom_only",
          infer_site_code("https://foo.example.com/a/b", cfg))
    check("未知域名 -> None", infer_site_code("https://example.com/x", cfg) is None,
          infer_site_code("https://example.com/x", cfg))
    check("空 URL -> None", infer_site_code("", cfg) is None)


def test_concurrency_cap():
    print("\n[3] fetch_many 并发不超过配置上限")
    state = {"cur": 0, "max": 0}

    async def getter(url, timeout, user_agent):
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        await asyncio.sleep(0.02)
        state["cur"] -= 1
        return HTML_OK

    fetcher = ContentFetcher(http_getter=getter, robots=None, max_concurrency=4)
    items = [FetchItem(url="https://a.com/p/%d" % i) for i in range(12)]
    results = asyncio.run(fetcher.fetch_many(items, concurrency=3))

    check("并发峰值 <= 3", state["max"] <= 3, "max=%d" % state["max"])
    check("并发峰值 > 1（真的并行了）", state["max"] > 1, "max=%d" % state["max"])
    check("结果条数 = 输入条数", len(results) == 12, len(results))
    check("全部 success", all(r.status == "success" for r in results),
          [r.status for r in results])

    # 硬上限收敛
    check("max_concurrency 超 8 被截断", ContentFetcher(max_concurrency=100).max_concurrency == 8,
          ContentFetcher(max_concurrency=100).max_concurrency)
    check("max_concurrency=0 收敛为 1", ContentFetcher(max_concurrency=0).max_concurrency == 1,
          ContentFetcher(max_concurrency=0).max_concurrency)
    check("timeout 超 30 被截断", ContentFetcher(default_timeout=999).default_timeout == 30,
          ContentFetcher(default_timeout=999).default_timeout)


def test_robots_disallowed():
    print("\n[4] robots 禁止 -> skipped / ROBOTS_DISALLOWED")

    class FakeRobots:
        async def can_fetch(self, url, user_agent=None):
            return "blocked" not in url

    async def getter(url, timeout, user_agent):
        return HTML_OK

    fetcher = ContentFetcher(http_getter=getter, robots=FakeRobots())
    blocked = asyncio.run(fetcher.fetch_one(FetchItem(url="https://a.com/blocked/1")))
    allowed = asyncio.run(fetcher.fetch_one(FetchItem(url="https://a.com/ok/1")))

    check("被禁 -> status=skipped", blocked.status == "skipped", blocked.status)
    check("被禁 -> error_code=ROBOTS_DISALLOWED",
          blocked.error_code == cf.ROBOTS_DISALLOWED, blocked.error_code)
    check("被禁 -> retryable=False", blocked.retryable is False, blocked.retryable)
    check("允许 -> success", allowed.status == "success", allowed.status)


def test_timeout_isolated():
    print("\n[5] 单条超时 -> failed / FETCH_TIMEOUT 且不影响其余条目")

    async def getter(url, timeout, user_agent):
        if "slow" in url:
            raise asyncio.TimeoutError("read timeout")
        await asyncio.sleep(0.005)
        return HTML_OK

    fetcher = ContentFetcher(http_getter=getter, robots=None)
    items = [
        FetchItem(url="https://a.com/ok/1"),
        FetchItem(url="https://a.com/slow/2"),
        FetchItem(url="https://a.com/ok/3"),
    ]
    results = asyncio.run(fetcher.fetch_many(items, concurrency=4))
    by_url = {r.url: r for r in results}

    check("结果条数不变", len(results) == 3, len(results))
    check("超时条 failed", by_url["https://a.com/slow/2"].status == "failed",
          by_url["https://a.com/slow/2"].status)
    check("超时条 error_code=FETCH_TIMEOUT",
          by_url["https://a.com/slow/2"].error_code == cf.FETCH_TIMEOUT,
          by_url["https://a.com/slow/2"].error_code)
    check("超时条 retryable=True", by_url["https://a.com/slow/2"].retryable is True)
    check("其余条不受影响（仍 success）",
          by_url["https://a.com/ok/1"].status == "success"
          and by_url["https://a.com/ok/3"].status == "success",
          [by_url["https://a.com/ok/1"].status, by_url["https://a.com/ok/3"].status])


def test_extract_empty_and_invalid_url():
    print("\n[6] 抽取为空 / 非法 URL")

    async def getter(url, timeout, user_agent):
        return HTML_EMPTY_EXTRACT

    fetcher = ContentFetcher(http_getter=getter, robots=None)
    r = asyncio.run(fetcher.fetch_one(FetchItem(url="https://a.com/only-script")))
    check("抽取为空 -> failed", r.status == "failed", r.status)
    check("抽取为空 -> EXTRACT_EMPTY", r.error_code == cf.EXTRACT_EMPTY, r.error_code)

    bad = asyncio.run(fetcher.fetch_one(FetchItem(url="not-a-url")))
    check("非法 URL -> INVALID_URL", bad.error_code == cf.INVALID_URL, bad.error_code)

    # to_dict 可序列化且含关键字段
    d = r.to_dict()
    check("to_dict 含 status/error_code/content_length",
          {"status", "error_code", "content_length", "url"} <= set(d.keys()), sorted(d.keys()))


def test_content_selector_used():
    print("\n[7] 站点 content_selector 被优先采用")
    sites_config = {"sites": {"demo": {
        "domains": ["demo.com"],
        "content_selector": "div.article-content",
    }}}

    async def getter(url, timeout, user_agent):
        return ("<html><body><div class='other'>忽略</div>"
                "<div class='article-content'><p>选中正文</p></div></body></html>")

    fetcher = ContentFetcher(http_getter=getter, robots=None, sites_config=sites_config)
    r = asyncio.run(fetcher.fetch_one(FetchItem(url="https://demo.com/x")))
    check("命中站点选择器 -> site_selector", r.extractor == "site_selector", r.extractor)
    check("含选中正文", "选中正文" in (r.content or ""), r.content)
    check("不含被排除内容", "忽略" not in (r.content or ""), r.content)


def test_batch_update_records():
    print("\n[8] batch_update_records 对象数组 + 分片 + data.updated")

    class FakeFeishu(FeishuService):
        def __init__(self):
            pass

        async def get_tenant_access_token(self):
            return "fake-token"

    svc = FakeFeishu()
    posted = []
    shapes = []
    urls = []

    class FakeResp:
        def __init__(self, n):
            self._n = n

        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0, "data": {"records": [{"record_id": "rec%d" % i} for i in range(self._n)]}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None, timeout=None):
            recs = json["records"]
            posted.append(len(recs))
            shapes.append(sorted({type(x).__name__ for x in recs}))
            urls.append(url)
            return FakeResp(len(recs))

    original = svc_mod.httpx.AsyncClient
    svc_mod.httpx.AsyncClient = FakeClient
    try:
        records = [{"record_id": "rec%04d" % i, "fields": {"content": "x"}} for i in range(1200)]
        result = asyncio.run(svc.batch_update_records("appTok", "tblId", records))
    finally:
        svc_mod.httpx.AsyncClient = original

    check("分片 500/500/200（取自 limits.BATCH_WRITE_LIMIT）",
          posted == [500, 500, 200] and BATCH == 500, posted)
    check("请求体 records 为对象数组（含 record_id）",
          all(shape == ["dict"] for shape in shapes), shapes)
    check("URL 指向 batch_update 端点",
          all(u.endswith("/records/batch_update") for u in urls), urls)
    check("整体成功 code=0", result.get("code") == 0, result.get("code"))
    check("返回 data.updated=1200", result["data"]["updated"] == 1200, result["data"]["updated"])

    # 缺少 record_id 的记录被丢弃
    svc2 = FakeFeishu()
    svc_mod.httpx.AsyncClient = FakeClient
    try:
        posted.clear()
        result2 = asyncio.run(svc2.batch_update_records("t", "id", [{"fields": {"a": 1}}]))
    finally:
        svc_mod.httpx.AsyncClient = original
    check("无 record_id 记录被丢弃 -> updated=0",
          result2["data"]["updated"] == 0 and posted == [], (result2, posted))


def main():
    print("=" * 70)
    print("正文抓取编排回归测试")
    print("=" * 70)
    test_should_write_back()
    test_infer_site_code()
    test_concurrency_cap()
    test_robots_disallowed()
    test_timeout_isolated()
    test_extract_empty_and_invalid_url()
    test_content_selector_used()
    test_batch_update_records()

    print("\n" + "=" * 70)
    print("PASSED: %d    FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("-" * 70)
        for f in FAILED:
            print("  FAILED -> %s" % f)
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
