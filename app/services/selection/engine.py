"""智能选材引擎核心类"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Any
from app.core.config import ConfigManager
from functools import lru_cache

logger = logging.getLogger(__name__)


# 默认配置
DEFAULT_CONFIG = {
    "weights": {"hot": 0.5, "recency": 0.25, "title": 0.15, "platform": 0.1},
    "decay_hours": 6.0,
    "platform_weights": {"weibo": 1.0, "baidu": 0.95, "zhihu": 0.9, "default": 0.8},
    "min_score": 0.0,
    "max_items_per_request": 300,
    "threshold_score": 0.1
}


class SelectionEngine:
    """智能选材引擎 - 负责分析热点内容在不同平台的适用性并进行筛选"""
    
    def __init__(self):
        """
        初始化选材引擎
        1. 创建配置管理器实例
        2. 初始化平台配置和内容策略字典
        3. 加载配置信息
        """
        self.config_manager = ConfigManager()
        self.platform_profiles = {}      # 存储各平台的配置信息
        self.content_strategies = {}     # 存储内容策略
        self._load_configs()
        
    def _load_configs(self):
        """加载平台配置和内容策略"""
        try:
            # 加载平台配置
            platforms_config = self.config_manager.get_platforms_config()
            if platforms_config and "publish_platforms" in platforms_config:
                # 遍历所有发布平台的配置
                for platform, config in platforms_config["publish_platforms"].items():
                    # 如果平台配置中有选材规则，则加载
                    if "selection_rules" in config:
                        self.platform_profiles[platform] = config["selection_rules"]
            
            # 加载内容策略 - 预定义不同类型平台的内容创作策略
            self.content_strategies = {
                "emotional_appeal": {
                    "applicable_platforms": ["xiaohongshu", "douyin"],      # 适用平台：小红书、抖音
                    "content_elements": ["个人故事", "情感触发", "视觉隐喻"],   # 内容要素
                    "strategy_name": "情感共鸣策略",                         # 策略名称
                    "description": "通过情感故事和视觉元素引发用户共鸣"      # 策略描述
                },
                "knowledge_sharing": {
                    "applicable_platforms": ["zhihu", "wechat_public"],    # 适用平台：知乎、微信公众号
                    "content_elements": ["数据支撑", "专家观点", "结构化分析"],  # 内容要素
                    "strategy_name": "知识分享策略",                         # 策略名称
                    "description": "提供深度分析和专业知识内容"              # 策略描述
                },
                "trend_analysis": {
                    "applicable_platforms": ["toutiao", "weibo"],          # 适用平台：头条、微博
                    "content_elements": ["热点追踪", "趋势预测", "快速解读"],   # 内容要素
                    "strategy_name": "趋势分析策略",                         # 策略名称
                    "description": "快速响应热点，提供趋势分析和解读"        # 策略描述
                },
                "quick_news": {
                    "applicable_platforms": ["toutiao", "weibo"],          # 适用平台：头条、微博
                    "content_elements": ["简洁明了", "时效性强", "重点突出"],   # 内容要素
                    "strategy_name": "快速资讯策略",                         # 策略名称
                    "description": "提供快速、简洁的资讯内容"                # 策略描述
                }
            }
            
            logger.info(f"成功加载 {len(self.platform_profiles)} 个平台配置和 {len(self.content_strategies)} 个内容策略")
            
        except Exception as e:
            logger.error(f"加载选材引擎配置失败: {e}")
            raise
    
    def _log1p_norm_hot(self, hot):
        """对热度值进行对数归一化处理"""
        try:
            val = float(hot)
        except Exception:
            val = 0.0
        # log1p then scale: empirical scale factor 10 (tuneable)
        s = math.log1p(max(0.0, val)) / 10.0
        return max(0.0, min(1.0, s))
    
    def _recency_score(self, collected_at, decay_hours):
        """计算时效性得分"""
        if not collected_at:
            return 0.5
        try:
            if isinstance(collected_at, str):
                # accept "YYYY-MM-DD HH:MM:SS" or ISO
                dt = datetime.fromisoformat(collected_at.replace(' ', 'T'))
            elif isinstance(collected_at, datetime):
                dt = collected_at
            else:
                return 0.5
            hours = max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)
            return math.exp(-hours / max(1.0, decay_hours))
        except Exception:
            return 0.5

    @lru_cache(maxsize=512)
    def _title_keyword_score(self, title):
        """基于标题关键词计算得分"""
        if not title:
            return 0.0
        # small curated keyword list
        kws = ["官宣", "爆", "首", "夺冠", "离世", "热", "？", "?", "!", "！", "#"]
        score = 0.0
        for kw in kws:
            if kw in title:
                score += 1.0
        # short punchy titles get a boost
        ln = len(title.strip())
        if 5 <= ln <= 30:
            score += 0.5
        # normalize (cap)
        return min(1.0, score / 3.0)
    
    def _platform_weight(self, site_code, cfg):
        """获取平台权重"""
        return cfg.get("platform_weights", {}).get(site_code, cfg.get("platform_weights", {}).get("default", 0.8))
    
    def _content_match_score(self, item, platform_config):
        """计算内容匹配度得分"""
        if not platform_config:
            return 0.5  # 默认中等匹配度
            
        title = item.get("title", "").lower()
        platform_preferences = platform_config.get("content_preferences", [])
        
        # 如果平台没有配置偏好，返回默认分数
        if not platform_preferences:
            return 0.5
            
        # 计算标题与平台偏好的匹配度
        match_score = 0.0
        matched_preferences = []
        
        for preference in platform_preferences:
            preference_lower = preference.lower()
            # 完全匹配得分最高
            if preference_lower in title:
                match_score = max(match_score, 1.0)
                matched_preferences.append(preference)
            # 部分匹配得分适中
            else:
                preference_words = preference_lower.split()
                title_words = title.split()
                # 计算词汇重叠度
                overlap = len(set(preference_words) & set(title_words))
                if overlap > 0:
                    # 根据重叠词数量计算得分
                    partial_score = min(0.8, overlap * 0.2)
                    match_score = max(match_score, partial_score)
                    if partial_score > 0.3:  # 记录部分匹配的偏好
                        matched_preferences.append(preference)
        
        # 如果没有明显匹配，但平台偏好与标题有一些相关性，给予基础分数
        if match_score == 0.0:
            # 检查是否有间接相关性
            general_keywords = ["热点", "新闻", "事件", "话题", "最新", "热门"]
            if any(keyword in title for keyword in general_keywords):
                match_score = 0.3
            else:
                match_score = 0.1  # 最低基础分数
                
        return match_score
    
    def _score_item(self, item, cfg, platform_config=None):
        """对单个条目进行评分"""
        w = cfg.get("weights", DEFAULT_CONFIG["weights"])
        decay = cfg.get("decay_hours", DEFAULT_CONFIG["decay_hours"])
        
        # 基础评分维度
        hot = self._log1p_norm_hot(item.get("hot", 0))
        rec = self._recency_score(item.get("collected_at"), decay)
        title = self._title_keyword_score(item.get("title", ""))
        pboost = self._platform_weight(item.get("site_code"), cfg)
        
        # 内容匹配度（这是关键部分，不同平台应该有不同的匹配度）
        content_match = self._content_match_score(item, platform_config)
        
        # 如果有平台配置，使用平台特定的权重
        if platform_config and "scoring_weights" in platform_config:
            platform_weights = platform_config["scoring_weights"]
            # 使用平台特定权重计算最终得分
            final = (
                hot * platform_weights.get("hot", w["hot"]) +
                rec * platform_weights.get("recency", w["recency"]) +
                title * platform_weights.get("title", w["title"]) +
                content_match * platform_weights.get("content_match", 0.3) +
                pboost * platform_weights.get("platform", w["platform"])
            )
            
            # breakdown
            breakdown = {
                "hot": round(hot, 6),
                "recency": round(rec, 6),
                "title": round(title, 6),
                "content_match": round(content_match, 6),
                "platform": round(pboost, 6)
            }
        else:
            # 使用默认权重
            final = (w["hot"] * hot + w["recency"] * rec + w["title"] * title + w["platform"] * pboost)
            
            # breakdown
            breakdown = {
                "hot": round(hot, 6),
                "recency": round(rec, 6),
                "title": round(title, 6),
                "platform": round(pboost, 6)
            }
        
        return max(0.0, min(1.0, final)), breakdown

    def analyze_hotspot_suitability(self, hotspot: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """
        分析单个热点在指定平台的适用性 - 轻量级版本
        这是选材引擎的核心方法，用于评估一个热点内容是否适合在特定平台发布
        
        参数:
        - hotspot: 热点数据字典，包含标题、热度、分类等信息
        - platform: 目标平台名称
        
        返回:
        - 包含评分、推荐理由等信息的字典
        """
        
        # 获取目标平台的配置信息
        platform_config = self.platform_profiles.get(platform, {})
        
        # 使用默认配置进行评分
        cfg = DEFAULT_CONFIG.copy()
        
        # 对条目进行评分
        score, breakdown = self._score_item(hotspot, cfg, platform_config)
        
        # 生成内容角度和推荐策略
        content_angle = self._generate_content_angle(hotspot, platform_config)           # 内容创作角度
        recommended_strategy = self._recommend_strategy(hotspot, platform_config)        # 推荐的内容策略
        
        # 生成推荐理由
        reason = self._generate_recommendation_reason_simple(score, breakdown)
        
        # 返回分析结果
        return {
            "hotspot_id": hotspot.get("id"),         # 热点ID
            "title": hotspot.get("title"),                   # 标题
            "total_score": round(score, 2),            # 总分（保留两位小数）
            "content_angle": content_angle,                  # 内容角度
            "recommended_strategy": recommended_strategy,    # 推荐策略
            "reason": reason,                                # 推荐理由
            "detailed_scores": breakdown                     # 各项详细评分
        }
    
    def _generate_recommendation_reason_simple(self, score, breakdown):
        """生成简单的推荐理由"""
        reasons = []
        if breakdown.get("hot", 0) >= 0.7:
            reasons.append("热度很高")
        elif breakdown.get("hot", 0) >= 0.4:
            reasons.append("热度适中")
            
        if breakdown.get("recency", 0) >= 0.7:
            reasons.append("时效性很强")
        elif breakdown.get("recency", 0) >= 0.4:
            reasons.append("时效性良好")
            
        if breakdown.get("title", 0) >= 0.5:
            reasons.append("标题吸引力强")
            
        if breakdown.get("content_match", 0) >= 0.7:
            reasons.append("内容匹配度高")
        elif breakdown.get("content_match", 0) >= 0.4:
            reasons.append("内容较匹配")
            
        if breakdown.get("platform", 0) >= 0.8:
            reasons.append("平台匹配度高")
        elif breakdown.get("platform", 0) >= 0.5:
            reasons.append("平台适配性良好")
        
        if not reasons:
            reasons.append("综合表现良好")
            
        return "，".join(reasons)
    
    async def analyze_hotspots(self, hotspots: List[Dict[str, Any]], platforms: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        分析多个热点在指定平台的适用性
        这是一个异步方法，可以同时分析多个平台的热点适用性
        
        参数:
        - hotspots: 热点数据列表
        - platforms: 目标平台列表，如果为None则分析所有已配置平台
        
        返回:
        - 包含各平台分析结果的字典
        """
        
        # 如果没有指定平台，则使用所有已配置的平台
        if not platforms:
            platforms = list(self.platform_profiles.keys())
        
        results = {"selections": {}, "selection_criteria": {}}  # 初始化结果字典
        
        # 并行分析每个平台，提高处理效率
        tasks = []
        for platform in platforms:
            # 为每个平台创建分析任务
            task = self._analyze_platform_hotspots(hotspots, platform)
            tasks.append(task)
        
        # 等待所有平台分析完成
        platform_results = await asyncio.gather(*tasks)
        
        # 整理结果，将分析结果按平台组织
        for platform, platform_result in zip(platforms, platform_results):
            if platform_result:  # 过滤掉空结果
                results["selections"][platform] = platform_result
        
        # 添加选择标准元数据
        results["selection_criteria"] = {
            "strategy_used": "lightweight_scoring",      # 使用的策略
            "total_hotspots_analyzed": len(hotspots),   # 分析的热点总数
            "platforms_analyzed": platforms,            # 分析的平台列表
            "selection_timestamp": datetime.now().isoformat(),  # 分析时间戳
            "threshold_score": DEFAULT_CONFIG.get("threshold_score", 0.1)  # 选材阈值分数
        }
        
        return results
    
    async def _analyze_platform_hotspots(self, hotspots: List[Dict[str, Any]], platform: str) -> List[Dict[str, Any]]:
        """
        分析指定平台的热点适用性
        这个方法负责对特定平台分析所有热点的适用性，并进行筛选和排序
        
        参数:
        - hotspots: 热点数据列表
        - platform: 目标平台名称
        
        返回:
        - 按适用性得分排序的热点列表
        """
        
        platform_results = []  # 初始化结果列表
        cfg = DEFAULT_CONFIG.copy()
        threshold_score = cfg.get("threshold_score", 0.1)
        
        # 获取平台配置
        platform_config = self.platform_profiles.get(platform, {})
        
        # 遍历所有热点进行分析
        for hotspot in hotspots:
            # 使用线程池执行CPU密集型计算，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            
            # 对条目进行评分
            score, breakdown = self._score_item(hotspot, cfg, platform_config)
            
            # 阈值过滤
            if score >= threshold_score:
                # 构造结果对象
                result = {
                    "hotspot_id": hotspot.get("id"),
                    "title": hotspot.get("title"),
                    "url": hotspot.get("url"),
                    "site_code": hotspot.get("site_code"),
                    "total_score": round(score, 2),
                    "content_angle": self._generate_content_angle(hotspot, platform_config),
                    "recommended_strategy": self._recommend_strategy(hotspot, platform_config),
                    "reason": self._generate_recommendation_reason_simple(score, breakdown),
                    "detailed_scores": breakdown
                }
                platform_results.append(result)
        
        # 按得分降序排序，得分高的热点排在前面
        platform_results.sort(key=lambda x: x["total_score"], reverse=True)
        
        return platform_results
    
    def _generate_content_angle(self, hotspot: Dict[str, Any], platform_config: Dict[str, Any]) -> str:
        """
        生成内容角度
        根据热点内容和平台特点，为内容创作者提供创作角度建议
        
        参数:
        - hotspot: 热点数据
        - platform_config: 平台配置
        
        返回:
        - 内容角度建议字符串
        """
        
        title = hotspot.get("title", "")              # 热点标题
        platform_style = platform_config.get("content_style", "")  # 平台内容风格
        
        # 基于平台风格和热点内容生成角度
        if "情感" in platform_style:
            return f"个人视角：{title}的情感体验分享"        # 情感类平台建议
        elif "深度" in platform_style or "专业" in platform_style:
            return f"深度分析：{title}背后的逻辑与影响"     # 深度类平台建议
        elif "趋势" in platform_style:
            return f"趋势解读：{title}的发展趋势分析"       # 趋势类平台建议
        else:
            return f"热点解读：{title}的关键信息梳理"       # 通用热点解读
    
    def _recommend_strategy(self, hotspot: Dict[str, Any], platform_config: Dict[str, Any]) -> str:
        """
        推荐内容策略
        根据平台特点推荐合适的内容创作策略
        
        参数:
        - hotspot: 热点数据
        - platform_config: 平台配置
        
        返回:
        - 推荐策略名称
        """
        
        platform_name = platform_config.get("name", "")  # 平台名称
        
        # 基于平台推荐策略
        if "小红书" in platform_name:
            return "情感共鸣策略"      # 小红书适合情感类内容
        elif "知乎" in platform_name:
            return "知识分享策略"      # 知乎适合知识类内容
        elif "头条" in platform_name or "微博" in platform_name:
            return "趋势分析策略"      # 头条微博适合趋势类内容
        else:
            return "快速资讯策略"      # 其他平台适合快速资讯