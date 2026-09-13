#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feature_analysis 包导入健康度回归测试（Fix 2 固化）

在离线桩环境下 import ``app.services.analysis.feature_analysis`` 后断言：
  - 真悬空依赖（except 收窄后仍需容错）降级为 None：
      FeatureAnalyzer is None、AnalysisStorage is None
  - 当前可正常导入的子模块（已改为**严格导入**）仍可用：
      FeishuDataLoader is not None、HotspotClassifier is not None
  - 核心 LLM 符号仍是强依赖且可用：LLMProcessor / LLMMockClient / build_llm_client
  - 源码级锁：__init__.py 使用收窄异常 ``(ImportError, ModuleNotFoundError)``，
    且**不**再出现宽 ``except Exception``（防止回归为静默吞异常）

自带第三方依赖桩（httpx / lark_oapi / app.core.config），不联网、不安装依赖：

    python tests/test_feature_analysis_package.py
"""

import os
import re
import sys
import types
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.join(ROOT, "app", "services", "analysis")
FA_DIR = os.path.join(ANALYSIS_DIR, "feature_analysis")
FEISHU_DIR = os.path.join(ROOT, "app", "services", "feishu")

# ---------------------------------------------------------------------------
# 1. 第三方依赖桩
# ---------------------------------------------------------------------------
httpx_stub = types.ModuleType("httpx")
httpx_stub.AsyncClient = object
httpx_stub.Client = object
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

# ---------------------------------------------------------------------------
# 2. app 包骨架
# ---------------------------------------------------------------------------
for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.utils", os.path.join(ROOT, "app", "utils")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.analysis", ANALYSIS_DIR),
    ("app.services.analysis.classification", os.path.join(ANALYSIS_DIR, "classification")),
    ("app.services.analysis.storage", os.path.join(ANALYSIS_DIR, "storage")),
    ("app.services.feishu", FEISHU_DIR),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

config_stub = types.ModuleType("app.core.config")
config_stub.config_manager = types.SimpleNamespace(
    get_config=lambda force_reload=False: {},
    get_credentials=lambda force_reload=False: {},
    get_sites_config=lambda force_reload=False: {"sites": {}},
)
sys.modules["app.core.config"] = config_stub


def _load(name, path, is_pkg=False):
    if is_pkg:
        spec = importlib.util.spec_from_file_location(
            name, path, submodule_search_locations=[os.path.dirname(path)]
        )
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# feishu_data_loader 依赖 app.services.feishu.feishu_service，先装载
_load("app.services.feishu.limits", os.path.join(FEISHU_DIR, "limits.py"))
_load("app.services.feishu.field_rules", os.path.join(FEISHU_DIR, "field_rules.py"))
_load("app.services.feishu.feishu_service", os.path.join(FEISHU_DIR, "feishu_service.py"))

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s" % name)
    else:
        FAILED.append(name + (" :: " + str(detail) if detail else ""))
        print("  [FAIL] %s  %s" % (name, detail))


def run():
    print("=" * 72)
    print("feature_analysis 包导入健康度回归测试（Fix 2）")
    print("=" * 72)

    print("\n[1] 包可 import（异常收窄后仍不崩）")
    pkg = None
    try:
        pkg = _load("app.services.analysis.feature_analysis",
                    os.path.join(FA_DIR, "__init__.py"), is_pkg=True)
        check("包可 import", True)
    except Exception as exc:  # noqa: BLE001
        check("包可 import", False, repr(exc))
        pkg = None

    if pkg is not None:
        print("\n[2] 真悬空依赖 -> None（保留容错）")
        check("FeatureAnalyzer is None", getattr(pkg, "FeatureAnalyzer", "missing") is None,
              type(getattr(pkg, "FeatureAnalyzer", "missing")).__name__)
        check("AnalysisStorage is None", getattr(pkg, "AnalysisStorage", "missing") is None,
              type(getattr(pkg, "AnalysisStorage", "missing")).__name__)

        print("\n[3] 当前可导入 -> 严格导入（非 None）")
        check("FeishuDataLoader is not None", getattr(pkg, "FeishuDataLoader", None) is not None,
              type(getattr(pkg, "FeishuDataLoader", None)).__name__)
        check("HotspotClassifier is not None", getattr(pkg, "HotspotClassifier", None) is not None,
              type(getattr(pkg, "HotspotClassifier", None)).__name__)

        print("\n[4] 核心 LLM 符号仍为强依赖")
        check("LLMProcessor 可用", getattr(pkg, "LLMProcessor", None) is not None)
        check("LLMMockClient 可用", getattr(pkg, "LLMMockClient", None) is not None)
        check("build_llm_client 可用", callable(getattr(pkg, "build_llm_client", None)))

    print("\n[5] 源码级锁：收窄异常、禁用宽 except")
    src = open(os.path.join(FA_DIR, "__init__.py"), encoding="utf-8").read()
    check("使用收窄异常 (ImportError, ModuleNotFoundError)",
          "(ImportError, ModuleNotFoundError)" in src)
    check("未再出现宽 except Exception", re.search(r"except\s+Exception", src) is None)
    check("容错分支有 logger.exception 记录", src.count("logger.exception") >= 2,
          src.count("logger.exception"))

    print("\n" + "=" * 72)
    print("PASSED: %d    FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("-" * 72)
        for f in FAILED:
            print("  FAILED -> %s" % f)
    print("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(run())
