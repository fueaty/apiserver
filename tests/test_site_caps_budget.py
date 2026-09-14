#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
站点单轮上限名录 + 容量守卫回归测试（app/services/collection/site_caps.py）

对应设计 `.workbuddy/_next/站点上限守卫设计.md` §3.3 的 M1–M7。
全部为**离线、无网络**断言（仅标准库 + 站点源码文本/AST 扫描；读 sites.yaml 优先用
yaml、缺库时回退到最小解析，见 `load_enabled_sites`）。

本文件有两层，别混淆：
  · 守卫（生产）：`site_caps.py` import 期 G1/G2 —— 由 M1/M2 用**独立子进程**证明会 raise。
  · 锁（测试）：名录闭包 + sites.yaml 交叉 + **「使用点」接线锁**（M5）。
    M5 是本项目第四次尝试「接线锁」——前三次都栽在「只查形状/文本」。
    故 M5 既查**赋值形状**，又查**切片使用点个数**与**旧裸字面量缺失**，
    并用 **14 个位置的变异自证**证明「把任一处还原成裸字面量 → 锁必变红」。

环境变量（内部用，防递归）：
  SITE_CAPS_LOCK_ONLY=1  只跑「锁」（registry + M5 使用点），供变异自证子进程使用
  SITE_CAPS_LOCK_CHILD=1 标记子进程（跳过变异自证自身，防递归）

退出码：0 = 全部通过；1 = 有失败。

    python tests/test_site_caps_budget.py
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SITE_CAPS_PATH = os.path.join(ROOT, "app", "services", "collection", "site_caps.py")
SITES_DIR = os.path.join(ROOT, "app", "services", "collection", "sites")
RUN_DAILY_SH = os.path.join(ROOT, "script", "run_daily_task.sh")
SITES_YAML = os.path.join(ROOT, "config", "sites.yaml")

LOCK_ONLY = os.environ.get("SITE_CAPS_LOCK_ONLY") == "1"
IS_CHILD = os.environ.get("SITE_CAPS_LOCK_CHILD") == "1"

# 站点 → (站点模块相对路径, 该站"命名上界常量"名 or None)
SITE_FILES = {
    "people_daily": ("app/services/collection/sites/people_daily.py", "_MAX"),
    "xinhua": ("app/services/collection/sites/xinhua.py", "_MAX"),
    "cctv": ("app/services/collection/sites/cctv.py", "_MAX"),
    "thepaper": ("app/services/collection/sites/thepaper.py", "MAX_RESULTS"),
    "weibo": ("app/services/collection/sites/weibo.py", "_MAX"),
    "baidu": ("app/services/collection/sites/baidu.py", "_MAX"),
    "zhihu": ("app/services/collection/sites/zhihu.py", None),
    "tech_36kr": ("app/services/collection/sites/tech_36kr.py", "_MAX"),
    "xiaohongshu": ("app/services/collection/sites/xiaohongshu.py", "_MAX"),
}

EXPECTED_CAPS = {
    "people_daily": 50, "xinhua": 30, "cctv": 50, "thepaper": 100,
    "weibo": 50, "baidu": 50, "zhihu": 50, "tech_36kr": 50, "xiaohongshu": 30,
}

# —— M5(a) 计数锁：每文件「哨兵切片」个数（AST 数 Subscript(Slice(lower=None, upper=Name(哨兵)))）——
SENTINEL_SLICE_COUNT = {
    "app/services/collection/sites/baidu.py": 2,
    "app/services/collection/sites/cctv.py": 1,
    "app/services/collection/sites/people_daily.py": 1,
    "app/services/collection/sites/tech_36kr.py": 1,
    "app/services/collection/sites/thepaper.py": 2,
    "app/services/collection/sites/weibo.py": 3,
    "app/services/collection/sites/xiaohongshu.py": 2,
    "app/services/collection/sites/xinhua.py": 1,
}
SENTINEL_NAMES = {"_MAX", "MAX_RESULTS"}

# —— M5(b) 负面锁：每个旧裸字面量形态在该文件中必须出现 0 次 ——
NEGATIVE_LITERALS = {
    "app/services/collection/sites/baidu.py": ["matches[:50]", "category-wrap_iQLoo')[:50]"],
    "app/services/collection/sites/cctv.py": ["unique_data[:50]"],
    "app/services/collection/sites/people_daily.py": ["find_all('item')[:50]"],
    "app/services/collection/sites/tech_36kr.py": ["find_all('item')[:50]"],
    "app/services/collection/sites/thepaper.py": ["results[:100]"],
    "app/services/collection/sites/weibo.py": ["results[:50]", "unique_data[:50]"],
    "app/services/collection/sites/xiaohongshu.py": ["unique_data[:30]"],
    "app/services/collection/sites/xinhua.py": ["unique_data[:30]"],
    "app/services/collection/sites/zhihu.py": ["result_limit', 50"],
}

