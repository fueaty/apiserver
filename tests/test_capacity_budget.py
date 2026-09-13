#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
容量预算守卫回归测试（app/services/feishu/limits.py）

覆盖：
  1. 真实 `limits.py` 的三条容量不变式与现值
     （RETENTION_DAYS=25 / DAILY_BUDGET=630 / WATERMARK=17,000 /
       WARNING=18,500 / TABLE_RECORD_LIMIT=20,000）。
  2. **import 期守卫真的会 raise**（不是 warn / logger.error）：
     用「把 limits.py 复制到临时目录、文本变异一个常量、在子进程里 import 它」
     的方式，分别破坏 3 条不变式，断言子进程非 0 退出且 stderr 含 ValueError。
     另设「不改常量的对照」必须成功导入——这是变异测试，证明守卫对常量错误
     有鉴别力，而不是摆设。
  3. 天数唯一事实来源一致性：`cleanup_feishu_data.py` 的 `--days` 默认值取自
     `RETENTION_DAYS`；`scheduled_cleanup.sh` 不再写死 `DAYS=`、不再传 `--days`。

自带依赖：仅标准库（`limits.py` 本身零第三方依赖），不联网、无需安装项目依赖。
运行：

    python tests/test_capacity_budget.py
"""

import os
import sys
import shutil
import tempfile
import subprocess
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMITS_PATH = os.path.join(ROOT, "app", "services", "feishu", "limits.py")
CLEANUP_PY = os.path.join(ROOT, "script", "cleanup_feishu_data.py")
CLEANUP_SH = os.path.join(ROOT, "script", "scheduled_cleanup.sh")

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


def load_real_limits():
    """从真实路径加载 limits.py（模块名刻意区分，避免与临时副本混淆）。"""
    spec = importlib.util.spec_from_file_location("_real_limits_under_test", LIMITS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_import_in_subprocess(source_text):
    """把 source_text 写成临时目录下的 limits.py，用子进程 `import limits`。

    返回 (returncode, stderr_text)。cwd 与 PYTHONPATH 都指向临时目录，
    确保子进程导入的是这份变异副本，而不是真实 limits.py。
    """
    tmp = tempfile.mkdtemp(prefix="cap_budget_")
    try:
        with open(os.path.join(tmp, "limits.py"), "w", encoding="utf-8") as f:
            f.write(source_text)
        env = dict(os.environ)
        env["PYTHONPATH"] = tmp + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, "-c", "import limits"],
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc.returncode, proc.stderr.decode("utf-8", "replace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
def test_real_invariants():
    print("\n[1] 真实 limits.py 的容量不变式与现值")
    lim = load_real_limits()
    check("RETENTION_DAYS == 25", lim.RETENTION_DAYS == 25, lim.RETENTION_DAYS)
    check("DAILY_BUDGET == 630", lim.DAILY_BUDGET == 630, lim.DAILY_BUDGET)
    check("WATERMARK == 17000", lim.WATERMARK == 17000, lim.WATERMARK)
    check("WARNING == 18500", lim.WARNING == 18500, lim.WARNING)
    check("TABLE_RECORD_LIMIT == 20000", lim.TABLE_RECORD_LIMIT == 20000,
          lim.TABLE_RECORD_LIMIT)

    budget = lim.RETENTION_DAYS * lim.DAILY_BUDGET
    check("25 × 630 == 15750", budget == 15750, budget)
    check("不变式1 RETENTION_DAYS*DAILY_BUDGET <= WATERMARK", budget <= lim.WATERMARK,
          "%d <= %d" % (budget, lim.WATERMARK))
    check("不变式2 WATERMARK < WARNING", lim.WATERMARK < lim.WARNING)
    check("不变式3 WARNING < TABLE_RECORD_LIMIT", lim.WARNING < lim.TABLE_RECORD_LIMIT)

    # 余量诚实性：17000/20000 只留 15%（旧值 14000 留 30%）
    margin = (lim.TABLE_RECORD_LIMIT - lim.WATERMARK) * 100.0 / lim.TABLE_RECORD_LIMIT
    check("安全余量 = 15%（不粉饰）", abs(margin - 15.0) < 1e-9, margin)


def test_control_import_ok():
    print("\n[2] 对照：未变异的 limits.py 子进程导入成功")
    rc, err = run_import_in_subprocess(read_text(LIMITS_PATH))
    check("未变异副本退出码 0", rc == 0, "rc=%s stderr=%s" % (rc, err[-400:]))


def test_guard_blows_on_mutation():
    print("\n[3] 变异破坏三条不变式 -> 子进程 import 必须 raise ValueError")
    src = read_text(LIMITS_PATH)

    cases = [
        ("不变式1 预算>水位 (DAILY_BUDGET 630->9999)",
         "DAILY_BUDGET = 630", "DAILY_BUDGET = 9999", "容量预算超限"),
        ("不变式2 水位顺序反 (WATERMARK 17000->19000)",
         "WATERMARK = 17_000", "WATERMARK = 19_000", "水位线顺序错误"),
        ("不变式3 告警越界 (WARNING 18500->25000)",
         "WARNING = 18_500", "WARNING = 25_000", "水位线顺序错误"),
    ]
    for name, old, new, needle in cases:
        hits = src.count(old)
        check("变异靶点存在且唯一：%s" % old, hits == 1, "count=%d" % hits)
        mutated = src.replace(old, new, 1)
        check("文本确已改变：%s" % name, mutated != src)

        rc, err = run_import_in_subprocess(mutated)
        check("%s -> 非 0 退出" % name, rc != 0, "rc=%s" % rc)
        check("%s -> stderr 含 ValueError" % name, "ValueError" in err, err[-300:])
        check("%s -> stderr 含守卫文案「%s」" % (name, needle), needle in err, err[-300:])

    # 反向对照：只改注释、不动任何常量 -> 仍可成功导入。
    # 证明上面对照组的失败来自不变式被破坏，而不是「变异这个动作本身」。
    harmless = src.replace("# 飞书错误码常量", "# 飞书错误码常量（注释变异）", 1)
    check("无害变异文本已改变", harmless != src)
    rc2, err2 = run_import_in_subprocess(harmless)
    check("无害变异仍导入成功", rc2 == 0, "rc=%s stderr=%s" % (rc2, err2[-300:]))


def _code_lines(text):
    """去掉空行与整行注释，仅保留会真正执行的代码行。

    守卫只关心「代码是否写死天数 / 是否传 --days」——注释里解释历史教训
    （例如「历史教训：DAYS=35 与文档不一致」）是合理的，不应被误伤。
    """
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def test_single_source_of_truth():
    print("\n[4] 天数唯一事实来源一致性")
    sh_code = _code_lines(read_text(CLEANUP_SH))
    py = read_text(CLEANUP_PY)

    check("scheduled_cleanup.sh 代码行不再硬编码 DAYS=",
          all("DAYS=" not in ln for ln in sh_code),
          [ln for ln in sh_code if "DAYS=" in ln])
    check("scheduled_cleanup.sh 代码行不再传 --days",
          all("--days" not in ln for ln in sh_code),
          [ln for ln in sh_code if "--days" in ln])
    check("cleanup_feishu_data.py 已 import RETENTION_DAYS",
          "RETENTION_DAYS" in py)
    check("cleanup_feishu_data.py 的 --days 默认取 RETENTION_DAYS",
          "default=RETENTION_DAYS" in py)


def main():
    print("=" * 66)
    print("容量预算守卫回归测试")
    print("=" * 66)

    test_real_invariants()
    test_control_import_ok()
    test_guard_blows_on_mutation()
    test_single_source_of_truth()

    print("\n" + "=" * 66)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
