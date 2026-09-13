#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 可插拔与工厂回归测试（需求③）

覆盖：
  - build_llm_client：无 key → mock；有 key+base_url → real；有 key 无 base_url → mock
  - 两个客户端均实现 async generate + sync generate_sync（同签名）
  - 源码无硬编码密钥（无 'sk-' 字面量、无 32 位以上可疑 hex/base64 字符串常量）
  - LLMProcessor 默认（无 Key）→ llm_client_mode=='mock' 且 analyze_hotspot 成功
  - feature_analysis 包（含容错 __init__）可正常 import 并暴露 LLMProcessor

自带第三方依赖桩（httpx / app.core.config），不联网、不安装依赖：

    python tests/test_llm_client_factory.py
"""

import os
import re
import sys
import ast
import types
import inspect
import asyncio
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.join(ROOT, "app", "services", "analysis")
FA_DIR = os.path.join(ANALYSIS_DIR, "feature_analysis")

# ---------------------------------------------------------------------------
# 1. 第三方依赖桩
# ---------------------------------------------------------------------------
httpx_stub = types.ModuleType("httpx")
httpx_stub.AsyncClient = object
httpx_stub.Client = object
sys.modules["httpx"] = httpx_stub

for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.utils", os.path.join(ROOT, "app", "utils")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.analysis", ANALYSIS_DIR),
    ("app.services.analysis.feature_analysis", FA_DIR),
    ("app.services.analysis.classification", os.path.join(ANALYSIS_DIR, "classification")),
    ("app.services.analysis.storage", os.path.join(ANALYSIS_DIR, "storage")),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

# 无 Key 的配置桩：get_llm 段为空 → 必须降级 Mock
config_stub = types.ModuleType("app.core.config")
config_stub.config_manager = types.SimpleNamespace(
    get_config=lambda force_reload=False: {},
    get_credentials=lambda force_reload=False: {},
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


llm_clients = _load("app.services.analysis.feature_analysis.llm_clients",
                    os.path.join(FA_DIR, "llm_clients.py"))
llm_processor = _load("app.services.analysis.feature_analysis.llm_processor",
                      os.path.join(FA_DIR, "llm_processor.py"))

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s" % name)
    else:
        FAILED.append(name + (" :: " + str(detail) if detail else ""))
        print("  [FAIL] %s  %s" % (name, detail))


def _param_names(fn):
    return list(inspect.signature(fn).parameters.keys())


def run():
    print("=" * 72)
    print("LLM 可插拔与工厂回归测试")
    print("=" * 72)

    BaseLLMClient = llm_clients.BaseLLMClient
    OpenAICompatClient = llm_clients.OpenAICompatClient
    LLMMockClient = llm_clients.LLMMockClient
    build_llm_client = llm_clients.build_llm_client

    # [1] 工厂：无 key → mock
    print("\n[1] build_llm_client 选择逻辑")
    c1, m1 = build_llm_client("openai", "gpt-4-turbo", None, None, 30)
    check("无 key -> mode='mock'", m1 == "mock", m1)
    check("无 key -> LLMMockClient", isinstance(c1, LLMMockClient), type(c1).__name__)

    c2, m2 = build_llm_client("openai", "gpt-4-turbo", "https://api.openai.com/v1", "secret-key-xyz", 30)
    check("有 key+base_url -> mode='real'", m2 == "real", m2)
    check("有 key+base_url -> OpenAICompatClient", isinstance(c2, OpenAICompatClient), type(c2).__name__)

    c3, m3 = build_llm_client("openai", "gpt-4-turbo", None, "secret-key-xyz", 30)
    check("有 key 无 base_url -> mock", m3 == "mock", m3)

    c4, m4 = build_llm_client("openai", "gpt-4-turbo", "https://x/v1", "", 30)
    check("空 key -> mock", m4 == "mock", m4)

    # [2] 接口契约：async generate + sync generate_sync，签名一致
    print("\n[2] 接口契约（generate / generate_sync）")
    for cls in (OpenAICompatClient, LLMMockClient):
        check("%s.generate 为协程函数" % cls.__name__,
              inspect.iscoroutinefunction(cls.generate))
        check("%s.generate_sync 为同步函数" % cls.__name__,
              not inspect.iscoroutinefunction(cls.generate_sync))
    check("Mock.generate 参数签名",
          _param_names(LLMMockClient.generate) == ["self", "prompt", "temperature", "max_tokens"],
          _param_names(LLMMockClient.generate))
    check("Mock.generate_sync 参数签名",
          _param_names(LLMMockClient.generate_sync) == ["self", "prompt", "temperature", "max_tokens"],
          _param_names(LLMMockClient.generate_sync))
    check("Real.generate 参数签名",
          _param_names(OpenAICompatClient.generate) == ["self", "prompt", "temperature", "max_tokens"],
          _param_names(OpenAICompatClient.generate))

    # [3] LLMMockClient generate_sync 可返回
    print("\n[3] Mock 客户端实际可调用")
    sync_out = LLMMockClient().generate_sync("任意提示")
    check("generate_sync 返回字符串", isinstance(sync_out, str) and len(sync_out) > 0)

    # [4] LLMProcessor 默认降级 Mock 且分析可用
    print("\n[4] LLMProcessor 默认（无 Key）")
    proc = llm_processor.LLMProcessor()
    check("llm_client_mode == 'mock'", getattr(proc, "llm_client_mode", None) == "mock",
          getattr(proc, "llm_client_mode", None))
    result = asyncio.run(proc.analyze_hotspot({"id": "h1", "title": "测试热点", "url": "https://x"}))
    check("analyze_hotspot 成功（无 error）", isinstance(result, dict) and "error" not in result, result)
    check("analyze_hotspot 含 analysis_result", bool(result.get("analysis_result")), result)

    # [5] feature_analysis 包可 import（含容错 __init__）
    print("\n[5] feature_analysis 包 import 容错")
    try:
        pkg = _load("app.services.analysis.feature_analysis",
                    os.path.join(FA_DIR, "__init__.py"), is_pkg=True)
        check("包可 import", True)
        check("包暴露 LLMProcessor", hasattr(pkg, "LLMProcessor"))
        check("包暴露 LLMMockClient", hasattr(pkg, "LLMMockClient"))
        check("包暴露 build_llm_client", hasattr(pkg, "build_llm_client"))
        check("悬空依赖 FeatureAnalyzer 降级为 None", getattr(pkg, "FeatureAnalyzer", "x") is None,
              type(getattr(pkg, "FeatureAnalyzer", "missing")).__name__)
    except Exception as exc:  # noqa: BLE001
        check("包可 import", False, repr(exc))

    # [6] 源码无硬编码密钥
    print("\n[6] 源码无硬编码密钥")
    targets = [
        ("llm_clients.py", os.path.join(FA_DIR, "llm_clients.py")),
        ("llm_processor.py", os.path.join(FA_DIR, "llm_processor.py")),
        ("insights_service.py", os.path.join(ANALYSIS_DIR, "insights_service.py")),
    ]
    for label, path in targets:
        src = open(path, encoding="utf-8").read()
        check("%s 无 'sk-' 字面量" % label, "sk-" not in src)
        suspicious = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value.strip()
                if len(v) >= 32 and re.fullmatch(r"[A-Za-z0-9+/=_\-]+", v):
                    suspicious.append(v[:40])
        check("%s 无 32+ 位可疑密钥字面量" % label, not suspicious, suspicious)

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
