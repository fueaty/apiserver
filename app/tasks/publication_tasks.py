"""
发布相关异步任务
"""

import logging
from typing import Dict, Any, List
from celery import shared_task
from app.tasks.base import BaseTask
from app.services.publication.manager import PublicationManager
from app.core.config import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=BaseTask)
def batch_publication(
    self,
    content_data: List[Dict[str, Any]],
    platform_configs: List[Dict[str, Any]],
    publication_strategy: str = "sequential"
) -> Dict[str, Any]:
    """
    批量发布任务
    
    Args:
        content_data: 内容数据列表
        platform_configs: 平台配置列表
        publication_strategy: 发布策略
        
    Returns:
        发布结果
    """
    try:
        logger.info(f"开始批量发布任务: {len(content_data)} 个内容, {len(platform_configs)} 个平台")
        
        publication_manager = PublicationManager()
        
        # 执行批量发布
        results = publication_manager.batch_publish(
            content_data, 
            platform_configs, 
            strategy=publication_strategy
        )
        
        logger.info(f"批量发布任务完成: 成功发布 {len([r for r in results if r.get('success')])} 个内容")
        
        return {
            "success": True,
            "data": results,
            "total_content": len(content_data),
            "total_platforms": len(platform_configs),
            "successful_publications": len([r for r in results if r.get('success')])
        }
        
    except Exception as e:
        logger.error(f"批量发布任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def multi_platform_publication(
    self,
    content_data: Dict[str, Any],
    platforms: List[str],
    platform_credentials: Dict[str, Dict[str, str]]
) -> Dict[str, Any]:
    """
    多平台发布任务
    
    Args:
        content_data: 内容数据
        platforms: 目标平台列表
        platform_credentials: 平台认证信息
        
    Returns:
        多平台发布结果
    """
    try:
        logger.info(f"执行多平台发布任务: {len(platforms)} 个平台")
        
        publication_manager = PublicationManager()
        
        # 执行多平台发布
        results = {}
        for platform in platforms:
            try:
                result = publication_manager.publish_to_platform(
                    content_data, 
                    platform, 
                    platform_credentials.get(platform, {})
                )
                results[platform] = result
                logger.info(f"平台 {platform} 发布完成")
            except Exception as e:
                logger.error(f"平台 {platform} 发布失败: {e}")
                results[platform] = {"success": False, "error": str(e)}
        
        logger.info(f"多平台发布任务完成: 成功发布 {len([r for r in results.values() if r.get('success')])} 个平台")
        
        return {
            "success": True,
            "data": results,
            "total_platforms": len(platforms),
            "successful_platforms": len([r for r in results.values() if r.get('success')])
        }
        
    except Exception as e:
        logger.error(f"多平台发布任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TRIES_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def scheduled_publication(
    self,
    schedule_id: str,
    content_data: Dict[str, Any],
    platform_config: Dict[str, Any],
    publish_time: str
) -> Dict[str, Any]:
    """
    定时发布任务
    
    Args:
        schedule_id: 调度ID
        content_data: 内容数据
        platform_config: 平台配置
        publish_time: 发布时间
        
    Returns:
        定时发布结果
    """
    try:
        logger.info(f"执行定时发布任务 {schedule_id}: 计划发布时间 {publish_time}")
        
        publication_manager = PublicationManager()
        
        # 执行定时发布
        result = publication_manager.scheduled_publish(
            content_data, 
            platform_config, 
            publish_time
        )
        
        logger.info(f"定时发布任务 {schedule_id} 完成")
        
        return {
            "success": True,
            "schedule_id": schedule_id,
            "publish_time": publish_time,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"定时发布任务 {schedule_id} 失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def publication_status_check(
    self,
    task_ids: List[str],
    check_type: str = "publication"
) -> Dict[str, Any]:
    """
    发布状态检查任务
    
    Args:
        task_ids: 任务ID列表
        check_type: 检查类型
        
    Returns:
        状态检查结果
    """
    try:
        logger.info(f"执行发布状态检查: {len(task_ids)} 个任务")
        
        publication_manager = PublicationManager()
        
        # 检查发布状态
        status_results = publication_manager.check_publication_status(
            task_ids, 
            check_type
        )
        
        logger.info(f"发布状态检查完成: 检查 {len(status_results)} 个任务")
        
        return {
            "success": True,
            "data": status_results,
            "total_tasks": len(task_ids),
            "check_type": check_type
        }
        
    except Exception as e:
        logger.error(f"发布状态检查任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def test_publication_task(self, platform: str, test_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    测试发布任务
    
    Args:
        platform: 目标平台
        test_content: 测试内容
        
    Returns:
        测试发布结果
    """
    try:
        logger.info(f"执行测试发布任务: {platform}")
        
        publication_manager = PublicationManager()
        
        # 执行测试发布
        result = publication_manager.test_publish(
            test_content, 
            platform, 
            {}
        )
        
        logger.info(f"测试发布任务完成: {platform}")
        
        return {
            "success": True,
            "platform": platform,
            "data": result,
            "status": "测试成功"
        }
        
    except Exception as e:
        logger.error(f"测试发布任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)