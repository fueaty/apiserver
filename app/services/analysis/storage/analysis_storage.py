from typing import Dict, Any, List, Optional
import logging
from datetime import datetime
import json

from ....core.config import config_manager
from ....models.base import SessionLocal
from ....models.hotspot_analysis import HotspotAnalysisResult, HotspotClassification
from ....models.hotspot import Hotspot

logger = logging.getLogger(__name__)


class AnalysisStorage:
    """
    热点分析结果存储管理器，负责将分析结果和分类结果保存到数据库
    """
    
    def __init__(self):
        logger.info("初始化分析结果存储管理器")
        
        # 从配置中读取存储相关信息
        self.config = config_manager.get_config().get('feature_analysis', {})
        self.storage_config = self.config.get('storage', {})
        
        # 数据库会话
        self.db = None
    
    def _get_db_session(self):
        """
        获取数据库会话
        
        Returns:
            数据库会话对象
        """
        if not self.db:
            self.db = SessionLocal()
        return self.db
    
    def _close_db_session(self):
        """
        关闭数据库会话
        """
        if self.db:
            self.db.close()
            self.db = None
    
    async def save_analysis_result(self, hotspot: Dict[str, Any], analysis_result: Dict[str, Any]) -> Optional[HotspotAnalysisResult]:
        """
        保存热点分析结果
        
        Args:
            hotspot: 热点原始数据
            analysis_result: 分析结果
            
        Returns:
            保存的数据库模型实例
        """
        logger.info(f"保存热点分析结果: {hotspot.get('title')}")
        
        try:
            db = self._get_db_session()
            
            # 查找是否已存在该热点的分析结果
            existing = db.query(HotspotAnalysisResult).filter(
                HotspotAnalysisResult.hotspot_id == hotspot.get('id')
            ).first()
            
            # 准备数据
            analysis_data = {
                'hotspot_id': hotspot.get('id'),
                'title': hotspot.get('title'),
                'url': hotspot.get('url'),
                'raw_content': hotspot.get('extracted_content', ''),
                'analysis_result': json.dumps(analysis_result['analysis_result'], ensure_ascii=False),
                'entities': json.dumps(analysis_result.get('entities', []), ensure_ascii=False),
                'keywords': json.dumps(analysis_result.get('keywords', []), ensure_ascii=False),
                'sentiment_score': analysis_result.get('sentiment_score', 0),
                'title_attractiveness_score': analysis_result.get('title_attractiveness_score', 0),
                'processing_time_ms': analysis_result.get('processing_time_ms', 0),
                'analysis_time': datetime.now()
            }
            
            if existing:
                # 更新现有记录
                for key, value in analysis_data.items():
                    setattr(existing, key, value)
                existing.update_time = datetime.now()
                db.commit()
                db.refresh(existing)
                saved_result = existing
            else:
                # 创建新记录
                new_result = HotspotAnalysisResult(**analysis_data)
                db.add(new_result)
                db.commit()
                db.refresh(new_result)
                saved_result = new_result
            
            logger.info(f"热点分析结果保存成功: {hotspot.get('title')}")
            return saved_result
            
        except Exception as e:
            logger.error(f"保存热点分析结果失败: {str(e)}")
            if self.db:
                self.db.rollback()
            return None
    
    async def save_classification_result(self, hotspot: Dict[str, Any], classification_result: Dict[str, Any]) -> Optional[HotspotClassification]:
        """
        保存热点分类结果
        
        Args:
            hotspot: 热点原始数据
            classification_result: 分类结果
            
        Returns:
            保存的数据库模型实例
        """
        logger.info(f"保存热点分类结果: {hotspot.get('title')}")
        
        try:
            db = self._get_db_session()
            
            # 查找是否已存在该热点的分类结果
            existing = db.query(HotspotClassification).filter(
                HotspotClassification.hotspot_id == hotspot.get('id')
            ).first()
            
            # 准备数据
            classification_data = {
                'hotspot_id': hotspot.get('id'),
                'primary_category': classification_result.get('primary_category', '其他'),
                'secondary_category': classification_result.get('secondary_category', ''),
                'confidence': classification_result.get('confidence', 0.0),
                'classification_method': classification_result.get('classification_method', 'unknown'),
                'classification_time': datetime.fromisoformat(classification_result.get('classification_time')) if classification_result.get('classification_time') else datetime.now()
            }
            
            if existing:
                # 更新现有记录
                for key, value in classification_data.items():
                    setattr(existing, key, value)
                existing.update_time = datetime.now()
                db.commit()
                db.refresh(existing)
                saved_classification = existing
            else:
                # 创建新记录
                new_classification = HotspotClassification(**classification_data)
                db.add(new_classification)
                db.commit()
                db.refresh(new_classification)
                saved_classification = new_classification
            
            # 同时更新热点表中的分类信息（如果需要）
            self._update_hotspot_category(hotspot.get('id'), classification_data)
            
            logger.info(f"热点分类结果保存成功: {hotspot.get('title')} -> {classification_data['primary_category']}")
            return saved_classification
            
        except Exception as e:
            logger.error(f"保存热点分类结果失败: {str(e)}")
            if self.db:
                self.db.rollback()
            return None
    
    def _update_hotspot_category(self, hotspot_id: str, classification_data: Dict[str, Any]):
        """
        更新热点表中的分类信息
        
        Args:
            hotspot_id: 热点ID
            classification_data: 分类数据
        """
        try:
            db = self._get_db_session()
            hotspot = db.query(Hotspot).filter(Hotspot.id == hotspot_id).first()
            
            if hotspot:
                hotspot.primary_category = classification_data.get('primary_category', '其他')
                hotspot.secondary_category = classification_data.get('secondary_category', '')
                db.commit()
                logger.debug(f"热点表分类信息更新成功: {hotspot_id}")
        
        except Exception as e:
            logger.warning(f"更新热点表分类信息失败: {str(e)}")
            if self.db:
                self.db.rollback()
    
    async def save_complete_analysis(self, hotspot: Dict[str, Any], analysis_result: Dict[str, Any], 
                                   classification_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        保存完整的分析结果（分析+分类）
        
        Args:
            hotspot: 热点原始数据
            analysis_result: 分析结果
            classification_result: 分类结果
            
        Returns:
            保存结果字典
        """
        logger.info(f"保存完整分析结果: {hotspot.get('title')}")
        
        # 保存分析结果
        saved_analysis = await self.save_analysis_result(hotspot, analysis_result)
        
        # 保存分类结果
        saved_classification = await self.save_classification_result(hotspot, classification_result)
        
        # 组装返回结果
        result = {
            'hotspot_id': hotspot.get('id'),
            'analysis_saved': saved_analysis is not None,
            'classification_saved': saved_classification is not None,
            'total_success': saved_analysis is not None and saved_classification is not None
        }
        
        # 如果有任一部分保存失败，关闭数据库会话
        if not result['total_success']:
            self._close_db_session()
        
        return result
    
    async def batch_save_analysis_results(self, hotspots: List[Dict[str, Any]], 
                                        analysis_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量保存分析结果
        
        Args:
            hotspots: 热点列表
            analysis_results: 分析结果列表
            
        Returns:
            保存结果列表
        """
        logger.info(f"批量保存{len(hotspots)}个热点分析结果")
        
        results = []
        try:
            for i, hotspot in enumerate(hotspots):
                if i < len(analysis_results):
                    result = await self.save_analysis_result(hotspot, analysis_results[i])
                    results.append({
                        'hotspot_id': hotspot.get('id'),
                        'saved': result is not None
                    })
                else:
                    results.append({
                        'hotspot_id': hotspot.get('id'),
                        'saved': False,
                        'error': 'No analysis result provided'
                    })
            
            logger.info(f"批量保存完成，成功保存{sum(1 for r in results if r['saved'])}个分析结果")
            return results
            
        except Exception as e:
            logger.error(f"批量保存分析结果失败: {str(e)}")
            self._close_db_session()
            raise
    
    async def batch_save_classification_results(self, hotspots: List[Dict[str, Any]], 
                                              classification_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量保存分类结果
        
        Args:
            hotspots: 热点列表
            classification_results: 分类结果列表
            
        Returns:
            保存结果列表
        """
        logger.info(f"批量保存{len(hotspots)}个热点分类结果")
        
        results = []
        try:
            for i, hotspot in enumerate(hotspots):
                if i < len(classification_results):
                    result = await self.save_classification_result(hotspot, classification_results[i])
                    results.append({
                        'hotspot_id': hotspot.get('id'),
                        'saved': result is not None
                    })
                else:
                    results.append({
                        'hotspot_id': hotspot.get('id'),
                        'saved': False,
                        'error': 'No classification result provided'
                    })
            
            logger.info(f"批量保存完成，成功保存{sum(1 for r in results if r['saved'])}个分类结果")
            return results
            
        except Exception as e:
            logger.error(f"批量保存分类结果失败: {str(e)}")
            self._close_db_session()
            raise
    
    def get_analysis_result(self, hotspot_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定热点的分析结果
        
        Args:
            hotspot_id: 热点ID
            
        Returns:
            分析结果字典
        """
        try:
            db = self._get_db_session()
            result = db.query(HotspotAnalysisResult).filter(
                HotspotAnalysisResult.hotspot_id == hotspot_id
            ).first()
            
            if result:
                return {
                    'id': result.id,
                    'hotspot_id': result.hotspot_id,
                    'title': result.title,
                    'url': result.url,
                    'raw_content': result.raw_content,
                    'analysis_result': json.loads(result.analysis_result),
                    'entities': json.loads(result.entities),
                    'keywords': json.loads(result.keywords),
                    'sentiment_score': result.sentiment_score,
                    'title_attractiveness_score': result.title_attractiveness_score,
                    'processing_time_ms': result.processing_time_ms,
                    'analysis_time': result.analysis_time.isoformat(),
                    'update_time': result.update_time.isoformat() if result.update_time else None
                }
            
            return None
            
        except Exception as e:
            logger.error(f"获取分析结果失败: {str(e)}")
            self._close_db_session()
            return None
    
    def get_classification_result(self, hotspot_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定热点的分类结果
        
        Args:
            hotspot_id: 热点ID
            
        Returns:
            分类结果字典
        """
        try:
            db = self._get_db_session()
            result = db.query(HotspotClassification).filter(
                HotspotClassification.hotspot_id == hotspot_id
            ).first()
            
            if result:
                return {
                    'id': result.id,
                    'hotspot_id': result.hotspot_id,
                    'primary_category': result.primary_category,
                    'secondary_category': result.secondary_category,
                    'confidence': result.confidence,
                    'classification_method': result.classification_method,
                    'classification_time': result.classification_time.isoformat(),
                    'update_time': result.update_time.isoformat() if result.update_time else None
                }
            
            return None
            
        except Exception as e:
            logger.error(f"获取分类结果失败: {str(e)}")
            self._close_db_session()
            return None
    
    def get_category_statistics(self, days: int = 7) -> Dict[str, Dict[str, int]]:
        """
        获取分类统计信息
        
        Args:
            days: 统计天数
            
        Returns:
            统计字典，按主分类和子分类统计数量
        """
        try:
            db = self._get_db_session()
            
            # 计算起始日期
            from datetime import timedelta
            start_date = datetime.now() - timedelta(days=days)
            
            # 查询统计数据
            results = db.query(
                HotspotClassification.primary_category,
                HotspotClassification.secondary_category,
                db.func.count(HotspotClassification.id).label('count')
            ).filter(
                HotspotClassification.classification_time >= start_date
            ).group_by(
                HotspotClassification.primary_category,
                HotspotClassification.secondary_category
            ).all()
            
            # 构建统计结果
            statistics = {}
            for primary, secondary, count in results:
                if primary not in statistics:
                    statistics[primary] = {'total': 0, 'sub_categories': {}}
                
                statistics[primary]['total'] += count
                if secondary:
                    statistics[primary]['sub_categories'][secondary] = count
            
            return statistics
            
        except Exception as e:
            logger.error(f"获取分类统计失败: {str(e)}")
            self._close_db_session()
            return {}
    
    def __del__(self):
        """
        析构函数，确保数据库会话被关闭
        """
        self._close_db_session()