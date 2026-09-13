#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书表格容量管理回归测试

覆盖生产事故根因（RecordExceedLimit / 1254103）：
  - cleanup_table 是否按「时间 + 容量」两段式正确决策
  - 今日数据保护与回退删除
  - dry_run 不下发删除
  - batch_add_records 是否按 500 分片
  - 命中 1254103 时是否能「紧急清理 -> 重试剩余」自愈

本脚本自带第三方依赖桩（httpx / lark_oapi / app.core.config），
不联网、不需要安装项目依赖，直接运行即可：

    python tests/test_feishu_capacity.py
"""

import sys
import os
import types
import asyncio
import importlib.util
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(ROOT, "app", "services", "feishu")

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

# app 包骨架（避免执行 app/__init__.py 里可能存在的重量级导入）
for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.feishu", PKG_DIR),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

config_stub = types.ModuleType("app.core.config")
config_stub.config_manager = types.SimpleNamespace(get_credentials=lambda: {})
sys.modules["app.core.config"] = config_stub


def _load(module_name, filename):
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(PKG_DIR, filename)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


limits = _load("app.services.feishu.limits", "limits.py")
_load("app.services.feishu.field_rules", "field_rules.py")
svc_mod = _load("app.services.feishu.feishu_service", "feishu_service.py")

FeishuService = svc_mod.FeishuService
parse_record_time = svc_mod.parse_record_time

WATERMARK = limits.WATERMARK
LIMIT = limits.TABLE_RECORD_LIMIT
BATCH = limits.BATCH_WRITE_LIMIT


# ---------------------------------------------------------------------------
# 2. 测试替身
# ---------------------------------------------------------------------------
class FakeFeishu(FeishuService):
    """绕过 __init__（不连飞书），只保留被测逻辑。"""

    def __init__(self, rows, delete_ok=True):
        self.rows = rows                # [(record_id, collected_at)]
        self.delete_ok = delete_ok
        self.deleted_batches = []       # 记录每次实际下发的删除批次
        self.capacity_calls = []

    # 不碰网络
    async def get_tenant_access_token(self):
        return "fake-token"

    async def scan_records(self, app_token, table_id, page_size=None):
        return list(self.rows)

    async def delete_records(self, app_token, table_id, record_ids):
        self.deleted_batches.append(list(record_ids))
        if not self.delete_ok:
            return 0
        ids = set(record_ids)
        self.rows = [r for r in self.rows if r[0] not in ids]
        return len(record_ids)

    async def ensure_capacity(self, app_token, table_id, incoming=0, watermark=WATERMARK):
        self.capacity_calls.append(incoming)
        return {"ok": True, "message": "stub", "count_after": 0, "deleted_total": 0}


def make_rows(n, start_days_ago=400):
    """
    生成 n 条记录，collected_at 从 start_days_ago 天前开始、每条递增 1 分钟，
    全部落在过去且时间互不相同，便于精确断言「删的是最旧的那批」。
    """
    base = datetime.now() - timedelta(days=start_days_ago)
    rows = []
    for i in range(n):
        dt = base + timedelta(minutes=i)
        rows.append((f"rec{i:06d}", dt.strftime("%Y-%m-%d %H:%M:%S")))
    return rows


PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  ✅ {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  ❌ {name}  {detail}")


# ---------------------------------------------------------------------------
# 3. 用例
# ---------------------------------------------------------------------------
def test_parse_record_time():
    print("\n[1] parse_record_time 兼容性")
    now = datetime.now()
    check("标准格式", parse_record_time("2026-09-12 10:00:00") == datetime(2026, 9, 12, 10, 0, 0))
    check("ISO 带时区", parse_record_time("2026-09-12T10:00:00+08:00") == datetime(2026, 9, 12, 10, 0, 0))
    check("ISO 带 Z", parse_record_time("2026-09-12T10:00:00Z") == datetime(2026, 9, 12, 10, 0, 0))
    check("富文本 list", parse_record_time([{"text": "2026-09-12 10:00:00"}]) == datetime(2026, 9, 12, 10, 0, 0))
    check("空字符串 -> None", parse_record_time("") is None)
    check("None -> None", parse_record_time(None) is None)
    check("垃圾字符串 -> None", parse_record_time("not-a-date") is None)
    ms = int(now.timestamp() * 1000)
    got = parse_record_time(ms)
    check("毫秒时间戳", got is not None and abs((got - now).total_seconds()) < 2, f"got={got}")


def test_no_cleanup_when_safe():
    print("\n[2] 水位以下不清理")
    svc = FakeFeishu(make_rows(1000))
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=100))
    check("不删除", stats["deleted_total"] == 0, stats)
    check("ok=True", stats["ok"] is True)
    check("count_after 不变", stats["count_after"] == 1000)
    check("未下发删除批次", svc.deleted_batches == [])


def test_capacity_cleanup():
    print("\n[3] 超水位 -> 按容量清理到水位")
    original = make_rows(19000)
    svc = FakeFeishu(original)
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=0))
    expected_delete = 19000 - WATERMARK          # 2000（WATERMARK=17000）
    check("删除量正确", stats["deleted_total"] == expected_delete,
          f"expect={expected_delete} got={stats['deleted_total']}")
    check("删到水位", stats["count_after"] == WATERMARK, stats["count_after"])
    check("ok=True", stats["ok"] is True)

    # 删除的必须是「最旧的 expected_delete 条」，剩余必须是「最新的 WATERMARK 条」
    ordered = sorted(original, key=lambda r: r[1])
    expected_deleted = {rid for rid, _ in ordered[:expected_delete]}
    expected_remaining = {rid for rid, _ in ordered[expected_delete:]}
    actual_deleted = set(svc.deleted_batches[0]) if svc.deleted_batches else set()
    check("删除集合 = 最旧 expected_delete 条", actual_deleted == expected_deleted,
          f"len={len(actual_deleted)} diff={len(actual_deleted ^ expected_deleted)}")
    check("剩余集合 = 最新 WATERMARK 条",
          {r[0] for r in svc.rows} == expected_remaining,
          f"len={len(svc.rows)}")


def test_capacity_with_incoming():
    print("\n[4] 预留写入空间（incoming 参与水位计算）")
    svc = FakeFeishu(make_rows(19000))
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=2000))
    expect_after = WATERMARK - 2000               # 15000（WATERMARK=17000）
    check("清理后 = 水位 - incoming", stats["count_after"] == expect_after,
          f"expect={expect_after} got={stats['count_after']}")
    check("ok=True", stats["ok"] is True)
    check("含 incoming 后不超限",
          stats["count_after"] + 2000 <= LIMIT)


def test_protect_today_spill():
    print("\n[5] 今日数据保护 + 空间不足时回退删除")
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(f"old{i}", "2020-01-01 00:00:00") for i in range(500)]
    rows += [(f"new{i}", today) for i in range(19500)]
    svc = FakeFeishu(rows)
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=0))

    deleted_ids = set(svc.deleted_batches[0]) if svc.deleted_batches else set()
    old_deleted = sum(1 for i in range(500) if f"old{i}" in deleted_ids)
    new_deleted = sum(1 for i in range(19500) if f"new{i}" in deleted_ids)
    check("先删完所有非今日记录", old_deleted == 500, f"old_deleted={old_deleted}")
    check("回退删除今日记录补齐", new_deleted == 20000 - WATERMARK - 500,
          f"new_deleted={new_deleted}")
    check("最终到达水位", stats["count_after"] == WATERMARK, stats["count_after"])


def test_dry_run():
    print("\n[6] dry_run 只统计不删除")
    svc = FakeFeishu(make_rows(19000))
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=0, dry_run=True))
    check("未下发删除", svc.deleted_batches == [], svc.deleted_batches)
    check("实际删除 0", stats["deleted_total"] == 0)
    check("计划删除量正确", stats["delete_planned"] == 19000 - WATERMARK, stats["delete_planned"])
    check("预计剩余正确", stats["count_after"] == WATERMARK, stats["count_after"])
    check("标记 dry_run", stats["dry_run"] is True)


def test_time_based_cleanup():
    print("\n[7] 按时间清理（--days）")
    old = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
    mid = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    recent = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    rows = [(f"a{i}", old) for i in range(200)] + \
           [(f"b{i}", mid) for i in range(200)] + \
           [(f"c{i}", recent) for i in range(200)]
    svc = FakeFeishu(rows)
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=90, incoming=0))
    check("按时间删除 200 条", stats["deleted_by_age"] == 200, stats)
    check("30 天内的数据未被时间规则删除", stats["deleted_by_capacity"] == 0, stats)
    check("剩 400 条", stats["count_after"] == 400, stats["count_after"])


def test_delete_failure_detection():
    print("\n[8] 删除失败时不虚报容量")
    svc = FakeFeishu(make_rows(19990), delete_ok=False)
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=100))
    check("未虚报删除数", stats["deleted_total"] == 0, stats["deleted_total"])
    check("count_after 反映真实情况", stats["count_after"] == 19990, stats)
    check("20090 超限 -> ok=False", stats["ok"] is False, stats)
    check("message 含人工介入", "人工介入" in stats["message"], stats["message"])


def test_delete_chunking():
    print("\n[9] delete_records 按 500 分片，且请求体为 string[]")
    svc = FakeFeishu(make_rows(1200))
    posted = []          # 每批的记录数
    payload_shapes = []  # 每批 records 里元素的类型

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"code": 0}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            recs = json["records"]
            posted.append(len(recs))
            payload_shapes.append(
                sorted({type(x).__name__ for x in recs})
            )
            return FakeResp()

    original = svc_mod.httpx.AsyncClient
    svc_mod.httpx.AsyncClient = FakeClient
    try:
        # 直接调用真实实现（FakeFeishu 覆盖了 delete_records，这里显式走基类）
        n = asyncio.run(FeishuService.delete_records(
            svc, "t", "id", [f"r{i}" for i in range(1200)]
        ))
    finally:
        svc_mod.httpx.AsyncClient = original

    check("分片大小均为 500", posted == [500, 500, 200], posted)
    check("返回删除总数", n == 1200, n)
    # 关键回归点：官方文档 records 类型是 string[]。
    # 传 [{"record_id": ...}] 对象数组会直接 HTTP 400（生产事故根因）。
    check("请求体 records 为纯字符串数组",
          all(shape == ["str"] for shape in payload_shapes), payload_shapes)


def test_batch_add_chunking():
    print("\n[10] batch_add_records 按 500 分片写入")
    svc = FakeFeishu([])

    async def fake_fields(app_token, table_id):
        return {"title": {"id": "f1", "type": 1, "property": {}}}

    svc.get_table_fields_uncached = fake_fields

    posted = []

    class FakeResp:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            posted.append(len(json["records"]))
            return FakeResp({
                "code": 0,
                "data": {"records": [{"record_id": f"x{i}"} for i in range(len(json["records"]))]},
            })

    original = svc_mod.httpx.AsyncClient
    svc_mod.httpx.AsyncClient = FakeClient
    try:
        records = [{"fields": {"title": f"t{i}"}} for i in range(1200)]
        result = asyncio.run(svc.batch_add_records("t", "id", records))
    finally:
        svc_mod.httpx.AsyncClient = original

    check("分片 500/500/200", posted == [500, 500, 200], posted)
    check("整体成功", result["code"] == 0, result)
    check("返回 1200 条", len(result["data"]["records"]) == 1200,
          len(result["data"]["records"]))


def test_self_heal_on_exceed_limit():
    print("\n[11] 命中 1254103 后自愈：清理 -> 重试剩余")
    svc = FakeFeishu([])

    async def fake_fields(app_token, table_id):
        return {"title": {"id": "f1", "type": 1, "property": {}}}

    svc.get_table_fields_uncached = fake_fields

    calls = {"n": 0}
    posted = []

    class FakeResp:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            calls["n"] += 1
            posted.append(len(json["records"]))
            if calls["n"] == 1:
                # 第一批就撞上限
                return FakeResp({"code": 1254103, "msg": "RecordExceedLimit"})
            return FakeResp({
                "code": 0,
                "data": {"records": [{"record_id": f"y{i}"} for i in range(len(json["records"]))]},
            })

    original = svc_mod.httpx.AsyncClient
    svc_mod.httpx.AsyncClient = FakeClient
    try:
        records = [{"fields": {"title": f"t{i}"}} for i in range(600)]
        result = asyncio.run(svc.batch_add_records("t", "id", records))
    finally:
        svc_mod.httpx.AsyncClient = original

    check("触发了紧急清理", svc.capacity_calls == [600], svc.capacity_calls)
    check("自愈后整体成功", result["code"] == 0, result)
    check("重试覆盖全部 600 条",
          sum(posted[1:]) == 600, f"posted={posted}")


def test_unparsed_timestamps_are_deleted_first():
    print("\n[12] collected_at 无法解析时的降级行为")
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    bad = [(f"bad{i}", "###") for i in range(2000)]
    ok = [(f"ok{i}", today) for i in range(11999)]
    older = [("ok_last", yesterday)]
    rows = bad + ok + older

    svc = FakeFeishu(rows)
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=None, incoming=0))
    check("统计出未解析记录数", stats["unparsed"] == 2000, stats["unparsed"])
    check("计数正确", stats["count_before"] == len(rows), stats["count_before"])
    check("未超水位则不删除", stats["deleted_total"] == 0, stats["deleted_total"])

    # 抬到超水位，验证脏数据被优先丢弃
    extra = [(f"okx{i}", today) for i in range(9000)]
    svc2 = FakeFeishu(rows + extra)
    stats2 = asyncio.run(svc2.cleanup_table("t", "id", keep_days=None, incoming=0))
    deleted = set(svc2.deleted_batches[0]) if svc2.deleted_batches else set()
    bad_deleted = sum(1 for i in range(2000) if f"bad{i}" in deleted)
    check("脏数据被优先删除", bad_deleted == 2000, f"bad_deleted={bad_deleted}")
    expected = len(rows) + len(extra) - WATERMARK
    check("删除总量 = 超出水位部分", stats2["deleted_total"] == expected,
          f"{stats2['deleted_total']} vs {expected}")
    check("最终回到水位", stats2["count_after"] == WATERMARK, stats2["count_after"])


def test_age_cleanup_guard():
    print("\n[13] 时间清理 50% 保护闸（防止 --days 误清空全表）")
    # 场景复现：采集长期失败，表里 14,000 条数据全部早于 90 天前。
    # 若直接执行 --days 90 会删光整张表，保护闸必须拦住。
    old = [(f"r{i:06d}", (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S"))
           for i in range(14000)]

    svc = FakeFeishu(old)
    stats = asyncio.run(svc.cleanup_table("t", "id", keep_days=90, incoming=0))
    check("保护闸生效", stats["age_cleanup_skipped"] is True, stats)
    check("未按时间删除任何记录", stats["deleted_by_age"] == 0, stats["deleted_by_age"])
    check("表未被清空", stats["count_after"] == 14000, stats["count_after"])
    check("未下发删除", svc.deleted_batches == [], svc.deleted_batches)

    # 显式 force（guard_ratio=1.0）才允许执行
    svc2 = FakeFeishu(old)
    stats2 = asyncio.run(svc2.cleanup_table("t", "id", keep_days=90, incoming=0,
                                            guard_ratio=1.0))
    check("force 后跳过保护闸", stats2["age_cleanup_skipped"] is False, stats2)
    check("force 后按时间删光", stats2["deleted_by_age"] == 14000, stats2["deleted_by_age"])
    check("force 后表为空", stats2["count_after"] == 0, stats2["count_after"])

    # 保护闸只拦「大比例」。小比例过期应当正常清理。
    mixed = [(f"old{i}", (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S"))
             for i in range(100)]
    mixed += [(f"new{i}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")) for i in range(900)]
    svc3 = FakeFeishu(mixed)
    stats3 = asyncio.run(svc3.cleanup_table("t", "id", keep_days=90, incoming=0))
    check("小比例过期不受保护闸影响", stats3["deleted_by_age"] == 100, stats3["deleted_by_age"])
    check("小比例场景未触发跳过", stats3["age_cleanup_skipped"] is False, stats3)


def main():
    print("=" * 66)
    print("飞书表格容量管理回归测试")
    print(f"上限={LIMIT} 水位={WATERMARK} 分片={BATCH}")
    print("=" * 66)

    test_parse_record_time()
    test_no_cleanup_when_safe()
    test_capacity_cleanup()
    test_capacity_with_incoming()
    test_protect_today_spill()
    test_dry_run()
    test_time_based_cleanup()
    test_delete_failure_detection()
    test_delete_chunking()
    test_batch_add_chunking()
    test_self_heal_on_exceed_limit()
    test_unparsed_timestamps_are_deleted_first()
    test_age_cleanup_guard()

    print("\n" + "=" * 66)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    if FAILED:
        for f in FAILED:
            print(f"  ❌ {f}")
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
