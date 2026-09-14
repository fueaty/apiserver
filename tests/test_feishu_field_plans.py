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
  2. TABLE_PLANS 的字段集必须与「写入方实际写的字段」完全一致（防漂移）：
       · **文本锁**：显式声明的写入方源文件集合里的 `feishu_record = {"fields": {...}}`
         字面量键集；
       · **行为锁**：直接调用 `write_set.build_headline_records()`，用合成输入跑出
         **真实写入记录**，断言 `set(rec["fields"]) == 表规划`。文本锁对「检查了却
         不生效 / 运行期改键」完全无感，行为锁才看得见（有自证，见 [3b]）。
  3. 其余 7 张表的字段集冻结不变，避免修复过程误改线上结构

写入方扫描目标为何要「显式声明」
--------------------------------
历史上这把锁只扫 `app/api/v1/endpoints/enhanced_collection.py` 一个文件；增量 1 的
重构把 headlines 的 12 键字面量从该文件**搬到了** `app/services/collection/write_set.py`
（变量名仍是 feishu_record）⇒ 扫描器扫成空集、锁静默失效（绿而盲）。
故改为对**显式声明的写入方源文件清单**累积，并**断言每个声明目标存在**：以后再搬
文件会当场响，而不是静默扫空。

环境与卫生
----------
  · 不联网、不安装第三方依赖。`write_set` 的依赖链（write_set → mock_utils /
    id_generator）实测仅用标准库；[0] 段断言整套件未引入 aiohttp/pydantic/fastapi 等。
  · 鉴别力自证（[3b]）把变异后的源码写进 `tempfile.mkdtemp()` 临时文件、按文件加载，
    **不改动主树任何文件**，且 `finally` 清理；不创建 git worktree、不调用 git。

直接运行：

    python tests/test_feishu_field_plans.py
