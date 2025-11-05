#/root/apiserver/app/api/v1/endpoints/analysis.py
"""
发布效果分析API端点
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.endpoints.auth import verify_token
from app.services.analysis.analysis_service import AnalysisService
from app.utils.logger import logger


router = APIRouter()
analysis_service = AnalysisService()


class CollectRequest(BaseModel):
    """数据收集请求模型"""
    platform: str
    publication_id: str


@router.post("/collect", summary="收集发布数据")
async def collect_data(
    request: CollectRequest,
    payload: dict = Depends(verify_token)
):
    """
    收集指定发布文章的效果数据
    
    - **platform**: 平台标识
    - **publication_id**: 发布ID
    - 需要Authorization头: Bearer <token>
    
    返回: 数据收集结果
    """
    try:
        success = await analysis_service.collect_publication_data(request.platform, request.publication_id)
        if not success:
            raise HTTPException(status_code=500, detail="数据收集失败")
        
        return {"code": 200, "message": "success"}
        
    except Exception as e:
        logger.error(f"数据收集失败: {e}")
        raise HTTPException(status_code=500, detail=f"数据收集失败: {str(e)}")


@router.get("/report/{platform}/{publication_id}", summary="获取发布效果分析报告")
async def get_analysis_report(
    platform: str,
    publication_id: str,
    payload: dict = Depends(verify_token)
):
    """
    获取指定发布文章的效果分析报告
    
    - **platform**: 平台标识
    - **publication_id**: 发布ID
    - 需要Authorization头: Bearer <token>
    
    返回: 发布效果分析报告
    """
    try:
        report = await analysis_service.analyze_publication_performance(platform, publication_id)
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])
        
        return {"code": 200, "message": "success", "data": report}
        
    except Exception as e:
        logger.error(f"获取分析报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取分析报告失败: {str(e)}")
