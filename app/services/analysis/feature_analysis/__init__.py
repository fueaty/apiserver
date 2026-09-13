"""
热点特征分析模块
负责从飞书表格获取热点数据，并使用大模型分析热点特征

依赖健康度（2026-09 以隔离探针逐个实测）——本包内存在 **2 处真实悬空依赖**：
  1. ``feature_analyzer``  → ``..content_extraction.content_extractor``
     （``app.services.analysis.content_extraction`` 模块不存在）
  2. ``analysis_storage``  → ``...storage.analysis_storage``
     （``app.services.storage`` 包不存在；实际文件位于
      ``app/services/analysis/storage/analysis_storage.py``，且其自身还依赖同样
      不存在的 ``app.models``）

历史 ``__init__.py`` 直接 ``from .feature_analyzer import FeatureAnalyzer``，导致
**整包 import 即失败**，连带 ``llm_processor`` / ``llm_clients`` 也不可用
（需求③依赖它们，必须先解除该阻塞）。

处理策略：
  - 上述 **2 个真悬空** 子模块：容错导入，且异常类型**收窄**为
    ``(ImportError, ModuleNotFoundError)`` 并 ``logger.exception`` 记录，缺失时降级为
    ``None``。收窄后，语法错误 / ``NameError`` 之类的真实 bug 不会再被静默吞成
    ``None``（那会让问题以难定位的 ``AttributeError`` 形式在别处爆出来）。
  - 另外 **2 个当前可正常导入** 的子模块（``feishu_data_loader`` /
    ``hotspot_classifier``，经探针实测 OK）：改为 **严格导入**，让将来的真实回归
    fail fast。
  - 核心 LLM 子模块（``llm_processor`` / ``llm_clients``）保持强依赖。

  ⚠️ 本模块只做容错，**不**新建 ``content_extraction`` / ``app.models`` /
  ``app.services.storage``——补全这些缺失模块属后续独立事项。
"""

import logging

logger = logging.getLogger(__name__)

# 核心：LLM 客户端与处理器（需求③，务必可用）
from .llm_clients import (
    BaseLLMClient,
    OpenAICompatClient,
    LLMMockClient,
    build_llm_client,
)
from .llm_processor import LLMProcessor

# 当前可正常导入的两个子模块：严格导入（真实回归应 fail fast，而非被静默吞掉）
from .feishu_data_loader import FeishuDataLoader
from ..classification.hotspot_classifier import HotspotClassifier

# 真悬空依赖 #1：feature_analyzer -> app.services.analysis.content_extraction（不存在）
try:
    from .feature_analyzer import FeatureAnalyzer
except (ImportError, ModuleNotFoundError):
    logger.exception(
        "可选子模块 feature_analyzer 导入失败（悬空依赖 content_extraction），降级为 None"
    )
    FeatureAnalyzer = None

# 真悬空依赖 #2：analysis_storage -> app.services.storage（不存在）/ app.models（不存在）
try:
    from ...storage.analysis_storage import AnalysisStorage
except (ImportError, ModuleNotFoundError):
    logger.exception(
        "可选子模块 analysis_storage 导入失败（悬空依赖 app.services.storage / app.models），降级为 None"
    )
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
