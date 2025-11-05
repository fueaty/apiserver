"""
内容发布API端点
提供多平台内容发布功能
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.publication.manager import PublicationManager
from app.api.v1.endpoints.auth import verify_token
from app.utils.logger import logger
from app.services.feishu.feishu_service import FeishuService


router = APIRouter()
publication_manager = PublicationManager()


class PublicationRequest(BaseModel):
    """发布请求模型"""
    platform: str
    platform_credentials: dict
    content: dict


@router.post("/", summary="发布内容到指定平台")
async def publish_content(
    request: PublicationRequest,
    payload: dict = Depends(verify_token)
):
    """
    发布内容到指定平台
    
    - **platform**: 目标平台标识
    - **platform_credentials**: 平台认证信息
    - **content**: 发布内容
    - 需要Authorization头: Bearer <token>
    
    返回: 发布结果
    """
    try:
        # 构建发布请求数据
        request_data = {
            "platform": request.platform,
            "platform_credentials": request.platform_credentials,
            "content": request.content,
            "client_id": payload.get("client_id")
        }
        
        logger.info(f"开始发布任务，客户端: {payload.get('client_id')}, 平台: {request.platform}")
        
        # 执行发布
        result = await publication_manager.publish(request_data)
        
        logger.info(f"发布任务完成，平台: {request.platform}, 状态: {'成功' if result.get('code') == 200 else '失败'}")
        
        # 如果发布成功，将结果存储到飞书表格
        if result.get("code") == 200:
            try:
                feishu_service = FeishuService()
                sheet_data = {
                    "platform": request.platform,
                    "client_id": payload.get("client_id"),
                    "content_title": request.content.get("title", ""),
                    "status": "success",
                    "timestamp": result.get("data", {}).get("timestamp", ""),
                    "publish_url": result.get("data", {}).get("url", "")
                }
                await feishu_service.append_to_sheet(sheet_data)
                logger.info(f"已将发布结果写入飞书表格: 平台={request.platform}, 标题={request.content.get('title', '')}")
            except Exception as e:
                logger.error(f"写入飞书表格失败: {str(e)}", exc_info=True)
                # 不中断主流程，继续返回发布结果
        
        return result
        
    except Exception as e:
        logger.error(f"发布任务失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500201,
                "message": f"发布失败: {str(e)}",
                "data": None
            }
        )


@router.get("/platforms", summary="获取可用发布平台列表")
async def get_available_platforms(payload: dict = Depends(verify_token)):
    """
    获取当前可用的发布平台列表
    
    - 需要Authorization头: Bearer <token>
    - 返回: 平台配置信息
    """
    try:
        platforms_config = publication_manager.get_available_platforms()
        
        return {
            "code": 200,
            "message": "success",
            "data": {
                "platforms": platforms_config,
                "total": len(platforms_config)
            }
        }
        
    except Exception as e:
        logger.error(f"获取平台列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500202,
                "message": f"获取平台列表失败: {str(e)}",
                "data": None
            }
        )