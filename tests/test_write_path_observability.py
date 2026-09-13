#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
写路径可观测性 regressions 锁（Task #37 / P2）—— 离线，无外网。

覆盖三件事：
  (1) FeishuService.batch_update_records 归一化里「形状不符 → 静默跳过」的同族残留
      （feishu_service.py）：
        · 全被丢光（传进来的都没 record_id）→ 必须**同时**返回 success(0) 与发出 warning
          （此前完全静默，调用方会误读成"全部更新成功"）；
        · 部分被丢 → 必须发出「规范化丢弃 N/M」warning，且发生在**触网之前**；
        · 全部合法 → 不得发出「丢弃」warning（避免噪音）。
  (2) collection_pipeline.py 的 records_to_delete 去重（接线锁）：
      必须用 `list(dict.fromkeys(records_to_delete))`，且打印「列表长度」与「唯一 id 数」两个数。
      这是 QA 报的「无法闭合 +5 残差」最可能成因。
  (3) script/verify_run.sh（接线锁）：存在 + LF + 固定重定向到 logs/verify_*.log 且回显路径。
      把「运行输出落服务端日志」从操作者纪律变成机器保证。

依赖桩（**条件桩**；判据：桩的合法性 = 被桩模块的行为是否被断言依赖）：
  httpx / lark_oapi / ... 仅 ImportError 时注入；其行为不被断言依赖（本测试只跑
  归一化这段纯逻辑，不联网、不建 client —— 用例 1 在触网前就返回）。

    python tests/test_write_path_observability.py     # 期望 RC=0
"""

import asyncio
import logging
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from app.services.feishu.feishu_service import FeishuService           # noqa: E402
from app.services.feishu import feishu_service as _fsmod               # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------------------
# (1) batch_update_records 归一化可观测性
# ---------------------------------------------------------------------------
def _run_batch_update(records, boom):
    """构造不联网的 FeishuService，跑一次 batch_update_records，返回
    (result, rc, err, messages)。

    boom=True 时 get_tenant_access_token 抛哨兵异常，从而在**触网前**截断，
    使我们能只观察归一化阶段的日志（用例 2/3）。
    """
    svc = object.__new__(FeishuService)  # 绕过 __init__，不读配置、不建 client
    if boom:
        async def _no_net():
            raise RuntimeError("NO_NET_SENTINEL")
        svc.get_tenant_access_token = _no_net

    recs = []

    class _MemHandler(logging.Handler):
        def emit(self, record):
            recs.append(record)

    handler = _MemHandler()
    _fsmod.logger.addHandler(handler)
    result, rc, err = None, 0, None
    try:
        try:
            result = asyncio.run(svc.batch_update_records("app", "tbl", records))
        except RuntimeError as e:
            rc, err = 1, str(e)
    finally:
        _fsmod.logger.removeHandler(handler)
    return result, rc, err, [r.getMessage() for r in recs]


def test_batch_update_observability():
    print("\n[1] batch_update_records：归一化「静默跳过」必须可观测")

    # 用例 1：全被丢光（1 非 dict、1 缺 record_id、1 非 dict）→ 触网前返回
    result, rc, err, msgs = _run_batch_update([1, {"fields": {}}, "x"], boom=False)
    check("①1 全非法：返回 success(0)/updated=0（保持既有返回值不变）",
          result == {"code": 0, "msg": "success", "data": {"records": [], "updated": 0}},
          f"result={result!r} err={err}")
    check("①2 全非法：发出『规范化丢弃』warning（此前完全静默）",
          any("规范化丢弃" in m for m in msgs), f"msgs={msgs}")
    check("①3 全非法：发出『归一化后为空』warning（区分『本就无需更新』）",
          any("归一化后为空" in m for m in msgs), f"msgs={msgs}")

    # 用例 2：部分非法（1 合法 + 1 缺 record_id）→ 触网前已告警
    result, rc, err, msgs = _run_batch_update(
        [{"record_id": "rec1", "fields": {"title": "x"}}, {"fields": {"title": "y"}}],
        boom=True,
    )
    check("②1 部分非法：触网前发出『规范化丢弃 1/2』warning",
          any("规范化丢弃 1/2" in m for m in msgs), f"msgs={msgs}")
    check("②2 部分非法：不发出『归一化后为空』（仍有合法记录）",
          not any("归一化后为空" in m for m in msgs), f"msgs={msgs}")
    check("②3 部分非法：确实在触网处被哨兵截断（证明告警发生在触网之前）",
          rc == 1 and err == "NO_NET_SENTINEL", f"rc={rc} err={err}")

    # 用例 3：全部合法 → 不得有『丢弃』噪音
    result, rc, err, msgs = _run_batch_update(
        [{"record_id": "rec1", "fields": {}}, {"record_id": "rec2", "fields": {}}],
        boom=True,
    )
    check("③1 全合法：不发出任何『丢弃』warning（无噪音）",
          not any("丢弃" in m for m in msgs), f"msgs={msgs}")


# ---------------------------------------------------------------------------
# (2) records_to_delete 去重（源锁）
# ---------------------------------------------------------------------------
def test_records_to_delete_dedup():
    print("\n[2] collection_pipeline.py：records_to_delete 去重（接线锁）")

    with open(os.path.join(ROOT, "script", "collection_pipeline.py"), encoding="utf-8") as f:
        src = f.read()

    check("[2] 去重：使用 list(dict.fromkeys(records_to_delete))",
          "list(dict.fromkeys(records_to_delete))" in src,
          "未去重 → 删除接口会收到重复 id、对账无法闭合")

    check("[2] 去重：同时打印『列表长度』与『唯一 id 数』",
          "delete_len_raw" in src and "去重后唯一" in src,
          "两个数缺一 → 残差无法定位")


# ---------------------------------------------------------------------------
# (3) verify_run.sh 证据脚本（锁）
# ---------------------------------------------------------------------------
def test_verify_run_script():
    print("\n[3] script/verify_run.sh：把『输出落服务端日志』变成机器保证")

    vp = os.path.join(ROOT, "script", "verify_run.sh")
    exists = os.path.isfile(vp)
    check("[3] script/verify_run.sh 存在", exists, vp)
    if not exists:
        return

    raw = open(vp, "rb").read()
    check("[3] verify_run.sh 为 LF（无 CR，生产机要求）",
          raw.count(b"\r") == 0, f"cr={raw.count(bytes([13]))}")

    txt = raw.decode("utf-8")
    check("[3] 固定重定向到 logs/verify_*.log 且合并 stderr(2>&1)",
          "logs/verify_" in txt and "2>&1" in txt,
          "缺少固定重定向 → 仍可能 NO_VERIFY_LOG")

    check("[3] 固定解释器与 PYTHONPATH 及流水线入口",
          "PYTHONPATH=" in txt and "/usr/bin/python3" in txt
          and "script/collection_pipeline.py" in txt,
          "未固定解释器/入口 → 双解释器歧义")

    check("[3] 回显日志路径（VERIFY_LOG=）供验证者读取",
          "VERIFY_LOG=" in txt, "未回显日志路径")


def main():
    print("=" * 70)
    print("写路径可观测性锁（离线）：batch_update 归一化 / 去重 / verify_run.sh")
    print("=" * 70)

    test_batch_update_observability()
    test_records_to_delete_dedup()
    test_verify_run_script()

    print("=" * 70)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
