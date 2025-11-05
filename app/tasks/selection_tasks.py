"""
选材相关异步任务
"""

import logging
from typing import Dict, Any, List
from celery import shared_task
from app.tasks.base import BaseTask
from app.services.selection.engine import SelectionEngine
from app.core.config import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=BaseTask)
def batch_selection_analysis(
    self,
    hotspots_data: List[Dict[str, Any]],
    platforms: List[str],
    selection_strategy: str = "platform_optimized"
) -> Dict[str, Any]:
    """
    批量选材分析任务
    
    Args:
        hotspots_data: 热点数据列表
        platforms: 目标平台列表
        selection_strategy: 选材策略
        
    Returns:
        选材分析结果
    """
    try:
        logger.info(f"开始批量选材分析: {len(hotspots_data)} 个热点, {len(platforms)} 个平台")
        
        selection_engine = SelectionEngine()
        
        # 执行选材分析
        results = selection_engine.analyze_hotspots(
            hotspots_data, 
            platforms, 
            strategy=selection_strategy
        )
        
        logger.info(f"批量选材分析完成: 生成 {len(results.get('selections', []))} 个选材结果")
        
        return {
            "success": True,
            "data": results,
            "total_hotspots": len(hotspots_data),
            "total_platforms": len(platforms),
            "selections_count": len(results.get('selections', []))
        }
        
    except Exception as e:
        logger.error(f"批量选材分析任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def platform_specific_selection(
    self,
    hotspot_data: Dict[str, Any],
    platform: str,
    detailed_analysis: bool = True
) -> Dict[str, Any]:
    """
    平台特定选材分析
    
    Args:
        hotspot_data: 热点数据
        platform: 目标平台
        detailed_analysis: 是否进行详细分析
        
    Returns:
        平台特定选材结果
    """
    try:
        logger.info(f"执行平台特定选材分析: {platform}")
        
        selection_engine = SelectionEngine()
        
        # 执行平台特定分析
        result = selection_engine.analyze_single_hotspot(
            hotspot_data, 
            platform, 
            detailed_analysis=detailed_analysis
        )
        
        logger.info(f"平台特定选材分析完成: {platform}")
        
        return {
            "success": True,
            "platform": platform,
            "data": result,
            "analysis_level": "detailed" if detailed_analysis else "basic"
        }
        
    except Exception as e:
        logger.error(f"平台特定选材分析任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def content_strategy_generation(
    self,
    hotspot_data: Dict[str, Any],
    platform: str,
    strategy_type: str = "content_angle"
) -> Dict[str, Any]:
    """
    内容策略生成任务
    
    Args:
        hotspot_data: 热点数据
        platform: 目标平台
        strategy_type: 策略类型
        
    Returns:
        内容策略生成结果
    """
    try:
        logger.info(f"生成内容策略: {platform} - {strategy_type}")
        
        selection_engine = SelectionEngine()
        
        # 生成内容策略
        strategies = selection_engine.generate_content_strategies(
            hotspot_data, 
            platform, 
            strategy_type
        )
        
        logger.info(f"内容策略生成完成: 生成 {len(strategies)} 个策略")
        
        return {
            "success": True,
            "platform": platform,
            "strategy_type": strategy_type,
            "strategies": strategies,
            "strategies_count": len(strategies)
        }
        
    except Exception as e:
        logger.error(f"内容策略生成任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)


@shared_task(bind=True, base=BaseTask)
def selection_quality_assessment(
    self,
    selection_results: List[Dict[str, Any]],
    assessment_criteria: Dict[str, Any]
) -> Dict[str, Any]:
    """
    选材质量评估任务
    
    Args:
        selection_results: 选材结果列表
        assessment_criteria: 评估标准
        
    Returns:
        质量评估结果
    """
    try:
        logger.info(f"执行选材质量评估: {len(selection_results)} 个选材结果")
        
        selection_engine = SelectionEngine()
        
        # 执行质量评估
        assessments = selection_engine.assess_selection_quality(
            selection_results, 
            assessment_criteria
        )
        
        logger.info(f"选材质量评估完成: 评估 {len(assessments)} 个结果")
        
        return {
            "success": True,
            "assessments": assessments,
            "total_selections": len(selection_results),
            "assessment_criteria": assessment_criteria
        }
        
    except Exception as e:
        logger.error(f"选材质量评估任务失败: {e}")
        raise self.retry(countdown=settings.ASYNC_TASK_RETRY_DELAY, max_retries=settings.ASYNC_TASK_RETRY_COUNT)