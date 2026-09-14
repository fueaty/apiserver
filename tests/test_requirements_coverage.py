#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖覆盖度回归测试：**全仓** import 的第三方模块，必须在 requirements.txt 有对应包。

背景（两次真实缺口）：
  - 2026-09 曾漏 pin `lark_oapi`（导入名 lark_oapi / 包名 lark-oapi）；
  - 复查时发现「只扫 app/ + script/」会漏掉 `secret/` 与根目录训练脚本里的
    `jwt` / `jieba` / `sklearn` —— 一次人工核对不算修复，这道测试才算。

⚠️ 本测试曾经的缺陷：**「绿而盲」（green-but-blind）**。
   本文件声明「已覆盖 `secret/` 与根训练脚本」，但在**干净检出**里 `secret/`
   是被 `.gitignore:3` 忽略的目录——缺失时那几条 check **静默消失**，测试仍
   37/0 全绿 ⇒ 「已覆盖 secret/」这一声明在干净检出下**为假**。
   修法（见 `test_scan_scope`）：
     · 把**实际扫描范围**（根目录名 + 被扫文件数）**打印出来**，缩小即可见；
     · 对**应当存在**的扫描根（`EXPECTED_ROOTS`）与**缺口锚文件**（`EXPECTED_GAP_FILES`）
       逐条断言存在；缺失即 FAIL，且失败文案**直接告诉人怎么办**；
     · 断言文档所述缺口模块（`jwt`/`jieba`/`sklearn`）**确实被扫到**。
   由此：在**干净 `git worktree`**（无 `secret/`）下本测试会**变红**，不再假绿。

做法（AST 全仓扫描 + 冻结映射）：
  1. 解析全仓 *.py 的 import 语句，得到「第三方顶层模块」集合；
  2. 用**冻结的** MODULE_TO_DIST 把导入名换算成 PyPI 发行名
     （7 个「导入名≠包名」写全，其余按同名换算）；
  3. 断言每个模块都能在 requirements.txt 中找到对应包；
  4. 排除 stdlib 与本项目包（app / function / script / tests / config / secret）。

自带依赖：仅标准库，不联网、无需安装项目依赖。运行：

    python tests/test_requirements_coverage.py

环境变量（内部用，防递归）：
  REQCOV_CHILD=1  标记「鉴别力自证」子进程（跳过自证自身，防递归）

