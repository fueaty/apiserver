from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from .feishu_data_loader import FeishuDataLoader
from .llm_processor import LLMProcessor
from ..content_extraction.content_extractor import ContentExtractor
from ...storage.analysis_storage import AnalysisStorage

logger = logging.getLogger(__name__)


class FeatureAnalyzer:
    """
    热点特征分析器，负责协调数据加载、内容提取和特征分析过程
    """
    
    def __init__(self):
        logger.info("初始化热点特征分析器")
        
        # 初始化各个组件
        self.feishu_data_loader = FeishuDataLoader()
        self.llm_processor = LLMProcessor()
        self.content_extractor = ContentExtractor()
        self.analysis_storage = AnalysisStorage()
    
    async def analyze_top_hotspots(self, date: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        分析排名靠前的热点特征
        
        Args:
            date: 日期过滤，格式YYYY-MM-DD，默认为当天
            limit: 返回的热点数量限制
            
        Returns:
            分析结果列表
        """
        logger.info(f"开始分析热点特征，日期: {date}, 数量: {limit}")
        
        try:
            # 步骤1: 从飞书表格获取热点数据
            logger.info("步骤1: 从飞书表格获取热点数据")
            hotspots = await self.feishu_data_loader.get_top_hotspots(date=date, limit=limit)
            
            if not hotspots:
                logger.warning(f"未获取到热点数据，日期: {date}")
                return []
            
            # 步骤2: 提取热点内容
            logger.info("步骤2: 提取热点内容")
            hotspots_with_content = await self._extract_hotspot_contents(hotspots)
            
            # 步骤3: 使用大模型分析特征
            logger.info("步骤3: 使用大模型分析特征")
            analysis_results = await self.llm_processor.batch_analyze_hotspots(hotspots_with_content)
            
            # 步骤4: 保存分析结果
            logger.info("步骤4: 保存分析结果")
            await self._save_analysis_results(analysis_results)
            
            logger.info(f"热点特征分析完成，共分析{len(analysis_results)}个热点")
            return analysis_results
            
        except Exception as e:
            logger.error(f"热点特征分析失败: {str(e)}")
            raise
    
    async def analyze_hotspot_by_id(self, hotspot_id: str) -> Dict[str, Any]:
        """
        根据ID分析单个热点
        
        Args:
            hotspot_id: 热点ID
            
        Returns:
            分析结果
        """
        logger.info(f"根据ID分析热点: {hotspot_id}")
        
        try:
            # 先尝试从存储中获取
            stored_result = await self.analysis_storage.get_analysis_result(hotspot_id)
            if stored_result:
                logger.info(f"使用缓存的分析结果: {hotspot_id}")
                return stored_result
            
            # 从飞书表格获取热点数据（需要实现根据ID查询的功能）
            # 这里简化处理，获取所有数据后过滤
            hotspots = await self.feishu_data_loader.get_top_hotspots(limit=100)
            target_hotspot = next((h for h in hotspots if h.get('id') == hotspot_id), None)
            
            if not target_hotspot:
                raise ValueError(f"未找到ID为{hotspot_id}的热点")
            
            # 提取内容
            hotspot_with_content = await self._extract_single_content(target_hotspot)
            
            # 分析特征
            analysis_result = await self.llm_processor.analyze_hotspot(hotspot_with_content)
            
            # 保存结果
            await self.analysis_storage.save_analysis_result(analysis_result)
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"分析单个热点失败: {str(e)}")
            raise
    
    async def analyze_hotspots_by_date_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        分析日期范围内的热点
        
        Args:
            start_date: 开始日期，格式YYYY-MM-DD
            end_date: 结束日期，格式YYYY-MM-DD
            
        Returns:
            分析结果列表
        """
        logger.info(f"分析日期范围[{start_date}至{end_date}]的热点")
        
        try:
            # 从飞书表格获取日期范围内的热点
            hotspots = await self.feishu_data_loader.get_hotspots_by_date_range(start_date, end_date)
            
            if not hotspots:
                logger.warning(f"日期范围内未获取到热点数据")
                return []
            
            # 提取内容
            hotspots_with_content = await self._extract_hotspot_contents(hotspots)
            
            # 分析特征
            analysis_results = await self.llm_processor.batch_analyze_hotspots(hotspots_with_content)
            
            # 保存结果
            await self._save_analysis_results(analysis_results)
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"分析日期范围热点失败: {str(e)}")
            raise
    
    async def _extract_hotspot_contents(self, hotspots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量提取热点内容
        
        Args:
            hotspots: 热点列表
            
        Returns:
            添加了内容的热点列表
        """
        results = []
        
        for hotspot in hotspots:
            try:
                # 提取单个热点的内容
                hotspot_with_content = await self._extract_single_content(hotspot)
                results.append(hotspot_with_content)
            except Exception as e:
                logger.error(f"提取热点内容失败: {hotspot.get('title')}, 错误: {str(e)}")
                # 添加错误标记但继续处理
                hotspot['content_extraction_error'] = str(e)
                results.append(hotspot)
        
        return results
    
    async def _extract_single_content(self, hotspot: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取单个热点的内容
        
        Args:
            hotspot: 热点数据
            
        Returns:
            添加了内容的热点数据
        """
        url = hotspot.get('url')
        if not url:
            logger.warning(f"热点URL为空: {hotspot.get('title')}")
            return hotspot
        
        try:
            # 使用内容提取器提取内容
            extracted_content = await self.content_extractor.extract_from_url(url)
            
            # 添加提取的内容到热点数据
            hotspot['extracted_content'] = extracted_content.get('content', '')
            hotspot['extracted_title'] = extracted_content.get('title', hotspot.get('title'))
            hotspot['extracted_summary'] = extracted_content.get('summary', '')
            hotspot['content_extraction_time'] = datetime.now().isoformat()
            
            # 更新摘要字段，用于大模型分析
            if extracted_content.get('summary'):
                hotspot['summary'] = extracted_content['summary']
            elif extracted_content.get('content'):
                # 如果没有摘要，使用内容的前200个字符
                hotspot['summary'] = extracted_content['content'][:200] + '...'
            
        except Exception as e:
            logger.error(f"提取URL内容失败: {url}, 错误: {str(e)}")
            # 如果提取失败，仍返回原始热点数据
            hotspot['content_extraction_error'] = str(e)
        
        return hotspot
    
    async def _save_analysis_results(self, analysis_results: List[Dict[str, Any]]):
        """
        保存分析结果
        
        Args:
            analysis_results: 分析结果列表
        """
        for result in analysis_results:
            try:
                await self.analysis_storage.save_analysis_result(result)
            except Exception as e:
                logger.error(f"保存分析结果失败: {result.get('hotspot_id')}, 错误: {str(e)}")
    
    async def analyze_single_hotspot(self, hotspot: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析单个热点（异步方法）
        
        Args:
            hotspot: 热点数据
            
        Returns:
            分析结果
        """
        logger.info(f"分析单个热点: {hotspot.get('title')}")
        
        # 提取内容
        hotspot_with_content = await self._extract_single_content(hotspot)
        
        # 使用大模型分析特征
        analysis_result = await self.llm_processor.analyze_hotspot(hotspot_with_content)
        
        # 保存结果
        await self.analysis_storage.save_analysis_result(analysis_result)
        
        return analysis_result
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取分析统计信息
        
        Returns:
            统计信息
        """
        return {
            'total_analyzed': self.analysis_storage.get_total_analyzed_count(),
            'today_analyzed': self.analysis_storage.get_today_analyzed_count(),
            'success_rate': self.analysis_storage.get_success_rate()
        }