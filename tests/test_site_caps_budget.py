#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
站点单轮上限名录 + 容量守卫回归测试（app/services/collection/site_caps.py）

对应设计 `.workbuddy/_next/站点上限守卫设计.md` §3.3 的 M1–M7。
全部为**离线、无网络、无第三方依赖**断言（仅标准库 + 站点源码文本/AST 扫描）。

为什么要这些"变异对照"：本项目已三次踩"断言绿但无鉴别力"的坑
（``all([])==True``、站点枚举写死、接线锁只查文本）。故 M1–M7 每条都给出
**变异靶点 → 期望变红**，证明守卫/接线锁**真的读了真实代码路径**，而非摆设。

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

# 站点 → (站点模块相对路径, 该站"命名上界常量"名 or None)
# thepaper 用既有公开名 MAX_RESULTS；其余 8 站用内部名 _MAX；
# zhihu 无模块级常量（其上界是 `.get('result_limit', SITE_ROUND_CAPS["zhihu"])` 的默认值）。
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

# §1.3 的设计基线（真·单轮上界）
EXPECTED_CAPS = {
    "people_daily": 50, "xinhua": 30, "cctv": 50, "thepaper": 100,
    "weibo": 50, "baidu": 50, "zhihu": 50, "tech_36kr": 50, "xiaohongshu": 30,
}

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


# ---------------------------------------------------------------------------
# 被测对象：真实 site_caps（import 会触发 G1/G2 守卫）
# ---------------------------------------------------------------------------
def load_real_site_caps():
    from app.services.collection import site_caps
    return site_caps


def run_site_caps_import_in_subprocess(source_text):
    """把 source_text 写成临时目录下的 site_caps.py，用子进程 `import site_caps`。

    返回 (returncode, stderr_text)。cwd 指向临时目录（`python -c` 会把 cwd 放到
    sys.path[0]），因此导入的是这份**变异副本**；PYTHONPATH 指向仓库根，使副本里
    的 `from app.services.feishu import limits` 仍能解析到**真实** limits（守卫要读
    它的 WATERMARK）。
    """
    tmp = tempfile.mkdtemp(prefix="site_caps_")
    try:
        with open(os.path.join(tmp, "site_caps.py"), "w", encoding="utf-8") as f:
            f.write(source_text)
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, "-c", "import site_caps"],
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc.returncode, proc.stderr.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 名录闭包：从**真实站点源码**（AST）取"被声明的上界键"，与名录交叉
# ---------------------------------------------------------------------------
def referenced_cap_keys():
    """扫描 sites/*.py，收集所有 `SITE_ROUND_CAPS["<key>"]` 里引用的键。"""
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
    """名录闭包：站点声明的上界键 与 名录键 必须**互为子集**（即相等）。

    - 站点声明了未登记的键 → ValueError（"名录闭包：站点声明了未登记的上界"）
    - 名录里有多余的键（无站点声明 / 已停用）→ ValueError（"名录残留死人"）
    """
    ref = referenced_cap_keys()
    missing = sorted(ref - set(registry))
    if missing:
        raise ValueError("名录闭包：站点声明了未登记的上界 %s" % missing)
    residue = sorted(set(registry) - ref)
    if residue:
        raise ValueError("名录闭包：名录残留死人 %s（无对应站点声明）" % residue)
    return True


# ---------------------------------------------------------------------------
# M5 用：AST 判定"某命名常量是否取自 SITE_ROUND_CAPS[key]"
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


# ---------------------------------------------------------------------------
# M7 用：数 run_daily_task.sh 头部的 cron 行
# ---------------------------------------------------------------------------
_CRON_RE = re.compile(r"^\s*#\s*(\S+\s+){4}\S+.*run_daily_task\.sh\s*$", re.M)


def cron_line_count(sh_text):
    return len(_CRON_RE.findall(sh_text))


