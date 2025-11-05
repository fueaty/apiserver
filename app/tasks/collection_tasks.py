"""
采集相关异步任务
"""

import logging
from typing import Dict, Any, List
from celery import shared_task
from app.tasks.base import BaseTask
from app.services.collection.engine import CollectionEngine
from app.core.config import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=BaseTask)
def batch_collect_websites(
    self, 
    site_codes: List[str], 
    date: str = None,
    category: str = None,
    keyword: str = None
) -> Dict[str, Any]:
    """
    批量采集网站信息
    
    Args:
        site_codes: 网站编码列表
        date: 采集日期
        category: 分类筛选
        keyword: 关键词筛选
        
    Returns:
        采集结果
    """
    try:
        logger.info(f"开始批量采集任务: {site_codes}")
        
        collection_engine = CollectionEngine()
        
        # 构建采集参数
        params = {
            "date": date,
            "site_code": ",".join(site_codes),
            "category": category,
            "keyword": keyword,
            "client_id": "batch_task"
        }
        
        # 执行采集
        results = collection_engine.collect_websites(params)
        
        logger.info(f"批量采集完成: 共采集 {len(results)} 个站点的数据")
        
        return {
            "success": True,
            "data": results,
            "total_sites": len(site_codes),
            "collected_sites": len(results)
        }
        
    except Exception as e:
        logger.error(f"批量采集任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def scheduled_collection(
    self,
    schedule_id: str,
    site_codes: List[str],
    collection_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    定时采集任务
    
    Args:
        schedule_id: 调度ID
        site_codes: 网站编码列表
        collection_config: 采集配置
        
    Returns:
        采集结果
    """
    try:
        logger.info(f"执行定时采集任务 {schedule_id}")
        
        collection_engine = CollectionEngine()
        
        # 构建采集参数
        params = {
            "site_code": ",".join(site_codes),
            "client_id": f"schedule_{schedule_id}",
            **collection_config
        }
        
        # 执行采集
        results = collection_engine.collect_websites(params)
        
        logger.info(f"定时采集任务 {schedule_id} 完成: 共采集 {len(results)} 个站点的数据")
        
        return {
            "success": True,
            "schedule_id": schedule_id,
            "data": results,
            "total_sites": len(site_codes),
            "collected_sites": len(results)
        }
        
    except Exception as e:
        logger.error(f"定时采集任务 {schedule_id} 失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def test_collection_task(self, site_code: str) -> Dict[str, Any]:
    """
    测试采集任务
    
    Args:
        site_code: 网站编码
        
    Returns:
        测试结果
    """
    try:
        logger.info(f"执行测试采集任务: {site_code}")
        
        collection_engine = CollectionEngine()
        
        # 构建采集参数
        params = {
            "site_code": site_code,
            "client_id": "test_task"
        }
        
        # 执行采集
        results = collection_engine.collect_websites(params)
        
        logger.info(f"测试采集任务完成: {site_code}")
        
        return {
            "success": True,
            "site_code": site_code,
            "data": results,
            "status": "测试成功"
        }
        
    except Exception as e:
        logger.error(f"测试采集任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)