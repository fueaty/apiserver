"""
热点特征分析模块
负责从飞书表格获取热点数据，并使用大模型分析热点特征
"""

from .feature_analyzer import FeatureAnalyzer
from .feishu_data_loader import FeishuDataLoader
from .llm_processor import LLMProcessor
from ..content_extraction.content_extractor import ContentExtractor
from ..classification.hotspot_classifier import HotspotClassifier
from ...storage.analysis_storage import AnalysisStorage

__all__ = [
    "FeatureAnalyzer",
    "FeishuDataLoader",
    "LLMProcessor",
    "ContentExtractor",
    "HotspotClassifier",
    "AnalysisStorage"
]

__version__ = '1.0.0'