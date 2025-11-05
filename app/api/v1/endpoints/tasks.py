"""
异步任务管理API端点
提供任务提交、状态查询、结果获取等功能
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.endpoints.auth import verify_token
from app.tasks.collection_tasks import batch_collect_websites, scheduled_collection
from app.tasks.selection_tasks import batch_selection_analysis, platform_specific_selection
from app.tasks.publication_tasks import batch_publication, multi_platform_publication
from app.utils.logger import logger


router = APIRouter()


class TaskRequest(BaseModel):
    """任务请求基类"""
    task_type: str = Field(..., description="任务类型")
    parameters: Dict[str, Any] = Field(default={}, description="任务参数")
    priority: int = Field(default=5, description="任务优先级(1-10)")


class CollectionTaskRequest(TaskRequest):
    """采集任务请求"""
    task_type: str = "collection"
    site_codes: List[str] = Field(..., description="网站编码列表")
    date: Optional[str] = Field(None, description="采集日期")
    category: Optional[str] = Field(None, description="分类筛选")
    keyword: Optional[str] = Field(None, description="关键词筛选")


class SelectionTaskRequest(TaskRequest):
    """选材任务请求"""
    task_type: str = "selection"
    hotspots_data: List[Dict[str, Any]] = Field(..., description="热点数据列表")
    platforms: List[str] = Field(..., description="目标平台列表")
    selection_strategy: str = Field(default="platform_optimized", description="选材策略")


class PublicationTaskRequest(TaskRequest):
    """发布任务请求"""
    task_type: str = "publication"
    content_data: List[Dict[str, Any]] = Field(..., description="内容数据列表")
    platform_configs: List[Dict[str, Any]] = Field(..., description="平台配置列表")
    publication_strategy: str = Field(default="sequential", description="发布策略")


class TaskResponse(BaseModel):
    """任务响应"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    task_id: str = Field(..., description="任务ID")
    task_type: str = Field(..., description="任务类型")
    status: str = Field(..., description="任务状态")
    submitted_at: str = Field(..., description="提交时间")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    task_id: str = Field(..., description="任务ID")
    task_type: str = Field(..., description="任务类型")
    status: str = Field(..., description="任务状态")
    result: Optional[Dict[str, Any]] = Field(None, description="任务结果")
    submitted_at: str = Field(..., description="提交时间")
    completed_at: Optional[str] = Field(None, description="完成时间")
    progress: Optional[float] = Field(None, description="进度百分比")


@router.post("/submit", response_model=TaskResponse, summary="提交异步任务")
async def submit_task(
    request: TaskRequest,
    payload: dict = Depends(verify_token)
):
    """
    提交异步任务
    
    - **task_type**: 任务类型 (collection/selection/publication)
    - **parameters**: 任务参数
    - **priority**: 任务优先级
    
    返回: 任务提交结果，包含任务ID
    """
    try:
        client_id = payload.get("client_id", "unknown")
        logger.info(f"客户端 {client_id} 提交任务: {request.task_type}")
        
        # 根据任务类型分发任务
        if request.task_type == "collection":
            if not isinstance(request, CollectionTaskRequest):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="采集任务需要CollectionTaskRequest参数"
                )
            
            # 提交采集任务
            task = batch_collect_websites.apply_async(
                args=[
                    request.site_codes,
                    request.date,
                    request.category,
                    request.keyword
                ],
                priority=request.priority
            )
            
        elif request.task_type == "selection":
            if not isinstance(request, SelectionTaskRequest):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="选材任务需要SelectionTaskRequest参数"
                )
            
            # 提交选材任务
            task = batch_selection_analysis.apply_async(
                args=[
                    request.hotspots_data,
                    request.platforms,
                    request.selection_strategy
                ],
                priority=request.priority
            )
            
        elif request.task_type == "publication":
            if not isinstance(request, PublicationTaskRequest):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="发布任务需要PublicationTaskRequest参数"
                )
            
            # 提交发布任务
            task = batch_publication.apply_async(
                args=[
                    request.content_data,
                    request.platform_configs,
                    request.publication_strategy
                ],
                priority=request.priority
            )
            
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的任务类型: {request.task_type}"
            )
        
        logger.info(f"任务提交成功: {task.id}")
        
        return TaskResponse(
            code=200,
            message="任务提交成功",
            task_id=task.id,
            task_type=request.task_type,
            status="PENDING",
            submitted_at=task.date_done.isoformat() if task.date_done else ""
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"任务提交失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"任务提交失败: {str(e)}"
        )


@router.get("/status/{task_id}", response_model=TaskStatusResponse, summary="查询任务状态")
async def get_task_status(
    task_id: str,
    payload: dict = Depends(verify_token)
):
    """
    查询任务状态
    
    - **task_id**: 任务ID
    
    返回: 任务状态和结果
    """
    try:
        client_id = payload.get("client_id", "unknown")
        logger.info(f"客户端 {client_id} 查询任务状态: {task_id}")
        
        # 获取任务结果
        from app.core.celery_config import celery_app
        result = celery_app.AsyncResult(task_id)
        
        # 构建响应
        response_data = {
            "code": 200,
            "message": "success",
            "task_id": task_id,
            "task_type": "unknown",  # 实际实现中需要存储任务类型信息
            "status": result.status,
            "submitted_at": result.date_done.isoformat() if result.date_done else "",
            "completed_at": result.date_done.isoformat() if result.date_done else None,
            "progress": None
        }
        
        # 如果任务完成，添加结果
        if result.ready():
            response_data["result"] = result.result
            
        logger.info(f"任务状态查询成功: {task_id} - {result.status}")
        
        return TaskStatusResponse(**response_data)
        
    except Exception as e:
        logger.error(f"任务状态查询失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"任务状态查询失败: {str(e)}"
        )


@router.get("/metrics", summary="获取任务性能指标")
async def get_task_metrics(payload: dict = Depends(verify_token)):
    """
    获取任务性能指标
    
    返回: 任务性能统计信息
    """
    try:
        client_id = payload.get("client_id", "unknown")
        logger.info(f"客户端 {client_id} 获取任务性能指标")
        
        from app.utils.metrics import metrics_collector
        
        # 获取任务性能指标
        metrics = metrics_collector.get_comprehensive_metrics()
        
        return {
            "code": 200,
            "message": "success",
            "data": metrics
        }
        
    except Exception as e:
        logger.error(f"获取任务性能指标失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取任务性能指标失败: {str(e)}"
        )