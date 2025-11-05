from typing import Dict, Any, List, Tuple, Optional
import logging
from datetime import datetime

from ....core.config import config_manager

logger = logging.getLogger(__name__)


class HotspotClassifier:
    """
    热点分类器，负责对热点进行分类，支持多级分类体系
    使用大模型进行文本分类，并结合规则进行优化
    """
    
    def __init__(self):
        logger.info("初始化热点分类器")
        
        # 从配置中读取分类相关信息
        self.config = config_manager.get_config().get('feature_analysis', {})
        self.classification_config = self.config.get('classification', {})
        
        # 预定义的分类体系
        self.category_system = self._load_category_system()
        
        # 分类规则
        self.rules = self._load_classification_rules()
    
    def _load_category_system(self) -> Dict[str, List[str]]:
        """
        加载分类体系
        
        Returns:
            分类体系字典，key为主分类，value为子分类列表
        """
        # 默认分类体系
        default_categories = {
            '科技': ['人工智能', '互联网', '通信', '硬件', '软件', '区块链', '元宇宙', '其他科技'],
            '财经': ['股票', '基金', '房地产', '数字货币', '宏观经济', '企业财报', '其他财经'],
            '社会': ['民生', '教育', '医疗', '就业', '环保', '公益', '其他社会'],
            '娱乐': ['电影', '音乐', '综艺', '明星', '游戏', '动漫', '其他娱乐'],
            '体育': ['足球', '篮球', '网球', '奥运会', '亚运会', '电竞', '其他体育'],
            '国际': ['政治', '军事', '外交', '冲突', '合作', '其他国际'],
            '健康': ['养生', '减肥', '运动', '心理健康', '疾病预防', '其他健康'],
            '文化': ['文学', '历史', '艺术', '出版', '传统文化', '其他文化'],
            '其他': []
        }
        
        # 从配置中获取自定义分类体系
        config_categories = self.classification_config.get('category_system', {})
        
        # 合并默认分类和配置分类
        if config_categories:
            return config_categories
        
        return default_categories
    
    def _load_classification_rules(self) -> List[Dict[str, Any]]:
        """
        加载分类规则
        
        Returns:
            规则列表
        """
        # 默认规则
        default_rules = [
            {'keywords': ['AI', '人工智能', '大模型', '机器学习', '深度学习'], 'category': '科技', 'sub_category': '人工智能', 'priority': 10},
            {'keywords': ['股市', '股票', '股价', '市值'], 'category': '财经', 'sub_category': '股票', 'priority': 8},
            {'keywords': ['比特币', '加密货币', '区块链'], 'category': '财经', 'sub_category': '数字货币', 'priority': 7},
            {'keywords': ['新冠', '疫情', '疫苗', '核酸'], 'category': '健康', 'sub_category': '疾病预防', 'priority': 9},
            {'keywords': ['足球', '世界杯', '英超', '欧冠'], 'category': '体育', 'sub_category': '足球', 'priority': 8},
            {'keywords': ['篮球', 'NBA', 'CBA'], 'category': '体育', 'sub_category': '篮球', 'priority': 8},
        ]
        
        # 从配置中获取自定义规则
        config_rules = self.classification_config.get('rules', [])
        
        # 合并规则
        if config_rules:
            return config_rules + default_rules
        
        return default_rules
    
    async def classify_hotspot(self, hotspot: Dict[str, Any], analysis_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        对单个热点进行分类
        
        Args:
            hotspot: 热点数据
            analysis_result: 预先生成的分析结果（可选）
            
        Returns:
            分类结果
        """
        logger.info(f"对热点进行分类: {hotspot.get('title')}")
        
        try:
            # 步骤1: 先应用规则分类
            rule_category, rule_sub_category = self._apply_rules(hotspot)
            
            # 步骤2: 如果规则分类结果不够准确，使用大模型分类
            final_category, final_sub_category = await self._enhance_with_llm(
                hotspot, 
                rule_category, 
                rule_sub_category,
                analysis_result
            )
            
            # 步骤3: 验证和优化分类结果
            validated_category, validated_sub_category = self._validate_and_optimize(
                final_category, 
                final_sub_category
            )
            
            # 构建分类结果
            classification_result = {
                'hotspot_id': hotspot.get('id'),
                'primary_category': validated_category,
                'secondary_category': validated_sub_category,
                'confidence': self._calculate_confidence(validated_category, validated_sub_category, rule_category),
                'classification_method': self._determine_classification_method(rule_category, final_category),
                'classification_time': datetime.now().isoformat()
            }
            
            logger.info(f"热点分类完成: {hotspot.get('title')} -> {validated_category}/{validated_sub_category}")
            return classification_result
            
        except Exception as e:
            logger.error(f"热点分类失败: {str(e)}")
            # 返回默认分类
            return {
                'hotspot_id': hotspot.get('id'),
                'primary_category': '其他',
                'secondary_category': '',
                'confidence': 0.1,
                'classification_method': 'default',
                'classification_time': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def _apply_rules(self, hotspot: Dict[str, Any]) -> Tuple[str, str]:
        """
        应用规则进行初步分类
        
        Args:
            hotspot: 热点数据
            
        Returns:
            (主分类, 子分类) 元组
        """
        # 提取文本内容用于匹配
        text_to_match = ' '.join([
            hotspot.get('title', ''),
            hotspot.get('summary', ''),
            hotspot.get('extracted_content', '')[:500]  # 只取前500字符
        ]).lower()
        
        # 存储匹配到的规则
        matched_rules = []
        
        # 遍历规则
        for rule in self.rules:
            keywords = rule.get('keywords', [])
            for keyword in keywords:
                if keyword.lower() in text_to_match:
                    matched_rules.append(rule)
                    break
        
        # 如果有匹配的规则，按照优先级排序并取最高优先级的
        if matched_rules:
            # 按优先级排序（优先级数字越小越优先）
            matched_rules.sort(key=lambda r: r.get('priority', 5))
            best_rule = matched_rules[0]
            
            logger.debug(f"应用规则分类: {best_rule.get('category')}/{best_rule.get('sub_category')}")
            return best_rule.get('category'), best_rule.get('sub_category')
        
        # 没有匹配的规则
        return '', ''
    
    async def _enhance_with_llm(self, hotspot: Dict[str, Any], initial_category: str, initial_sub_category: str, 
                              analysis_result: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """
        使用大模型增强分类结果
        
        Args:
            hotspot: 热点数据
            initial_category: 初始主分类
            initial_sub_category: 初始子分类
            analysis_result: 预先生成的分析结果
            
        Returns:
            增强后的(主分类, 子分类) 元组
        """
        # 如果已有分析结果且包含分类信息，优先使用
        if analysis_result and 'analysis_result' in analysis_result:
            llm_result = analysis_result['analysis_result']
            if 'topic_category' in llm_result:
                category = llm_result['topic_category']
                sub_category = llm_result.get('sub_category', '')
                
                # 验证分类是否在分类体系中
                if category in self.category_system:
                    # 如果子分类不在对应主分类的子分类列表中，设为空
                    if sub_category and sub_category not in self.category_system[category]:
                        sub_category = ''
                    return category, sub_category
        
        # 这里应该调用大模型进行分类
        # 由于我们已经在LLMProcessor中进行了分类，这里直接使用规则结果
        # 在实际应用中，这里可以实现更复杂的大模型分类逻辑
        
        return initial_category or '其他', initial_sub_category or ''
    
    def _validate_and_optimize(self, category: str, sub_category: str) -> Tuple[str, str]:
        """
        验证和优化分类结果
        
        Args:
            category: 主分类
            sub_category: 子分类
            
        Returns:
            优化后的(主分类, 子分类) 元组
        """
        # 验证主分类
        if category not in self.category_system:
            logger.warning(f"无效的主分类: {category}，使用默认分类")
            return '其他', ''
        
        # 验证子分类
        if sub_category:
            # 检查子分类是否属于对应的主分类
            if sub_category not in self.category_system[category]:
                logger.warning(f"子分类{sub_category}不属于主分类{category}，移除子分类")
                return category, ''
        
        return category, sub_category
    
    def _calculate_confidence(self, final_category: str, final_sub_category: str, rule_category: str) -> float:
        """
        计算分类置信度
        
        Args:
            final_category: 最终主分类
            final_sub_category: 最终子分类
            rule_category: 规则分类的主分类
            
        Returns:
            置信度值 (0-1)
        """
        # 基础置信度
        base_confidence = 0.6
        
        # 如果规则和最终分类一致，提高置信度
        if rule_category == final_category:
            base_confidence += 0.2
        
        # 如果有子分类，提高置信度
        if final_sub_category:
            base_confidence += 0.1
        
        # 如果是默认分类，降低置信度
        if final_category == '其他':
            base_confidence = 0.3
        
        # 确保在0-1范围内
        return min(1.0, max(0.1, base_confidence))
    
    def _determine_classification_method(self, rule_category: str, final_category: str) -> str:
        """
        确定分类方法
        
        Args:
            rule_category: 规则分类的主分类
            final_category: 最终主分类
            
        Returns:
            分类方法字符串
        """
        if rule_category and rule_category == final_category:
            return 'rule'
        elif rule_category:
            return 'rule_enhanced'
        else:
            return 'llm'
    
    async def batch_classify(self, hotspots: List[Dict[str, Any]], analysis_results: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        批量分类热点
        
        Args:
            hotspots: 热点列表
            analysis_results: 对应的分析结果列表（可选）
            
        Returns:
            分类结果列表
        """
        logger.info(f"开始批量分类{len(hotspots)}个热点")
        
        classification_results = []
        
        for i, hotspot in enumerate(hotspots):
            # 获取对应的分析结果
            analysis_result = None
            if analysis_results and i < len(analysis_results):
                analysis_result = analysis_results[i]
            
            # 分类
            result = await self.classify_hotspot(hotspot, analysis_result)
            classification_results.append(result)
        
        logger.info(f"批量分类完成，成功分类{len(classification_results)}个热点")
        return classification_results
    
    def get_category_statistics(self, classification_results: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        获取分类统计信息
        
        Args:
            classification_results: 分类结果列表
            
        Returns:
            统计字典，key为分类，value为数量
        """
        stats = {}
        
        for result in classification_results:
            category = result.get('primary_category', '其他')
            stats[category] = stats.get(category, 0) + 1
        
        return stats