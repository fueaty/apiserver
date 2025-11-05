"""基于机器学习的智能选材引擎"""

import logging
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Any
from app.core.config import ConfigManager

logger = logging.getLogger(__name__)


class MLSelectionEngine:
    """基于机器学习的智能选材引擎"""
    
    def __init__(self, model_path: str = "content_matching_model.pkl", 
                 preferences_path: str = "platform_preferences.pkl"):
        """
        初始化机器学习选材引擎
        
        参数:
        - model_path: 训练好的模型文件路径
        - preferences_path: 平台偏好配置文件路径
        """
        self.config_manager = ConfigManager()
        self.platform_profiles = {}
        self.model = None
        self.platform_preferences = None
        
        # 尝试加载模型和平台偏好配置
        try:
            self.model = joblib.load(model_path)
            self.platform_preferences = joblib.load(preferences_path)
            logger.info("成功加载机器学习模型和平台偏好配置")
        except Exception as e:
            logger.warning(f"无法加载机器学习模型: {e}")
            logger.warning("将使用基于规则的选材引擎")
        
        # 加载平台配置
        self._load_configs()
        
    def _load_configs(self):
        """加载平台配置"""
        try:
            # 加载平台配置
            platforms_config = self.config_manager.get_platforms_config()
            if platforms_config and "publish_platforms" in platforms_config:
                # 遍历所有发布平台的配置
                for platform, config in platforms_config["publish_platforms"].items():
                    # 如果平台配置中有选材规则，则加载
                    if "selection_rules" in config:
                        self.platform_profiles[platform] = config["selection_rules"]
                        
            logger.info(f"成功加载 {len(self.platform_profiles)} 个平台配置")
            
        except Exception as e:
            logger.error(f"加载选材引擎配置失败: {e}")
            raise
    
    def _preprocess_text(self, text: str) -> str:
        """
        文本预处理函数
        """
        import re
        # 去除特殊字符和数字
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\d+', '', text)
        return text
    
    def _extract_features(self, item: Dict[str, Any], platform: str) -> List[float]:
        """
        提取用于模型预测的特征
        
        参数:
        - item: 热点数据
        - platform: 目标平台
        
        返回:
        - 特征向量
        """
        features = []
        
        title = item.get("title", "")
        
        # 计算与各平台偏好的匹配度
        for pref_platform, preferences in self.platform_preferences.items():
            match_score = 0.0
            if preferences:
                match_score = sum(1 for pref in preferences if pref in title) / len(preferences)
            features.append(match_score)
            
        return features
    
    def analyze_hotspot_suitability(self, hotspot: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """
        使用机器学习模型分析热点在指定平台的适用性
        
        参数:
        - hotspot: 热点数据
        - platform: 目标平台
        
        返回:
        - 分析结果
        """
        # 如果没有加载模型，回退到基于规则的引擎
        if self.model is None or self.platform_preferences is None:
            return self._fallback_analysis(hotspot, platform)
        
        try:
            # 提取特征
            features = self._extract_features(hotspot, platform)
            
            # 使用模型预测
            features_array = np.array(features).reshape(1, -1)
            prediction = self.model.predict(features_array)[0]
            probabilities = self.model.predict_proba(features_array)[0]
            
            # 获取目标平台的索引
            platform_index = list(self.platform_preferences.keys()).index(platform)
            platform_probability = probabilities[platform_index] if platform_index < len(probabilities) else 0.5
            
            # 结合热度、时效性等因素调整得分
            hot_score = self._calculate_hot_score(hotspot)
            recency_score = self._calculate_recency_score(hotspot)
            
            # 综合得分
            final_score = (platform_probability * 0.6 + hot_score * 0.3 + recency_score * 0.1)
            
            # 生成推荐理由
            reason = self._generate_reason(platform_probability, hot_score, recency_score)
            
            return {
                "hotspot_id": hotspot.get("id"),
                "title": hotspot.get("title"),
                "total_score": round(final_score, 2),
                "content_angle": self._generate_content_angle(hotspot, platform),
                "recommended_strategy": self._recommend_strategy(platform),
                "reason": reason,
                "detailed_scores": {
                    "platform_match": round(platform_probability, 4),
                    "hot": round(hot_score, 4),
                    "recency": round(recency_score, 4)
                }
            }
            
        except Exception as e:
            logger.error(f"ML分析过程中出错: {e}")
            # 出错时回退到基于规则的分析
            return self._fallback_analysis(hotspot, platform)
    
    def _calculate_hot_score(self, hotspot: Dict[str, Any]) -> float:
        """
        计算热度得分
        """
        hot = hotspot.get("hot", 0)
        try:
            val = float(hot)
            # 使用对数归一化
            import math
            score = math.log1p(val) / 10.0
            return max(0.0, min(1.0, score))
        except:
            return 0.5
    
    def _calculate_recency_score(self, hotspot: Dict[str, Any]) -> float:
        """
        计算时效性得分
        """
        from datetime import datetime
        
        collected_at = hotspot.get("collected_at")
        if not collected_at:
            return 0.5
            
        try:
            if isinstance(collected_at, str):
                dt = datetime.fromisoformat(collected_at.replace(' ', 'T'))
            else:
                dt = collected_at
                
            hours = max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)
            # 使用指数衰减
            import math
            score = math.exp(-hours / 6.0)
            return score
        except:
            return 0.5
    
    def _generate_reason(self, platform_prob: float, hot_score: float, recency_score: float) -> str:
        """
        生成推荐理由
        """
        reasons = []
        if platform_prob >= 0.7:
            reasons.append("平台匹配度高")
        elif platform_prob >= 0.4:
            reasons.append("平台适配性良好")
            
        if hot_score >= 0.7:
            reasons.append("热度很高")
        elif hot_score >= 0.4:
            reasons.append("热度适中")
            
        if recency_score >= 0.7:
            reasons.append("时效性很强")
        elif recency_score >= 0.4:
            reasons.append("时效性良好")
            
        if not reasons:
            reasons.append("综合表现良好")
            
        return "，".join(reasons)
    
    def _generate_content_angle(self, hotspot: Dict[str, Any], platform: str) -> str:
        """
        生成内容角度建议
        """
        title = hotspot.get("title", "")
        platform_config = self.platform_profiles.get(platform, {})
        platform_style = platform_config.get("content_style", "")
        
        if "情感" in platform_style:
            return f"个人视角：{title}的情感体验分享"
        elif "深度" in platform_style or "专业" in platform_style:
            return f"深度分析：{title}背后的逻辑与影响"
        elif "趋势" in platform_style:
            return f"趋势解读：{title}的发展趋势分析"
        else:
            return f"热点解读：{title}的关键信息梳理"
    
    def _recommend_strategy(self, platform: str) -> str:
        """
        推荐内容策略
        """
        platform_config = self.platform_profiles.get(platform, {})
        platform_name = platform_config.get("name", platform)
        
        if "小红书" in platform_name:
            return "情感共鸣策略"
        elif "知乎" in platform_name:
            return "知识分享策略"
        elif "头条" in platform_name or "微博" in platform_name:
            return "趋势分析策略"
        else:
            return "快速资讯策略"
    
    def _fallback_analysis(self, hotspot: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """
        回退到基于规则的分析方法
        """
        logger.info("回退到基于规则的选材分析")
        
        # 简单的规则基础分析
        hot_score = self._calculate_hot_score(hotspot)
        recency_score = self._calculate_recency_score(hotspot)
        
        # 基于标题的简单匹配
        title = hotspot.get("title", "").lower()
        platform_config = self.platform_profiles.get(platform, {})
        preferences = platform_config.get("content_preferences", [])
        
        match_score = 0.1  # 默认基础分数
        if preferences:
            for pref in preferences:
                if pref.lower() in title:
                    match_score = 0.8
                    break
        
        final_score = (match_score * 0.5 + hot_score * 0.3 + recency_score * 0.2)
        
        return {
            "hotspot_id": hotspot.get("id"),
            "title": hotspot.get("title"),
            "total_score": round(final_score, 2),
            "content_angle": self._generate_content_angle(hotspot, platform),
            "recommended_strategy": self._recommend_strategy(platform),
            "reason": "使用基于规则的分析方法",
            "detailed_scores": {
                "platform_match": round(match_score, 4),
                "hot": round(hot_score, 4),
                "recency": round(recency_score, 4)
            }
        }