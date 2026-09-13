#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖覆盖度回归测试：**全仓** import 的第三方模块，必须在 requirements.txt 有对应包。

背景（两次真实缺口）：
  - 2026-09 曾漏 pin `lark_oapi`（导入名 lark_oapi / 包名 lark-oapi）；
  - 复查时发现「只扫 app/ + script/」会漏掉 `secret/` 与根目录训练脚本里的
    `jwt` / `jieba` / `sklearn` —— 一次人工核对不算修复，这道测试才算。

做法（AST 全仓扫描 + 冻结映射）：
  1. 解析全仓 *.py 的 import 语句，得到「第三方顶层模块」集合；
  2. 用**冻结的** MODULE_TO_DIST 把导入名换算成 PyPI 发行名
     （7 个「导入名≠包名」写全，其余按同名换算）；
  3. 断言每个模块都能在 requirements.txt 中找到对应包；
  4. 排除 stdlib 与本项目包（app / function / script / tests / config / secret）。

自带依赖：仅标准库，不联网、无需安装项目依赖。运行：

    python tests/test_requirements_coverage.py
"""

import ast
import os
import sys

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

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [OK] %s" % name)
    else:
        FAILED.append("%s :: %s" % (name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def scan_third_party_modules():
    """AST 全仓扫描，返回 {顶层模块: {文件集合}}（已排除 stdlib 与本地包）。"""
    found = {}

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
                scan(os.path.join(dirpath, fn))

    return {k: v for k, v in found.items()
            if k not in STDLIB and k not in LOCAL_PKGS}


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


def test_coverage():
    print("\n[2] 全仓 import 的第三方模块 -> requirements 覆盖")
    mods = scan_third_party_modules()
    req = parse_requirements()

    check("扫描到 >= 20 个第三方模块（口径未退化成只扫子目录）",
          len(mods) >= 20, "got=%d" % len(mods))

    missing = []
    for mod in sorted(mods):
        dist = MODULE_TO_DIST.get(mod, mod)
        ok = dist.lower() in req
        check("pin 覆盖: %-18s -> %-20s" % (mod, dist), ok,
              "requirements.txt 缺 %s" % dist)
        if not ok:
            missing.append("%s(->%s)" % (mod, dist))

    check("无未命中（0 个缺口）", not missing, missing)


def test_known_gaps_locked():
    print("\n[3] 历史缺口锁死（防止回退）")
    req = parse_requirements()
    check("lark-oapi 在列（历史 lark_oapi 缺口）", "lark-oapi" in req)
    check("jieba 在列（训练脚本补漏缺口）", "jieba" in req)
    check("PyJWT 在列（secret/ jwt 缺口）", "pyjwt" in req)
    check("scikit-learn 在列（sklearn 缺口）", "scikit-learn" in req)
    check("playwright 在列", "playwright" in req)
    check("requirements pin 数量 >= 90", len(req) >= 90, "got=%d" % len(req))


def main():
    print("=" * 66)
    print("依赖覆盖度回归测试（全仓 import vs requirements.txt）")
    print("=" * 66)

    test_renames_frozen()
    test_coverage()
    test_known_gaps_locked()

    print("\n" + "=" * 66)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