# —— M5(c) 变异自证：14 个位置（含同形重复的第 index 次出现）——
# (相对路径, 当前哨兵片段, 旧裸字面量片段, 第几次出现(0-based), 人类可读标签)
POSITIONS = [
    ("app/services/collection/sites/baidu.py", "matches[:_MAX]", "matches[:50]", 0,
     "baidu matches[:_MAX]"),
    ("app/services/collection/sites/baidu.py", "category-wrap_iQLoo')[:_MAX]",
     "category-wrap_iQLoo')[:50]", 0, "baidu find_all('div',...)[:_MAX]"),
    ("app/services/collection/sites/cctv.py", "unique_data[:_MAX]", "unique_data[:50]", 0,
     "cctv unique_data[:_MAX]"),
    ("app/services/collection/sites/people_daily.py", "find_all('item')[:_MAX]",
     "find_all('item')[:50]", 0, "people_daily find_all('item')[:_MAX]"),
    ("app/services/collection/sites/tech_36kr.py", "find_all('item')[:_MAX]",
     "find_all('item')[:50]", 0, "tech_36kr find_all('item')[:_MAX]"),
    ("app/services/collection/sites/thepaper.py", "results[:MAX_RESULTS]",
     "results[:100]", 0, "thepaper results[:MAX_RESULTS] (#1 try 内)"),
    ("app/services/collection/sites/thepaper.py", "results[:MAX_RESULTS]",
     "results[:100]", 1, "thepaper results[:MAX_RESULTS] (#2 return 前)"),
    ("app/services/collection/sites/weibo.py", "results = results[:_MAX]",
     "results = results[:50]", 0, "weibo results[:_MAX] (#1 浏览器路径)"),
    ("app/services/collection/sites/weibo.py", "results = results[:_MAX]",
     "results = results[:50]", 1, "weibo results[:_MAX] (#2 API 路径)"),
    ("app/services/collection/sites/weibo.py", "return unique_data[:_MAX]",
     "return unique_data[:50]", 0, "weibo unique_data[:_MAX]"),
    ("app/services/collection/sites/xiaohongshu.py", "hot_data = unique_data[:_MAX]",
     "hot_data = unique_data[:30]", 0, "xiaohongshu unique_data[:_MAX] (#1 JSON)"),
    ("app/services/collection/sites/xiaohongshu.py", "hot_data = unique_data[:_MAX]",
     "hot_data = unique_data[:30]", 1, "xiaohongshu unique_data[:_MAX] (#2 BS)"),
    ("app/services/collection/sites/xinhua.py", "hot_data = unique_data[:_MAX]",
     "hot_data = unique_data[:30]", 0, "xinhua unique_data[:_MAX]"),
    ("app/services/collection/sites/zhihu.py",
     'get(\'result_limit\', SITE_ROUND_CAPS["zhihu"])', 'get(\'result_limit\', 50)', 0,
     "zhihu result_limit 默认值"),
]

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [OK] %s" % name)
    else:
        FAILED.append("%s :: %s" % (name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def code_only(text):
    """只保留会真正执行的代码行（去掉空行与整行注释）。

    负面锁只关心「**代码**是否回退成裸字面量」；注释里为了说明历史/陷阱而
    提到旧字面量（例如「原 `unique_data[:50]`」）是合理的，不应被误伤
    ——与 tests/test_capacity_budget.py 的 `_code_lines` 同款取舍。
    """
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(ln)
    return "\n".join(out)


def load_real_site_caps():
    from app.services.collection import site_caps
    return site_caps


# ---------------------------------------------------------------------------
# 临时「最小树」：供子进程 `import site_caps` / 跑锁 / `import thepaper` 用
# ---------------------------------------------------------------------------
_MIN_TREE_ITEMS = [
    "app/__init__.py",
    "app/services/__init__.py",
    "app/services/collection/__init__.py",
    "app/services/collection/site_caps.py",
    "app/services/collection/sites",
    "app/services/collection/mock_utils.py",
    "app/services/feishu/__init__.py",
    "app/services/feishu/limits.py",
    "app/utils/__init__.py",
    "app/utils/id_generator.py",
    "config/sites.yaml",
    "script/run_daily_task.sh",
    "tests/test_site_caps_budget.py",
]


def copy_min_tree(dst):
    """把跑测试所需的最小文件集合复制到 dst（跳过 __pycache__）。"""
    for rel in _MIN_TREE_ITEMS:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            continue
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target)


def run_lock_in_subprocess(tree_root):
    """在 tree_root 里跑「锁」（LOCK_ONLY=1），返回 (rc, 输出文本)。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = tree_root + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SITE_CAPS_LOCK_ONLY"] = "1"
    env["SITE_CAPS_LOCK_CHILD"] = "1"
    proc = subprocess.run(
        [sys.executable, os.path.join(tree_root, "tests", "test_site_caps_budget.py")],
        cwd=tree_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def run_site_caps_import_in_subprocess(source_text):
    tmp = tempfile.mkdtemp(prefix="site_caps_")
    try:
        write_text(os.path.join(tmp, "site_caps.py"), source_text)
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run([sys.executable, "-c", "import site_caps"],
                              cwd=tmp, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc.returncode, proc.stderr.decode("utf-8", "replace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def replace_occurrence(text, old, new, idx):
    """把 text 中第 idx 次（0-based）出现的 old 换成 new；不足则返回 None。"""
    if text.count(old) <= idx:
        return None
    pos = -1
    for _ in range(idx + 1):
        pos = text.index(old, pos + 1)
    return text[:pos] + new + text[pos + len(old):]


# ---------------------------------------------------------------------------
# 名录闭包（AST，站点源码 vs 名录）
# ---------------------------------------------------------------------------
def referenced_cap_keys():
    keys = set()
    for name in sorted(os.listdir(SITES_DIR)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        tree = ast.parse(read_text(os.path.join(SITES_DIR, name)))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "SITE_ROUND_CAPS"
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                keys.add(node.slice.value)
    return keys


def closure_check(registry):
    ref = referenced_cap_keys()
    missing = sorted(ref - set(registry))
    if missing:
        raise ValueError("名录闭包：站点声明了未登记的上界 %s" % missing)
    residue = sorted(set(registry) - ref)
    if residue:
        raise ValueError("名录闭包：名录残留死人 %s（无对应站点声明）" % residue)
    return True


# ---------------------------------------------------------------------------
# sites.yaml enabled 集合（优先 yaml，缺库回退最小解析）
# ---------------------------------------------------------------------------
def _minimal_enabled_parse(text):
    enabled = set()
    cur = None
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^  ([A-Za-z_][A-Za-z0-9_]*):\s*$", raw)
        if m:
            cur = m.group(1)
            enabled.add(cur)  # 缺 enabled 时默认 True（对齐 test_target_sites）
            continue
        m2 = re.match(r"^\s+enabled:\s*(\S+)\s*$", raw)
        if m2 and cur:
            if m2.group(1).lower() not in ("true", "yes", "on"):
                enabled.discard(cur)
    return enabled


def load_enabled_sites():
    text = read_text(SITES_YAML)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
        sites = data.get("sites", {}) or {}
        return set(k for k, v in sites.items() if (v or {}).get("enabled", True))
    except Exception:
        return _minimal_enabled_parse(text)


# ---------------------------------------------------------------------------
# M5 用：AST 判定「命名常量是否取自 SITE_ROUND_CAPS[key]」/「引用键」
# ---------------------------------------------------------------------------
def _named_binding_is_lookup(src, const_name, key):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == const_name:
                    v = node.value
                    return (isinstance(v, ast.Subscript)
                            and isinstance(v.value, ast.Name)
                            and v.value.id == "SITE_ROUND_CAPS"
                            and isinstance(v.slice, ast.Constant)
                            and v.slice.value == key)
    return False


def _references_key(src, key):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "SITE_ROUND_CAPS"
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == key):
            return True
    return False


def _imports_site_round_caps(src):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[-1]
            if mod == "site_caps":
                for a in node.names:
                    if a.name == "SITE_ROUND_CAPS":
                        return True
    return False


def _sentinel_slice_count(src):
    tree = ast.parse(src)
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if (isinstance(sl, ast.Slice) and sl.lower is None
                    and isinstance(sl.upper, ast.Name)
                    and sl.upper.id in SENTINEL_NAMES):
                n += 1
    return n


# ---------------------------------------------------------------------------
# M7 用：cron 行
# ---------------------------------------------------------------------------
_CRON_RE = re.compile(r"^\s*#\s*(\S+\s+){4}\S+.*run_daily_task\.sh\s*$", re.M)


def cron_line_count(sh_text):
    return len(_CRON_RE.findall(sh_text))


def rounds_consistency_ok(sh_text, rounds_per_day):
    return cron_line_count(sh_text) == rounds_per_day


# ===========================================================================
# 锁（LOCK_ONLY 子进程只跑这一段）
# ===========================================================================
def test_registry_lock():
    print("\n[L1] 名录闭包 + sites.yaml 交叉（锁）")
    s = load_real_site_caps()
    raised, msg = False, ""
    try:
        closure_check(s.SITE_ROUND_CAPS)
    except ValueError as e:
        raised, msg = True, str(e)
    check("L1a 真实名录闭包成立（声明键 == 名录键）", not raised, msg)

    enabled = load_enabled_sites()
    check("L1b 真实名录键 == sites.yaml enabled 集合",
          set(s.SITE_ROUND_CAPS) == enabled,
          "caps=%s enabled=%s" % (sorted(s.SITE_ROUND_CAPS), sorted(enabled)))


def test_m5_usage_lock():
    print("\n[M5] 「使用点」接线锁：赋值形状 + 切片计数 + 旧裸字面量缺失")
    s = load_real_site_caps()
    for key, (relpath, cname) in SITE_FILES.items():
        path = os.path.join(ROOT, relpath)
        src = read_text(path)
        check("%s import SITE_ROUND_CAPS" % key, _imports_site_round_caps(src), relpath)
        check("%s 引用名录键 '%s'" % (key, key), _references_key(src, key), relpath)
        if cname is not None:
            check("%s 的 %s 取自 SITE_ROUND_CAPS['%s']" % (key, cname, key),
                  _named_binding_is_lookup(src, cname, key), relpath)
        check("%s 名录值 == %d" % (key, EXPECTED_CAPS[key]),
              s.SITE_ROUND_CAPS.get(key) == EXPECTED_CAPS[key], s.SITE_ROUND_CAPS.get(key))

    # (a) 切片使用点计数锁（AST）
    for relpath, expected in SENTINEL_SLICE_COUNT.items():
        got = _sentinel_slice_count(read_text(os.path.join(ROOT, relpath)))
        check("M5a %s 哨兵切片数 == %d" % (relpath, expected), got == expected, "got=%d" % got)

    # (b) 负面锁：旧裸字面量在**代码行**中 0 次
    for relpath, literals in NEGATIVE_LITERALS.items():
        src = code_only(read_text(os.path.join(ROOT, relpath)))
        for lit in literals:
            check("M5b %s 代码行不含 %r" % (relpath, lit), src.count(lit) == 0,
                  "count=%d" % src.count(lit))

    # zhihu 正向：默认值取自名录
    zh = read_text(os.path.join(ROOT, SITE_FILES["zhihu"][0]))
    check('M5 zhihu 默认值取自 SITE_ROUND_CAPS["zhihu"]',
          'SITE_ROUND_CAPS["zhihu"]' in zh and "result_limit', 50" not in zh)


# ===========================================================================
# 变异自证（仅父进程；子进程 LOCK_ONLY 不跑，防递归）
# ===========================================================================
def test_m5_mutation_selfproof():
    print("\n[M5c] 变异自证：未变异对照 + 14 个位置逐个还原成裸字面量 -> 锁必须变红")

    # 对照：整树复制但**不**变异 -> 锁必须绿（证明子进程锁不是"恒红"）
    ctrl = tempfile.mkdtemp(prefix="site_caps_ctl_")
    try:
        copy_min_tree(ctrl)
        rc, out = run_lock_in_subprocess(ctrl)
        check("M5c#00 未变异对照 -> 锁为绿", rc == 0,
              "rc=%s out=%s" % (rc, out.strip().splitlines()[-1:]))
    finally:
        shutil.rmtree(ctrl, ignore_errors=True)

    for i, (relpath, sentinel, legacy, occ, label) in enumerate(POSITIONS, 1):
        work = tempfile.mkdtemp(prefix="site_caps_mut_")
        try:
            copy_min_tree(work)
            target = os.path.join(work, relpath)
            src = read_text(target)
            mutated = replace_occurrence(src, sentinel, legacy, occ)
            if mutated is None or mutated == src:
                check("M5c#%02d %s 变异可施加" % (i, label), False,
                      "snippet=%r occ=%d" % (sentinel, occ))
                continue
            write_text(target, mutated)
            rc, out = run_lock_in_subprocess(work)
            check("M5c#%02d %s -> 锁变红" % (i, label), rc != 0,
                  "rc=%s out=%s" % (rc, out.strip().splitlines()[-1:] if out else ""))
        finally:
            shutil.rmtree(work, ignore_errors=True)


# ===========================================================================
# 守卫 / 行为
# ===========================================================================
def test_real_values():
    print("\n[0] 真实 site_caps 的名录与守卫现值")
    s = load_real_site_caps()
    check("SITE_ROUND_CAPS 恰为 9 站", set(s.SITE_ROUND_CAPS) == set(EXPECTED_CAPS),
          sorted(s.SITE_ROUND_CAPS))
    check("各站上界 == 设计 §1.3 基线", dict(s.SITE_ROUND_CAPS) == EXPECTED_CAPS,
          dict(s.SITE_ROUND_CAPS))
    check("ROUNDS_PER_DAY == 2", s.ROUNDS_PER_DAY == 2, s.ROUNDS_PER_DAY)
    check("PER_ROUND_CAP_TOTAL == 460", s.PER_ROUND_CAP_TOTAL == 460, s.PER_ROUND_CAP_TOTAL)
    check("WORST_CASE_DAILY == 920", s.WORST_CASE_DAILY == 920, s.WORST_CASE_DAILY)
    check("ACKNOWLEDGED_WORST_CASE_DAILY == 920",
          s.ACKNOWLEDGED_WORST_CASE_DAILY == 920, s.ACKNOWLEDGED_WORST_CASE_DAILY)
    check("cap_for('thepaper') == 100", s.cap_for("thepaper") == 100, s.cap_for("thepaper"))


def test_control_import_ok():
    print("\n[A] 对照：未变异 site_caps.py 子进程导入成功")
    rc, err = run_site_caps_import_in_subprocess(read_text(SITE_CAPS_PATH))
    check("未变异副本退出码 0", rc == 0, "rc=%s stderr=%s" % (rc, err[-400:]))


def test_m1_thepaper_9999():
    print("\n[M1] thepaper 100 -> 9999：G2 棘轮必须 raise（独立子进程）")
    src = read_text(SITE_CAPS_PATH)
    old, new = '"thepaper": 100', '"thepaper": 9999'
    check("变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
    mutated = src.replace(old, new, 1)
    rc, err = run_site_caps_import_in_subprocess(mutated)
    check("M1 非 0 退出", rc != 0, "rc=%s" % rc)
    check("M1 stderr 含 ValueError", "ValueError" in err, err[-300:])
    check("M1 stderr 含 G2 文案", "G2" in err, err[-300:])


def test_m2_people_daily_99999():
    print("\n[M2] people_daily 50 -> 99999：G1 单轮可写性必须 raise（独立子进程）")
    src = read_text(SITE_CAPS_PATH)
    old, new = '"people_daily": 50', '"people_daily": 99999'
    check("变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
    mutated = src.replace(old, new, 1)
    rc, err = run_site_caps_import_in_subprocess(mutated)
    check("M2 非 0 退出", rc != 0, "rc=%s" % rc)
    check("M2 stderr 含 ValueError", "ValueError" in err, err[-300:])
    check("M2 stderr 含 G1 文案", "G1" in err, err[-300:])


def test_m3_production_keyerror():
    print("\n[M3] 生产行为：真删名录 'thepaper' 条目 -> import thepaper 必须 KeyError")
    work = tempfile.mkdtemp(prefix="site_caps_m3_")
    try:
        copy_min_tree(work)
        scpath = os.path.join(work, "app", "services", "collection", "site_caps.py")
        src = read_text(scpath)
        old = '    "thepaper": 100,\n'
        check("M3 变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
        write_text(scpath, src.replace(old, "", 1))
        # 子进程 import thepaper（桩 aiohttp，避免依赖；site_caps['thepaper'] 缺失 -> KeyError）
        code = (
            "import sys, types\n"
            "sys.path.insert(0, %r)\n"
            "a = types.ModuleType('aiohttp');\n"
            "a.ClientSession = a.ClientTimeout = a.TCPConnector = object\n"
            "sys.modules['aiohttp'] = a\n"
            "import app.services.collection.sites.thepaper\n"
        ) % work
        env = dict(os.environ)
        env["PYTHONPATH"] = work + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run([sys.executable, "-c", code], cwd=work, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        err = proc.stderr.decode("utf-8", "replace")
        check("M3 import thepaper 非 0 退出", proc.returncode != 0, "rc=%s" % proc.returncode)
        check("M3 失败原因为 KeyError('thepaper')",
              "KeyError" in err and "thepaper" in err, err[-300:])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_m4_yaml_cross_ghost():
    print("\n[M4] 名录 vs sites.yaml：加 'ghost':50 -> 锁必须变红（真读 yaml）")
    work = tempfile.mkdtemp(prefix="site_caps_m4_")
    try:
        copy_min_tree(work)
        scpath = os.path.join(work, "app", "services", "collection", "site_caps.py")
        src = read_text(scpath)
        m1 = src.replace('    "thepaper": 100,',
                         '    "thepaper": 100,\n    "ghost": 50,', 1)
        check("M4 加 ghost 靶点生效", m1 != src)
        # 同步抬高棘轮基线，让 import 期 G2 不 raise，从而只让「yaml 交叉锁」变红
        m2 = m1.replace("ACKNOWLEDGED_WORST_CASE_DAILY = 920",
                        "ACKNOWLEDGED_WORST_CASE_DAILY = 1020", 1)
        check("M4 抬高棘轮基线生效", m2 != m1)
        write_text(scpath, m2)
        rc, out = run_lock_in_subprocess(work)
        check("M4 加 ghost 后锁变红", rc != 0, "rc=%s" % rc)
        check("M4 失败文案点名 ghost/enabled/残留",
              any(t in out for t in ("ghost", "enabled", "残留")),
              out.strip().splitlines()[-3:])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_m6_harmless_control():
    print("\n[M6] 无害对照：只改注释 -> 仍可导入")
    src = read_text(SITE_CAPS_PATH)
    old, new = "ROUNDS_PER_DAY = 2", "ROUNDS_PER_DAY = 2  # 注释变异"
    check("M6 变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
    mutated = src.replace(old, new, 1)
    rc, err = run_site_caps_import_in_subprocess(mutated)
    check("M6 无害变异仍导入成功（rc==0）", rc == 0, "rc=%s stderr=%s" % (rc, err[-300:]))


def test_m7_rounds_anchor():
    print("\n[M7] 轮次假设锚到调度源（run_daily_task.sh 头部 cron 行数）")
    s = load_real_site_caps()
    sh = read_text(RUN_DAILY_SH)
    check("真实 run_daily_task.sh 头部有 2 条 cron 行", cron_line_count(sh) == 2,
          "n=%d" % cron_line_count(sh))
    check("真实 ROUNDS_PER_DAY == 2", s.ROUNDS_PER_DAY == 2, s.ROUNDS_PER_DAY)
    check("真实：cron 行数 == ROUNDS_PER_DAY", rounds_consistency_ok(sh, s.ROUNDS_PER_DAY))
    check("M7a 只把 ROUNDS_PER_DAY 改 1 -> 不一致(FAIL)", rounds_consistency_ok(sh, 1) is False)
    lines = sh.splitlines()
    kept, dropped = [], False
    for ln in lines:
        if not dropped and "run_daily_task.sh" in ln and ln.strip().startswith("#"):
            dropped = True
            continue
        kept.append(ln)
    sh_one = "\n".join(kept)
    check("M7b 删一条 cron 行后计数 == 1", cron_line_count(sh_one) == 1, cron_line_count(sh_one))
    check("M7b 源码减一行、ROUNDS_PER_DAY 仍 2 -> 不一致(FAIL)",
          rounds_consistency_ok(sh_one, 2) is False)
    check("M7c 两处一致改（都 1）-> 一致(PASS)", rounds_consistency_ok(sh_one, 1) is True)


def main():
    print("=" * 66)
    print("站点单轮上限名录 + 容量守卫回归测试  [mode=%s]" %
          ("LOCK-ONLY" if LOCK_ONLY else ("CHILD" if IS_CHILD else "FULL")))
    print("=" * 66)

    if LOCK_ONLY:
        test_registry_lock()
        test_m5_usage_lock()
    else:
        test_real_values()
        test_registry_lock()          # 闭包 + yaml 交叉
        test_control_import_ok()
        test_m1_thepaper_9999()
        test_m2_people_daily_99999()
        test_m3_production_keyerror()
        test_m4_yaml_cross_ghost()
        test_m5_usage_lock()
        if not IS_CHILD:
            test_m5_mutation_selfproof()
        test_m6_harmless_control()
        test_m7_rounds_anchor()

    print("\n" + "=" * 66)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
