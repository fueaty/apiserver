"""
热点特征分析模块
负责从飞书表格获取热点数据，并使用大模型分析热点特征

⚠️ 容错说明（必要性）
该包内存在**历史遗留的悬空依赖**：``feature_analyzer.py`` 引用了并不存在的
``..content_extraction.content_extractor``（该模块在仓库中不存在）。旧的
``__init__.py`` 直接 ``from .feature_analyzer import FeatureAnalyzer``，导致
**整个包 import 即失败**，连带 ``llm_processor`` / ``llm_clients`` 也不可用
（本次需求③依赖它们，必须先解除该阻塞）。

这里对可选子模块做**容错导入**：缺失的降级为 None，而非让整包 import 失败；
核心的 LLM 子模块（llm_processor / llm_clients）保持强依赖。
"""

# 核心：LLM 客户端与处理器（需求③，务必可用）
from .llm_clients import (
    BaseLLMClient,
    OpenAICompatClient,
    LLMMockClient,
    build_llm_client,
)
from .llm_processor import LLMProcessor

# 可选子模块：存在悬空依赖，缺失时降级为 None
try:
    from .feature_analyzer import FeatureAnalyzer
except Exception:  # noqa: BLE001 —— 悬空依赖容错，避免拖垮整包
    FeatureAnalyzer = None

try:
    from .feishu_data_loader import FeishuDataLoader
except Exception:  # noqa: BLE001
    FeishuDataLoader = None

try:
    from ..classification.hotspot_classifier import HotspotClassifier
except Exception:  # noqa: BLE001
    HotspotClassifier = None

try:
    from ...storage.analysis_storage import AnalysisStorage
except Exception:  # noqa: BLE001
    AnalysisStorage = None

__all__ = [
    "LLMProcessor",
    "BaseLLMClient",
    "OpenAICompatClient",
    "LLMMockClient",
    "build_llm_client",
    "FeatureAnalyzer",
    "FeishuDataLoader",
    "HotspotClassifier",
    "AnalysisStorage",
]

__version__ = '1.0.0'
