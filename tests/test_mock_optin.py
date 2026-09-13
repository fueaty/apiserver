#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
mock **opt-in** 治理回归锁（Task #44 / P0-A + P0-C）—— 离线，无外网。

背景（#42 的漏洞）：
  #42 只在**写集侧**兜底——「就算采集失败产生了 mock，也按 is_mock 标记剔除」。
  但「采集失败 → **默认伪造**数据」这个**根因**没动；且 mock 治理的覆盖靠
  「枚举 sites/*.py」+「文本里出现过某函数名」两把锁，前者有枚举盲区
  （`_hidden_newsite.py` / `sub/newsite.py` 这类不被枚举到），后者检不出**行为失效**
  （`continue → pass` 之类）。

本文件覆盖（P0-A 根因 + P0-C 枚举无关守卫）：
  [A] fallback_or_empty 默认行为：返回 [] 且 warning 含「站点 + 原因」；
  [B] opt-in 行为：APISERVER_ALLOW_MOCK=1 才返回**打了 MOCK_FLAG** 的 mock（含包装体内层）；
  [C] 惰性：默认路径**根本不构造**假数据（callable 不被调用）——「生产默认不伪造」的硬证据；
  [D] 7 站**行为级**：强制网络失败后 collect() 默认返回 0 条 mock；opt-in 才返回带标记 mock；
  [E] P0-C 枚举无关守卫：**递归 AST** 扫描 app/services（含 `_` 前缀与子目录），
      所有「演示/回退数据产出函数」必须引用 MOCK_FLAG，否则本测试变红。

依赖桩（**条件桩**；判据：桩的合法性 = 被桩模块的行为是否被断言依赖）：
  aiohttp/bs4 只在 ImportError 时注入（本测试不联网、不断言其行为）。

    python tests/test_mock_optin.py     # 期望 RC=0
"""

import ast
import asyncio
import importlib
import os
import re
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


for _name in ("aiohttp", "httpx", "lark_oapi", "lark_oapi.api",
              "lark_oapi.api.bitable", "lark_oapi.api.bitable.v1",
              "pydantic", "pydantic_settings"):
    if _name in sys.modules:
        continue
    try:
        __import__(_name)
    except Exception:
        sys.modules[_name] = _stub_module(_name)

# bs4：baidu 在模块顶层 import；本测试不调用解析路径，其行为不被断言依赖。
if "bs4" not in sys.modules:
    try:
        import bs4  # noqa: F401
    except Exception:
        _bs4 = types.ModuleType("bs4")
        _bs4.BeautifulSoup = type("BeautifulSoup", (object,), {"__init__": lambda self, *a, **k: None,
                                                               "find_all": lambda self, *a, **k: []})
        sys.modules["bs4"] = _bs4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from app.services.collection.mock_utils import (  # noqa: E402
    MOCK_FLAG, ALLOW_MOCK_ENV, mock_allowed, is_mock_record, fallback_or_empty,
)
from app.services.collection.sites.base import BaseSite  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


SITES_DIR = os.path.join(ROOT, "app", "services", "collection", "sites")
SERVICES_DIR = os.path.join(ROOT, "app", "services")

# 7 个含 mock 回退的站点（供 [D] 逐站行为验证；枚举仅供**取用**，覆盖度由 [E] AST 守卫保证）。
MOCK_SITES = ("xinhua", "people_daily", "tech_36kr", "baidu", "cctv", "weibo", "xiaohongshu")


def _load_site_class(code):
    mod_name = f"app.services.collection.sites.{code}"
    mod = importlib.import_module(mod_name)
    for obj in vars(mod).values():
        if (isinstance(obj, type)
                and getattr(obj, "__module__", "") == mod_name
                and issubclass(obj, BaseSite)):
            return obj
    return None


class _MemHandler(object):
    """最小 logging.Handler：把 warning 文本收集起来，供断言。"""

    def __init__(self, sink):
        import logging
        self._h = logging.Handler()
        self._h.emit = lambda record: sink.append(record.getMessage())
        self._h.setLevel(0)
        self.sink = sink

    def __enter__(self):
        from app.utils.logger import logger
        logger.addHandler(self._h)
        return self

    def __exit__(self, *exc):
        from app.utils.logger import logger
        logger.removeHandler(self._h)
        return False


# ---------------------------------------------------------------------------
# [A][B][C] fallback_or_empty
# ---------------------------------------------------------------------------
def test_default_returns_empty_with_warning():
    print("\n[A] fallback_or_empty 默认：返回 [] + warning（站点/原因）")
    os.environ.pop(ALLOW_MOCK_ENV, None)
    check("[A] 默认可信：mock_allowed() is False", mock_allowed() is False,
          f"mock_allowed={mock_allowed()}")

    sink = []
    with _MemHandler(sink):
        out = fallback_or_empty("xinhua", "HTTP 状态码 403", [{"title": "示例", MOCK_FLAG: True}])
    check("[A] 默认返回空 list（不伪造）", out == [], f"out={out!r}")
    check("[A] 默认发出 warning", len(sink) >= 1, f"sink={sink}")
    check("[A] warning 含站点与原因",
          any("xinhua" in m and "HTTP 状态码 403" in m for m in sink), f"sink={sink}")


def test_optin_returns_tagged_mock():
    print("\n[B] opt-in：APISERVER_ALLOW_MOCK=1 才返回**打了标记**的 mock")
    os.environ[ALLOW_MOCK_ENV] = "1"
    try:
        check("[B] opt-in 生效：mock_allowed() is True", mock_allowed() is True, "")

        # 扁平 mock → 顶层打标记
        out_flat = fallback_or_empty("baidu", "解析为空", [{"title": "百度示例", "url": "u"}])
        check("[B] opt-in 扁平 mock：返回非空且 100% 判为 mock",
              len(out_flat) == 1 and is_mock_record(out_flat[0]),
              f"out={out_flat!r}")

        # 包装 mock → 内层打标记（is_mock_record 两层都查）
        out_wrap = fallback_or_empty("weibo", "解析为空", [{"fields": {"title": "微博示例"}}])
        check("[B] opt-in 包装 mock：内层打标记、仍被判为 mock",
              len(out_wrap) == 1 and is_mock_record(out_wrap[0]),
              f"out={out_wrap!r}")

        check("[B] 负控：opt-in 也不会把真实记录误标（输入未带标记的真实行）",
              is_mock_record({"title": "真实", "url": "u"}) is False, "")
    finally:
        os.environ.pop(ALLOW_MOCK_ENV, None)


def test_lazy_no_fabrication_by_default():
    print("\n[C] 惰性：默认路径**根本不构造**假数据（生产不伪造的硬证据）")
    os.environ.pop(ALLOW_MOCK_ENV, None)
    calls = {"n": 0}

    def _src():
        calls["n"] += 1
        return [{"title": "示例", MOCK_FLAG: True}]

    out = fallback_or_empty("cctv", "解析为空", _src)
    check("[C] 默认：返回空", out == [], f"out={out!r}")
    check("[C] 默认：items(callable) **未被调用**（没有构造任何假数据）",
          calls["n"] == 0, f"called={calls['n']}")

    os.environ[ALLOW_MOCK_ENV] = "1"
    try:
        out2 = fallback_or_empty("cctv", "解析为空", _src)
        check("[C] opt-in：callable 被调用且返回带标记 mock",
              calls["n"] == 1 and len(out2) == 1 and is_mock_record(out2[0]),
              f"called={calls['n']} out={out2!r}")
    finally:
        os.environ.pop(ALLOW_MOCK_ENV, None)


# ---------------------------------------------------------------------------
# [D] 逐站行为：网络失败 → 默认不产出 mock；opt-in 才产出
# ---------------------------------------------------------------------------
def _failed_collect(code):
    cls = _load_site_class(code)
    site = cls(code, {"timeout": 10})

    async def _boom():
        raise RuntimeError("NO_NET_SENTINEL")

    # 强制网络路径失败（xiaohongshu 因无 cookie 会先返回空，同样落到回退入口）
    site.get_session = _boom
    return asyncio.run(site.collect({"format": "feishu"}))


def test_per_site_behavior():
    print("\n[D] 逐站行为：网络失败 → collect() 默认不产出 mock；opt-in 才产出")

    os.environ.pop(ALLOW_MOCK_ENV, None)
    for code in MOCK_SITES:
        out = _failed_collect(code)
        mocked = [r for r in out if is_mock_record(r)]
        check(f"[D:{code}] 默认：无任何 mock 行进入 collect() 结果",
              len(mocked) == 0, f"mocked={mocked!r}")
        check(f"[D:{code}] 默认：结果为空（不伪造）",
              isinstance(out, list) and len(out) == 0, f"len={len(out)}")

    # opt-in：同一失败场景应产出**带标记**的 mock（证明回退点确实走了统一入口）
    os.environ[ALLOW_MOCK_ENV] = "1"
    try:
        for code in MOCK_SITES:
            out = _failed_collect(code)
            check(f"[D:{code}] opt-in：产出非空且 100% 带 MOCK_FLAG",
                  len(out) > 0 and all(is_mock_record(r) for r in out),
                  f"out={out!r}")
    finally:
        os.environ.pop(ALLOW_MOCK_ENV, None)


# ---------------------------------------------------------------------------
# [E] P0-C 枚举无关守卫：递归 AST 扫描 app/services
# ---------------------------------------------------------------------------
# 「演示/回退数据产出函数」命名集合。**注意**：`_is_mock_data`（谓词，返回 bool）不在内。
DEMO_NAME_RE = re.compile(r"^_(get_mock_data|mock_[A-Za-z0-9_]*|fallback_[A-Za-z0-9_]*)$")

# P2（延后）：N4 两个**非 headlines 写集**的演示/回退点，已知未打标记、显式豁免。
# 待 P2 处理后再把它们移出豁免名单（本测试对「豁免是子集」成立即可，改好后仍绿）。
N4_DEFERRED = {
    ("app/services/analysis/feature_analysis/llm_clients.py", "_mock_response"),
    ("app/services/selection/ml_engine.py", "_fallback_analysis"),
}


def _iter_py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        # 含 `_` 前缀文件与子目录；仅排除解释器缓存。
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _scan_demo_funcs():
    """返回 {(relpath, funcname): references_MOCK_FLAG}。"""
    found = {}
    for path in _iter_py_files(SERVICES_DIR):
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except SyntaxError:
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and DEMO_NAME_RE.match(node.name):
                refs = any(
                    (isinstance(n, ast.Name) and n.id == "MOCK_FLAG")
                    or (isinstance(n, ast.Attribute) and n.attr == "MOCK_FLAG")
                    for n in ast.walk(node)
                )
                found[(rel, node.name)] = refs
    return found


def test_ast_guard_enumeration_independent():
    print("\n[E] P0-C 枚举无关守卫：递归 AST 扫描 app/services 找演示/回退数据")

    found = _scan_demo_funcs()
    check("[E] 扫描非空（守卫不空转）", len(found) >= 7, f"发现 {len(found)} 个")

    # 7 站的 _get_mock_data 必须全部被扫到且**引用 MOCK_FLAG**
    for code in MOCK_SITES:
        key = (f"app/services/collection/sites/{code}.py", "_get_mock_data")
        check(f"[E:{code}] 被 AST 看到且引用 MOCK_FLAG",
              found.get(key) is True, f"found={found.get(key)}")

    unmarked = {k for k, v in found.items() if not v}
    check("[E] 未打标记的演示/回退函数 ⊆ N4 豁免名单（新增任何未标记点 → 变红）",
          unmarked <= N4_DEFERRED,
          f"未标记={sorted(unmarked)}，超出豁免={sorted(unmarked - N4_DEFERRED)}")

    check("[E] 豁免名单只含非采集域（不得把采集站点'豁免'掉）",
          all("sites/" not in p for p, _ in N4_DEFERRED), f"{N4_DEFERRED}")
    check("[E] 豁免名单规模锁 == 2（防止静默扩大）", len(N4_DEFERRED) == 2, "")


def main():
    print("=" * 70)
    print("mock opt-in 治理锁（离线）：默认不伪造 / opt-in 带标记 / 惰性 / 逐站 / AST 守卫")
    print("=" * 70)

    test_default_returns_empty_with_warning()
    test_optin_returns_tagged_mock()
    test_lazy_no_fabrication_by_default()
    test_per_site_behavior()
    test_ast_guard_enumeration_independent()

    print("=" * 70)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