"""

import os
import ast
import sys
import shutil
import tempfile
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 让 `import app...`（行为锁的真实调用链）可用；不引入任何第三方依赖。
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 依赖卫生：行为锁要用真实模块链，但必须保证**零第三方依赖**可跑。
# 在 import write_set 前后快照 sys.modules，断言没有拉进任何重依赖。
_HEAVY_DEPS = ("aiohttp", "pydantic", "pydantic_settings", "fastapi",
               "requests", "bs4", "sklearn", "numpy", "lxml", "playwright")
_mods_before = set(sys.modules)
_ws_err = None
try:
    import app.services.collection.write_set as ws  # noqa: E402
except Exception as exc:  # 防御：即便某种环境导不进来，也要给出可行动的失败而非崩溃
    ws = None
    _ws_err = "%s: %s" % (type(exc).__name__, exc)
_new_heavy = sorted({m.split(".")[0] for m in set(sys.modules) - _mods_before}
                    & set(_HEAVY_DEPS))

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


def _keys_from_source(src, var_name="feishu_record"):
    """从**源码字符串**里取出所有 `var_name = {"fields": {...}}` 的 fields 键集合。

    返回 list[set[str]]，因为同一个文件里可能有多个同名赋值（不同表）。
    """
    tree = ast.parse(src)
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


def collect_inner_dict_keys(path, var_name="feishu_record"):
    """按**仓库相对路径**读文件后取键集（文本锁的读取入口）。"""
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return _keys_from_source(f.read(), var_name)


# --- 行为锁：用合成输入跑真实 build_headline_records，拿**写入记录**的 fields 键集 ---
_SYNTHETIC_RESULTS = [{
    "site_code": "weibo",
    "collect_time": "2024-01-01T00:00:00",
    "data_count": 1,
    "news": [{
        "fields": {
            "title": "合成标题",
            "url": "https://example.invalid/x",
            "content": "合成正文",
            "hot": "3万",
            "rank": 1,
            "platform": "weibo",
            "published_at": "2024-01-01",
        }
    }],
}]


def behaviour_keys(ws_module, category="hot"):
    """对给定 write_set 模块用合成输入跑一次，返回写入记录 fields 的键集合（失败→None）。"""
    if ws_module is None or not hasattr(ws_module, "build_headline_records"):
        return None
    _opt, recs, _skipped = ws_module.build_headline_records(_SYNTHETIC_RESULTS, category=category)
    if not recs or not isinstance(recs[0], dict) or "fields" not in recs[0]:
        return None
    return set(recs[0]["fields"].keys())


# --- 变异副本加载（自证用；不改主树）-----------------------------------------
_TMP_DIRS = []

# 运行期改键：文本看不见（字面量仍是 12 键），行为看得见。
# 幂等设计：若源码**已是**变异体则原样返回（这样「整套件跑在被变异的主树副本上」也能
# 正常自证，而不会因为锚点消失而崩）。锚点漂移（既非原形也非变异体）才报错。
_RUNTIME_APPEND = "            feishu_records.append(feishu_record)"
_RUNTIME_MARKER = 'feishu_record["fields"]["extra_key"] = "x"'


def _mutate_runtime_key(src):
    if _RUNTIME_MARKER in src:
        return src
    if _RUNTIME_APPEND not in src:
        raise AssertionError("运行期改键锚点漂移（write_set.py 结构已变）")
    return src.replace(_RUNTIME_APPEND,
                       "            " + _RUNTIME_MARKER + "\n" + _RUNTIME_APPEND, 1)


def _mutate_rename_key(src):
    if '"authorX": "",' in src:
        return src
    if '"author": "",' not in src:
        raise AssertionError("改名键锚点漂移（write_set.py 结构已变）")
    return src.replace('"author": "",', '"authorX": "",', 1)


def _load_mutant(mutate):
    """把（可能变异后的）write_set.py 源码写进临时文件并按文件加载，返回 (module, src)。

    变异函数幂等：源码已是变异体时 new==src，仍照常加载（自证断言的是**效果**，不是「变了没变」）。
    """
    path = os.path.join(ROOT, "app", "services", "collection", "write_set.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    new = mutate(src)
    tmpdir = tempfile.mkdtemp(prefix="_feishu_fp_mutant_")
    _TMP_DIRS.append(tmpdir)
    tmp = os.path.join(tmpdir, "_mutant_write_set.py")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    spec_m = importlib.util.spec_from_file_location("_feishu_fp_mutant_ws", tmp)
    mod = importlib.util.module_from_spec(spec_m)
    spec_m.loader.exec_module(mod)
    return mod, new


print("=" * 78)
print("飞书表格字段规划回归测试（缺陷 8）")
print("=" * 78)

try:
    # -----------------------------------------------------------------------
    print("\n[0] 依赖卫生：行为锁不得引入第三方依赖")
    check(not _new_heavy,
          "导入 write_set 未引入重依赖（零第三方依赖）",
          "new_heavy=%s" % _new_heavy)
    check(ws is not None,
          "可导入 write_set.build_headline_records（行为锁前置）",
          _ws_err or "")

    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # 写入方扫描目标：**显式声明**（增量 1 把 headlines 字面量搬到 write_set.py，
    # 单文件扫描会静默扫空 —— 故此处必须显式列出，并逐个断言存在）。
    WRITER_SOURCES = [
        "app/api/v1/endpoints/enhanced_collection.py",   # content_selection 写入方
        "app/services/collection/write_set.py",          # headlines 写入方（增量 1 迁移后续）
    ]
    print("\n[2] 写入方扫描目标显式化 + 存在性断言")
    for src_path in WRITER_SOURCES:
        exists = os.path.isfile(os.path.join(ROOT, src_path))
        check(exists, "声明扫描目标存在: %s" % src_path,
              "缺失 ⇒ 扫描会静默扫空（锁失效）" if not exists else "")
    writer_sets = []
    for src_path in WRITER_SOURCES:
        writer_sets += collect_inner_dict_keys(src_path)
    check(bool(writer_sets),
          "扫描目标累积出至少一个 feishu_record 字面量（非空集）",
          "writer_sets=%s" % [sorted(s) for s in writer_sets])

    # -----------------------------------------------------------------------
    print("\n[3] content_selection：字段集必须与写入方完全一致（缺陷 8 本体）")
    plan_cs = set(fr.TABLE_PLANS["content_selection"]["fields"])
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

    # -----------------------------------------------------------------------
    print("\n[4] headlines：字段集必须与写入方完全一致（文本锁 + 行为锁）")
    plan_hl = set(fr.TABLE_PLANS["headlines"]["fields"])
    # 4a. 文本锁
    check(
        plan_hl in writer_sets,
        "headlines 字段集与写入方 feishu_record 完全一致（文本锁）",
        "plan=%s\n     writers=%s" % (sorted(plan_hl), [sorted(s) for s in writer_sets]),
    )
    # 4b. 行为锁（真守卫）：跑真实写入集构造，断言键集 == 表规划
    beh = behaviour_keys(ws)
    check(
        beh == plan_hl,
        "headlines 写入记录 fields 键集 == 表规划（行为锁，12 键）",
        "behaviour=%s\n     plan=%s" % (sorted(beh) if beh else None, sorted(plan_hl)),
    )

    # -----------------------------------------------------------------------
    print("\n[5] 鉴别力自证（变异副本；不改主树）")
    # 变异 A：在字面量**之后**加一行运行期改键 ⇒ 文本锁仍绿、行为锁变红（文本锁盲区）
    mod_a, src_a = _load_mutant(_mutate_runtime_key)
    text_a = _keys_from_source(src_a)
    check(plan_hl in text_a,
          "自证A：运行期改键后【文本锁仍绿】（字面量仍 12 键）",
          "sets=%s" % [sorted(s) for s in text_a])
    check(behaviour_keys(mod_a) != plan_hl,
          "自证A：运行期改键后【行为锁变红】（13 键 ≠ 12 键）",
          "behaviour=%s" % (sorted(behaviour_keys(mod_a) or [])))
    # 变异 B：把字面量里 "author" 改名 ⇒ 文本锁与行为锁**都红**
    mod_b, src_b = _load_mutant(_mutate_rename_key)
    text_b = _keys_from_source(src_b)
    check(plan_hl not in text_b,
          "自证B：字面量改名后【文本锁变红】",
          "sets=%s" % [sorted(s) for s in text_b])
    check(behaviour_keys(mod_b) != plan_hl,
          "自证B：字面量改名后【行为锁变红】",
          "behaviour=%s" % (sorted(behaviour_keys(mod_b) or [])))

    # -----------------------------------------------------------------------
    print("\n[6] 其余表字段集冻结（修复不得误改线上结构）")
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

    # -----------------------------------------------------------------------
    print("\n[7] 写入方 → 表规划 的覆盖度体检（已知缺口只报告、不判失败）")
    GAPS = []

    # 7a. publish_tasks：manager.py 写的字段是否都在规划内
    plan_pt = set(fr.TABLE_PLANS["publish_tasks"]["fields"])
    manager_sets = collect_inner_dict_keys("app/services/publication/manager.py", var_name="feishu_record")
    for s in manager_sets:
        miss = s - plan_pt
        if miss:
            GAPS.append(("publish_tasks", "app/services/publication/manager.py", sorted(miss)))

    # 7b. headlines：各采集站点 emit 的字段是否都在规划内
    site_dir = os.path.join(ROOT, "app", "services", "collection", "sites")
    site_gaps = set()
    if os.path.isdir(site_dir):
        for fn in sorted(os.listdir(site_dir)):
            if not fn.endswith(".py") or fn == "__init__.py":
                continue
            with open(os.path.join(site_dir, fn), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
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

finally:
    # 卫生：清理所有变异临时目录（无论成败）
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)

# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("PASSED: %d    FAILED: %d" % (PASSED, len(FAILED)))
if FAILED:
    print("-" * 78)
    for f in FAILED:
        print("  FAILED -> %s" % f)
print("=" * 78)
sys.exit(1 if FAILED else 0)