def rounds_consistency_ok(sh_text, rounds_per_day):
    """轮次假设是否与调度源一致：cron 行数 == ROUNDS_PER_DAY。"""
    return cron_line_count(sh_text) == rounds_per_day


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
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
    # 导入期 G1/G2 已成立（能 import 到这一步即证明没 raise）
    check("G1 单轮 Σ(上界) <= WATERMARK", s.PER_ROUND_CAP_TOTAL <= __import__(
        "app.services.feishu.limits", fromlist=["WATERMARK"]).WATERMARK)


def test_closure_real():
    print("\n[0b] 名录闭包（真实名录 vs 真实站点源码 AST）")
    s = load_real_site_caps()
    check("真实名录闭包成立（声明键 == 名录键）",
          closure_check(s.SITE_ROUND_CAPS) is True, "closure_check 未通过")


def test_control_import_ok():
    print("\n[A] 对照：未变异的 site_caps.py 子进程导入成功")
    rc, err = run_site_caps_import_in_subprocess(read_text(SITE_CAPS_PATH))
    check("未变异副本退出码 0", rc == 0, "rc=%s stderr=%s" % (rc, err[-400:]))


def test_m1_thepaper_9999():
    print("\n[M1] thepaper 100 -> 9999：G2 棘轮必须 raise")
    src = read_text(SITE_CAPS_PATH)
    old, new = '"thepaper": 100', '"thepaper": 9999'
    check("变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
    mutated = src.replace(old, new, 1)
    check("文本确已改变", mutated != src)
    rc, err = run_site_caps_import_in_subprocess(mutated)
    check("M1 非 0 退出", rc != 0, "rc=%s" % rc)
    check("M1 stderr 含 ValueError", "ValueError" in err, err[-300:])
    check("M1 stderr 含 G2 文案", "G2" in err, err[-300:])


def test_m2_people_daily_99999():
    print("\n[M2] people_daily 50 -> 99999：G1 单轮可写性必须 raise")
    src = read_text(SITE_CAPS_PATH)
    old, new = '"people_daily": 50', '"people_daily": 99999'
    check("变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
    mutated = src.replace(old, new, 1)
    check("文本确已改变", mutated != src)
    rc, err = run_site_caps_import_in_subprocess(mutated)
    check("M2 非 0 退出", rc != 0, "rc=%s" % rc)
    check("M2 stderr 含 ValueError", "ValueError" in err, err[-300:])
    check("M2 stderr 含 G1 文案", "G1" in err, err[-300:])


def test_m3_missing_entry():
    print("\n[M3] 名录删掉 'thepaper'，但 thepaper.py 仍声明 MAX_RESULTS -> 闭包 ValueError")
    s = load_real_site_caps()
    reg = dict(s.SITE_ROUND_CAPS)
    reg.pop("thepaper", None)
    raised = False
    msg = ""
    try:
        closure_check(reg)
    except ValueError as e:
        raised, msg = True, str(e)
    check("M3 闭包检查 raise ValueError", raised, "未 raise")
    check("M3 文案指向「站点声明了未登记的上界」", "未登记" in msg, msg)


def test_m4_ghost_entry():
    print("\n[M4] 名录多加 'ghost':50 但无对应站点 -> 闭包 ValueError（名录残留死人）")
    s = load_real_site_caps()
    reg = dict(s.SITE_ROUND_CAPS)
    reg["ghost"] = 50
    raised = False
    msg = ""
    try:
        closure_check(reg)
    except ValueError as e:
        raised, msg = True, str(e)
    check("M4 闭包检查 raise ValueError", raised, "未 raise")
    check("M4 文案指向「名录残留死人」", "残留" in msg, msg)


def test_m5_wiring_ast():
    print("\n[M5] 站点生效值真的取自名录（AST 接线锁）")
    s = load_real_site_caps()
    for key, (relpath, cname) in SITE_FILES.items():
        path = os.path.join(ROOT, relpath)
        src = read_text(path)
        check("%s 已 import SITE_ROUND_CAPS" % key, _imports_site_round_caps(src), relpath)
        check("%s 源码引用名录键 '%s'" % (key, key), _references_key(src, key), relpath)
        if cname is not None:
            check("%s 的 %s 取自 SITE_ROUND_CAPS['%s']" % (key, cname, key),
                  _named_binding_is_lookup(src, cname, key), relpath)
        # 生效值 == 名录值（用真实名录解析）
        check("%s 名录值 == %d" % (key, EXPECTED_CAPS[key]),
              s.SITE_ROUND_CAPS.get(key) == EXPECTED_CAPS[key],
              s.SITE_ROUND_CAPS.get(key))

    # 变异：把 thepaper 的命名常量改回裸字面量 -> 接线锁必须判定为 False
    tp = read_text(os.path.join(ROOT, SITE_FILES["thepaper"][0]))
    old = 'MAX_RESULTS = SITE_ROUND_CAPS["thepaper"]'
    check("M5 变异靶点存在", old in tp, "未找到 %s" % old)
    mutated = tp.replace(old, "MAX_RESULTS = 9999", 1)
    check("M5 变异文本确已改变", mutated != tp)
    check("M5 裸字面量化后被接线锁判定为 False",
          _named_binding_is_lookup(mutated, "MAX_RESULTS", "thepaper") is False)


def test_m6_harmless_control():
    print("\n[M6] 无害对照：只改注释 -> 仍可导入")
    src = read_text(SITE_CAPS_PATH)
    old, new = "ROUNDS_PER_DAY = 2", "ROUNDS_PER_DAY = 2  # 注释变异"
    check("M6 变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
    mutated = src.replace(old, new, 1)
    check("M6 文本确已改变", mutated != src)
    rc, err = run_site_caps_import_in_subprocess(mutated)
    check("M6 无害变异仍导入成功（rc==0）", rc == 0, "rc=%s stderr=%s" % (rc, err[-300:]))


def test_m7_rounds_anchor():
    print("\n[M7] 轮次假设锚到调度源（run_daily_task.sh 头部 cron 行数）")
    s = load_real_site_caps()
    sh = read_text(RUN_DAILY_SH)
    n = cron_line_count(sh)
    check("真实 run_daily_task.sh 头部有 2 条 cron 行", n == 2, "n=%d" % n)
    check("真实 ROUNDS_PER_DAY == 2", s.ROUNDS_PER_DAY == 2, s.ROUNDS_PER_DAY)
    check("真实：cron 行数 == ROUNDS_PER_DAY", rounds_consistency_ok(sh, s.ROUNDS_PER_DAY))

    # 只改一处 -> FAIL
    check("M7a 只把 ROUNDS_PER_DAY 改 1 -> 不一致(FAIL)",
          rounds_consistency_ok(sh, 1) is False)
    # 删掉一条 cron 行（源码变异）-> 与 2 不一致 FAIL
    lines = sh.splitlines()
    kept = []
    dropped = False
    for ln in lines:
        if not dropped and "run_daily_task.sh" in ln and ln.strip().startswith("#"):
            dropped = True
            continue
        kept.append(ln)
    sh_one = "\n".join(kept)
    check("M7b 删一条 cron 行后 cron 计数 == 1", cron_line_count(sh_one) == 1,
          cron_line_count(sh_one))
    check("M7b 源码减一行、ROUNDS_PER_DAY 仍 2 -> 不一致(FAIL)",
          rounds_consistency_ok(sh_one, 2) is False)
    # 两处一致改 -> PASS（证明该断言真的读了 cron 源，而非只比常量）
    check("M7c 两处一致改（都 1）-> 一致(PASS)",
          rounds_consistency_ok(sh_one, 1) is True)


def main():
    print("=" * 66)
    print("站点单轮上限名录 + 容量守卫回归测试")
    print("=" * 66)

    test_real_values()
    test_closure_real()
    test_control_import_ok()
    test_m1_thepaper_9999()
    test_m2_people_daily_99999()
    test_m3_missing_entry()
    test_m4_ghost_entry()
    test_m5_wiring_ast()
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
