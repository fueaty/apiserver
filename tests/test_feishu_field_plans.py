#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书表格字段规划回归测试（缺陷 8）

根因回顾
--------
`ensure_table_fields()` 的执行逻辑是：
    fields_to_delete = 线上字段 - required_fields
也就是说 **凡是不在 required_fields 里的线上列都会被删除（连带数据）**。

而 field_rules.py 早期用
    {f for f in REQUIRED_FIELDS if f in [...]}
来声明每张表的字段。未在 BASE_FIELD_DEFINITIONS 中定义的名字会被静默过滤，
于是 content_selection 声明了 11 个字段、实际只解析出 id/title/rank/status，
另外 7 个（source/platform/hot_level/suitability_score/content_angle/
recommended_strategy/reason）既不会创建，一旦线上存在还会被删掉。
而 `init_all_feishu_tables.py` 会遍历所有表调用 ensure_table_fields，
所以这不是理论风险，是一条可被触发的破坏路径。

本测试锁定三件事：
  1. _resolve_fields 对未定义字段名必须 import 期报错（守卫）
  2. TABLE_PLANS 的字段集必须与「写入方实际写的字段」完全一致（防漂移）
  3. 其余 7 张表的字段集冻结不变，避免修复过程误改线上结构

不联网、不安装第三方依赖，直接运行：

    python tests/test_feishu_field_plans.py