退出码：0 = 全部通过；1 = 有失败。
"""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")

SKIP_DIRS = {"__pycache__", ".git", ".workbuddy", "node_modules", "venv",
             ".venv", "env", "history_data", "logs", "backup", ".pytest_cache"}
LOCAL_PKGS = {"app", "function", "script", "tests", "config", "secret"}

# stdlib 兜底集合（覆盖 3.9 无 sys.stdlib_module_names 的情况）
_CURATED_STDLIB = {
    "__future__", "abc", "argparse", "asyncio", "base64", "collections",
    "contextlib", "copy", "csv", "dataclasses", "datetime", "enum", "functools",
    "glob", "hashlib", "hmac", "html", "importlib", "inspect", "io", "itertools",
    "json", "logging", "math", "os", "pathlib", "platform", "random", "re",
    "secrets", "shutil", "signal", "socket", "statistics", "string",
    "subprocess", "sys", "tempfile", "threading", "time", "traceback", "typing",
    "urllib", "uuid", "warnings", "weakref", "xml", "zipfile",
}
STDLIB = set(_CURATED_STDLIB)
if hasattr(sys, "stdlib_module_names"):
    STDLIB |= set(sys.stdlib_module_names)

# 导入名 -> PyPI 发行名（**冻结**；不同名的 7 个必须写全，勿改成启发式）
MODULE_TO_DIST = {
    "jose": "python-jose",
    "jwt": "PyJWT",
    "bs4": "beautifulsoup4",
    "lark_oapi": "lark-oapi",
    "pydantic_settings": "pydantic-settings",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}
# 其余导入名与包名一致，按同名换算（MODULE_TO_DIST.get(mod, mod)）。

# —— 覆盖度声明的「可验证前提」（缺失即本测试变红）——
# 以**实际仓库**为准：本仓库顶层扫描根为 app/config/script/secret/tests 与根级脚本。
# 注：`function/` 在本仓库**不存在**，故不列入（列了会制造恒红的环境噪声）。
EXPECTED_ROOTS = ["app", "config", "script", "secret", "tests"]
# 文档所述历史缺口的「锚文件」——它们的存在 = 「已覆盖 secret/ 与根训练脚本」的前提。
EXPECTED_GAP_FILES = [
    "secret/generate_auth_key.py",       # import jwt
    "train_content_matching_model.py",   # import jieba / sklearn
]
# 上述锚文件应引入的第三方模块（必须真被扫到）。
EXPECTED_GAP_MODULES = ["jwt", "jieba", "sklearn"]

IS_CHILD = os.environ.get("REQCOV_CHILD") == "1"

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [OK] %s" % name)
    else:
        FAILED.append("%s :: %s" % (name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def _rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _top_of(rel):
    parts = rel.split("/")
    return parts[0] if len(parts) > 1 else "<root>"


def scan_third_party_modules():
    """AST 全仓扫描。

    Returns:
        (mods, files): mods = {顶层模块: {文件集合}}（已排除 stdlib 与本地包）；
        files = 被扫到的 *.py 相对路径列表（供「扫描范围显式化」用）。
    """
    found = {}
    scanned_files = []

    def scan(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except Exception as exc:  # noqa
            print("  !! 解析失败 %s: %s" % (path, exc))
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(path)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # 相对导入 = 本项目
                if not node.module:
                    continue
                found.setdefault(node.module.split(".")[0], set()).add(path)

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                p = os.path.join(dirpath, fn)
                scanned_files.append(_rel(p))
                scan(p)

    mods = {k: v for k, v in found.items()
            if k not in STDLIB and k not in LOCAL_PKGS}
    return mods, scanned_files


def parse_requirements():
    """解析 requirements.txt，返回小写发行名集合。"""
    names = set()
    with open(REQUIREMENTS, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # 兼容 "name==ver" 与 "name @ file://..."（后者本项目不出现）
            name = line.split("==")[0].split("@")[0].strip()
            if name:
                names.add(name.lower())
    return names


# ---------------------------------------------------------------------------
# [0] 扫描范围显式化 + 覆盖度声明的可验证前提（治「绿而盲」）
# ---------------------------------------------------------------------------
def test_scan_scope(scanned_files, mods):
    print("\n[0] 扫描范围显式化 + 覆盖度前提断言（缺失即红）")

    by_root = Counter(_top_of(f) for f in scanned_files)
    print("  · 实际扫描到的根 / 每个根的 .py 文件数：")
    for root in sorted(by_root):
        print("      %-12s %d" % (root, by_root[root]))
    print("  · 被扫 .py 文件总数：%d" % len(scanned_files))

    check("扫描到 >= 20 个 .py 文件（口径未退化成空扫）",
          len(scanned_files) >= 20, "got=%d" % len(scanned_files))

    # (1) 应当存在的扫描根，逐条断言存在
    for root in EXPECTED_ROOTS:
        check("扫描根存在: %s/" % root,
              os.path.isdir(os.path.join(ROOT, root)),
              "缺少 %s/ —— 该根很可能被 gitignore 或未检出，本门禁的覆盖度声明在"
              "此环境下**不成立**。请在「含 %s/ 的完整工作树」中运行本门禁"
              "（不要用缺少 gitignored 内容的干净 worktree 跑本门禁）。" % (root, root))

    # (2) 文档所述历史缺口的锚文件，逐条断言存在且确实被扫到
    for rel in EXPECTED_GAP_FILES:
        check("缺口锚文件存在: %s" % rel,
              os.path.exists(os.path.join(ROOT, rel)),
              "缺少 %s —— 文档声称已覆盖该文件，但文件不存在（被 gitignore/未检出/被删），"
              "覆盖度声明不成立。请恢复该文件，或在含它的完整工作树中运行本门禁。" % rel)
        check("缺口锚文件已被扫描: %s" % rel,
              rel in scanned_files,
              "%s 未被扫描（扫描范围缩小），其 import 不会被计入覆盖度。" % rel)

    # (3) 文档所述缺口模块必须真被扫到（这是「绿而盲」的正中靶心）
    for mod in EXPECTED_GAP_MODULES:
        check("缺口模块被扫到: %s" % mod,
              mod in mods,
              "未扫到 %s —— secret/generate_auth_key.py 或 train_content_matching_model.py "
              "缺失/被删，导致「已覆盖 %s」的声明在干净检出下为假。" % (mod, mod))


# ---------------------------------------------------------------------------
# [1] 冻结映射
# ---------------------------------------------------------------------------
def test_renames_frozen():
    print("\n[1] 冻结的「导入名≠包名」映射（7 个必须写全）")
    expected = {
        "jose": "python-jose",
        "jwt": "PyJWT",
        "bs4": "beautifulsoup4",
        "lark_oapi": "lark-oapi",
        "pydantic_settings": "pydantic-settings",
        "sklearn": "scikit-learn",
        "yaml": "PyYAML",
    }
    for mod, dist in expected.items():
        check("映射 %-18s -> %s" % (mod, dist),
              MODULE_TO_DIST.get(mod) == dist, MODULE_TO_DIST.get(mod))


# ---------------------------------------------------------------------------
# [2] 覆盖度
# ---------------------------------------------------------------------------
def test_coverage(scanned_files, mods):
    print("\n[2] 全仓 import 的第三方模块 -> requirements 覆盖")
    req = parse_requirements()

    check("扫描到 >= 20 个第三方模块（口径未退化成只扫子目录）",
          len(mods) >= 20, "got=%d" % len(mods))
    print("  · 被扫到的第三方模块（%d 个）：%s" % (len(mods), sorted(mods)))

    missing = []
    for mod in sorted(mods):
        dist = MODULE_TO_DIST.get(mod, mod)
        ok = dist.lower() in req
        check("pin 覆盖: %-18s -> %-20s" % (mod, dist), ok,
              "requirements.txt 缺 %s" % dist)
        if not ok:
            missing.append("%s(->%s)" % (mod, dist))

    check("无未命中（0 个缺口）", not missing, missing)


# ---------------------------------------------------------------------------
# [3] 历史缺口锁死
# ---------------------------------------------------------------------------
def test_known_gaps_locked():
    print("\n[3] 历史缺口锁死（防止回退）")
    req = parse_requirements()
    check("lark-oapi 在列（历史 lark_oapi 缺口）", "lark-oapi" in req)
    check("jieba 在列（训练脚本补漏缺口）", "jieba" in req)
    check("PyJWT 在列（secret/ jwt 缺口）", "pyjwt" in req)
    check("scikit-learn 在列（sklearn 缺口）", "scikit-learn" in req)
    check("playwright 在列", "playwright" in req)
    check("requirements pin 数量 >= 90", len(req) >= 90, "got=%d" % len(req))


# ---------------------------------------------------------------------------
# [4] 鉴别力自证：删掉缺口锚文件 -> 本测试必须变红（仅父进程跑）
# ---------------------------------------------------------------------------
def _copy_repo(dst):
    """把整个仓库（去掉 SKIP_DIRS 与以 . 开头的目录）复制到 dst。"""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        rel = _rel(dirpath)
        target = dst if rel == "." else os.path.join(dst, *rel.split("/"))
        os.makedirs(target, exist_ok=True)
        for fn in filenames:
            shutil.copy2(os.path.join(dirpath, fn), os.path.join(target, fn))


def _run_child(tree):
    """在 tree 里跑本测试（REQCOV_CHILD=1），返回 (rc, 输出)。"""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["REQCOV_CHILD"] = "1"
    proc = subprocess.run(
        [sys.executable, os.path.join(tree, "tests", "test_requirements_coverage.py")],
        cwd=tree, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def test_discrimination_selfproof():
    print("\n[4] 鉴别力自证：未变异对照->绿；删缺口锚文件->红")
    today_cases = [
        ("对照：完整副本（含 secret/）", None, 0),
        ("变异A：删 secret/generate_auth_key.py", ("file", "secret/generate_auth_key.py"), 1),
        ("变异B：删整个 secret/（模拟干净 worktree）", ("dir", "secret"), 1),
        ("变异C：删 train_content_matching_model.py", ("file", "train_content_matching_model.py"), 1),
    ]
    for label, mutation, expect_code in today_cases:
        work = tempfile.mkdtemp(prefix="reqcov_")
        try:
            _copy_repo(work)
            if mutation is not None:
                kind, rel = mutation
                tgt = os.path.join(work, *rel.split("/"))
                if kind == "file":
                    os.remove(tgt)
                else:
                    shutil.rmtree(tgt, ignore_errors=True)
            rc, out = _run_child(work)
            if expect_code == 0:
                check("自证 %s -> 绿(rc=0)" % label, rc == 0,
                      "rc=%s 末行=%s" % (rc, out.strip().splitlines()[-1:]))
            else:
                check("自证 %s -> 红(rc!=0)" % label, rc != 0,
                      "rc=%s 末行=%s" % (rc, out.strip().splitlines()[-1:]))
                # 失败文案应点名缺口（可诊断）
                check("自证 %s：红的时候点名缺口" % label,
                      any(tok in out for tok in ("secret", "jwt", "jieba", "sklearn",
                                                 "train_content_matching_model", "缺口")),
                      out.strip().splitlines()[-3:])
        finally:
            shutil.rmtree(work, ignore_errors=True)


def main():
    print("=" * 66)
    print("依赖覆盖度回归测试（全仓 import vs requirements.txt）  [mode=%s]"
          % ("CHILD" if IS_CHILD else "FULL"))
    print("=" * 66)

    mods, scanned_files = scan_third_party_modules()

    test_scan_scope(scanned_files, mods)
    test_renames_frozen()
    test_coverage(scanned_files, mods)
    test_known_gaps_locked()
    if not IS_CHILD:
        test_discrimination_selfproof()

    print("\n" + "=" * 66)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