"""

import os
import ast
import sys
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

spec = importlib.util.spec_from_file_location(
    "field_rules", os.path.join(ROOT, "app", "services", "feishu", "field_rules.py")
)
fr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr)

PASSED = 0
FAILED = []


def check(cond, label, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print("  [PASS] %s" % label)
    else:
        FAILED.append(label + (" :: " + detail if detail else ""))
        print("  [FAIL] %s %s" % (label, (":: " + detail) if detail else ""))


def collect_inner_dict_keys(path, var_name="feishu_record"):
    """解析源码，取出所有 `var_name = {"fields": {...}}` 的 fields 键集合。

    返回 list[set[str]]，因为同一个文件里可能有多个同名赋值（不同表）。
    """
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == var_name for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and k.value == "fields" and isinstance(v, ast.Dict):
                keys = {kk.value for kk in v.keys if isinstance(kk, ast.Constant)}
                if keys:
                    results.append(keys)
    return results


print("=" * 78)
print("飞书表格字段规划回归测试（缺陷 8）")
print("=" * 78)

# ---------------------------------------------------------------------------
print("\n[1] 守卫：显式名单引用未定义字段必须报错")
for bad, label in (
    (["id", "definitely_not_a_field"], "单个未定义字段"),
    (["nope_a", "nope_b"], "多个未定义字段"),
    (["id", "title", "nope_c"], "已定义与未定义混合"),
):
    try:
        fr._resolve_fields(explicit=bad)
        check(False, "守卫应拦截: %s" % label)
    except ValueError as exc:
        check("未定义的字段" in str(exc), "守卫拦截: %s" % label, str(exc)[:80])

# 合法名单必须放行
ok = fr._resolve_fields(explicit=["id", "title"])
check(ok == {"id", "title"}, "合法显式名单正常解析", str(sorted(ok)))

# ---------------------------------------------------------------------------
print("\n[2] content_selection：字段集必须与写入方完全一致（缺陷 8 本体）")
plan_cs = set(fr.TABLE_PLANS["content_selection"]["fields"])
writer_sets = collect_inner_dict_keys("app/api/v1/endpoints/enhanced_collection.py")
check(
    plan_cs in writer_sets,
    "content_selection 字段集与写入方 feishu_record 完全一致",
    "plan=%s\n     writers=%s" % (sorted(plan_cs), [sorted(s) for s in writer_sets]),
)
check(
    len(plan_cs) == 11,
    "content_selection 解析出 11 个字段（修复前只有 4 个）",
    "got=%d" % len(plan_cs),
)
for f in ("source", "platform", "hot_level", "suitability_score",
          "content_angle", "recommended_strategy", "reason"):
    check(f in plan_cs, "content_selection 含历史丢失字段: %s" % f)

# ---------------------------------------------------------------------------
print("\n[3] headlines：字段集必须与写入方完全一致")
plan_hl = set(fr.TABLE_PLANS["headlines"]["fields"])
check(
    plan_hl in writer_sets,
    "headlines 字段集与写入方 feishu_record 完全一致",
    "plan=%s" % sorted(plan_hl),
)

# ---------------------------------------------------------------------------
print("\n[4] 其余表字段集冻结（修复不得误改线上结构）")
# NOTE: headlines 11→12、publish_tasks 13→14 是本轮增量需求①的**有意字段扩展**
#       （补入 published_at / error_message），非误改。改动须与 field_rules.py
#       的 TABLE_PLANS 显式名单、以及写入方（enhanced_collection / manager）同步。
FROZEN = {
    "headlines": 12,
    "ai_insights": 14,
    "distribution": 9,
    "platform_configs": 18,
    "data_sources": 16,
    "publish_tasks": 14,
    "content_evaluation": 17,
    "content_selection": 11,
}
for table, expect_count in FROZEN.items():
    plan = fr.TABLE_PLANS.get(table)
    check(plan is not None, "TABLE_PLANS 含表: %s" % table)
    if plan is None:
        continue
    got = len(plan["fields"])
    check(got == expect_count, "%s 字段数 = %d" % (table, expect_count), "got=%d" % got)

# 所有 plan 字段必须都有定义（与守卫一致的最终一致性检查）
for table, plan in fr.TABLE_PLANS.items():
    undef = sorted(f for f in plan["fields"] if f not in fr.BASE_FIELD_DEFINITIONS)
    check(not undef, "%s 所有字段均已定义" % table, str(undef))

# ---------------------------------------------------------------------------
print("\n[5] 写入方 → 表规划 的覆盖度体检（已知缺口只报告、不判失败）")
GAPS = []

# 5a. publish_tasks：manager.py 写的字段是否都在规划内
plan_pt = set(fr.TABLE_PLANS["publish_tasks"]["fields"])
manager_sets = collect_inner_dict_keys("app/services/publication/manager.py", var_name="feishu_record")
for s in manager_sets:
    miss = s - plan_pt
    if miss:
        GAPS.append(("publish_tasks", "app/services/publication/manager.py", sorted(miss)))

# 5b. headlines：各采集站点 emit 的字段是否都在规划内
site_dir = os.path.join(ROOT, "app", "services", "collection", "sites")
site_gaps = set()
if os.path.isdir(site_dir):
    for fn in sorted(os.listdir(site_dir)):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        src = open(os.path.join(site_dir, fn), encoding="utf-8").read()
        tree = ast.parse(src)
        # 采集器把结果 dict 直接 append 到 results / params，键名即 feishu 字段
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = {k.value for k in node.keys if isinstance(k, ast.Constant)
                        and isinstance(k.value, str)}
                if {"collected_at", "site_code"} <= keys:
                    site_gaps |= (keys - plan_hl)
if site_gaps:
    GAPS.append(("headlines", "app/services/collection/sites/*.py", sorted(site_gaps)))

if GAPS:
    print("  ⚠ 检出「写入方有、表规划无」的字段（当前不会写入线上，需人工决策）：")
    for table, where, fields in GAPS:
        print("     - %-16s %s -> %s" % (table, where, fields))
else:
    print("  未检出覆盖缺口")

# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("PASSED: %d    FAILED: %d" % (PASSED, len(FAILED)))
if FAILED:
    print("-" * 78)
    for f in FAILED:
        print("  FAILED -> %s" % f)
print("=" * 78)
sys.exit(1 if FAILED else 0)
