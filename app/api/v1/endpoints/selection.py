"""智能选材API端点"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.endpoints.auth import verify_token
from app.services.selection.engine import SelectionEngine

logger = logging.getLogger(__name__)

router = APIRouter()


class HotspotItem(BaseModel):
    """热点数据项 - 增强版"""
    hotspot_id: str = Field(..., description="热点ID")
    title: str = Field(..., description="热点标题")
    source: str = Field(..., description="来源平台")
    platform: str = Field(default="", description="内容平台")
    hot_value: int = Field(default=0, description="热度值")
    hot_level: str = Field(default="", description="热度等级")
    rank: int = Field(default=0, description="排名")
    category: str = Field(default="", description="分类")
    keywords: List[str] = Field(default=[], description="关键词列表")
    collect_time: str = Field(..., description="采集时间")
    publish_time: str = Field(default="", description="发布时间")
    summary: str = Field(default="", description="摘要内容")
    content_quality: dict = Field(default={}, description="内容质量评估")
    original_data: dict = Field(default={}, description="原始数据")


class SelectionRequest(BaseModel):
    """选材请求体"""
    hotspots: List[HotspotItem] = Field(..., description="热点列表")
    platforms: Optional[List[str]] = Field(default=None, description="目标平台列表")


class SelectionResult(BaseModel):
    """单个选材结果 - 增强版"""
    hotspot_id: str = Field(..., description="热点ID")
    title: str = Field(..., description="热点标题")
    source: str = Field(..., description="来源平台")
    hot_level: str = Field(..., description="热度等级")
    rank: int = Field(..., description="原始排名")
    suitability_score: float = Field(..., description="匹配度得分")
    content_angle: str = Field(..., description="内容角度")
    recommended_strategy: str = Field(..., description="推荐策略")
    reason: str = Field(..., description="推荐理由")
    detailed_scores: dict = Field(..., description="详细得分")
    platform_insights: dict = Field(..., description="平台洞察")
    content_quality: dict = Field(..., description="内容质量评估")
    keywords_analysis: dict = Field(..., description="关键词分析")


class SelectionCriteria(BaseModel):
    """选材标准 - 增强版"""
    strategy_used: str = Field(..., description="使用的策略")
    total_hotspots_analyzed: int = Field(..., description="分析的热点总数")
    platforms_analyzed: List[str] = Field(..., description="分析的平台列表")
    selection_timestamp: str = Field(..., description="选材时间戳")
    threshold_score: float = Field(..., description="阈值分数")
    data_optimization: str = Field(default="enhanced", description="数据优化级别")
    analysis_dimensions: List[str] = Field(default=[], description="分析维度")
    quality_filters: dict = Field(default={}, description="质量过滤标准")


class SelectionResponse(BaseModel):
    """选材响应体"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    data: dict = Field(..., description="选材结果数据")


# 创建选材引擎实例
selection_engine = SelectionEngine()


@router.post("/selection", response_model=SelectionResponse, tags=["selection"])
async def analyze_hotspots(
    request: SelectionRequest,
    payload: dict = Depends(verify_token)
):
    """
    智能选材分析接口 - 增强版
    
    分析热点内容与各平台的匹配度，返回平台差异化选材结果
    充分利用采集接口返回的增强数据格式，提供更精准的选材建议
    """
    try:
        # 验证请求数据
        if not request.hotspots:
            raise HTTPException(status_code=400, detail="热点列表不能为空")
        
        # 优化热点数据格式，充分利用增强字段
        hotspots_data = []
        for hotspot in request.hotspots:
            hotspot_dict = hotspot.dict()
            
            # 如果缺少增强字段，尝试从原始数据中提取
            if not hotspot_dict.get("hot_level") and hotspot_dict.get("hot_value"):
                hotspot_dict["hot_level"] = _calculate_hot_level(hotspot_dict["hot_value"])
            
            if not hotspot_dict.get("keywords") and hotspot_dict.get("title"):
                hotspot_dict["keywords"] = _extract_keywords(hotspot_dict["title"])
            
            if not hotspot_dict.get("content_quality"):
                hotspot_dict["content_quality"] = _assess_content_quality(
                    hotspot_dict.get("title", ""), 
                    hotspot_dict.get("hot_value", 0)
                )
            
            hotspots_data.append(hotspot_dict)
        
        # 调用选材引擎进行分析
        results = await selection_engine.analyze_hotspots(
            hotspots_data, request.platforms
        )
        
        # 按照飞书格式构建响应数据 - 返回selections数组
        selections_list = []
        
        # 将所有平台的选材结果合并到一个数组中
        for platform, selections in results["selections"].items():
            for selection in selections:
                # 按照飞书格式构建fields字段，包含platform字段
                selections_list.append({
                    "fields": {
                        "platform": platform,
                        "hotspot_id": selection.get("hotspot_id", ""),
                        "title": selection.get("title", ""),
                        "source": selection.get("source", ""),
                        "hot_level": selection.get("hot_level", ""),
                        "rank": selection.get("rank", 0),
                        "suitability_score": selection.get("total_score", 0.0),
                        "content_angle": selection.get("content_angle", ""),
                        "recommended_strategy": selection.get("recommended_strategy", ""),
                        "reason": selection.get("reason", ""),
                        "detailed_scores": selection.get("detailed_scores", {}),
                        "platform_insights": selection.get("platform_insights", {}),
                        "content_quality": selection.get("content_quality", {}),
                        "keywords_analysis": selection.get("keywords_analysis", {})
                    }
                })
        
        logger.info(f"选材分析完成: 分析 {len(hotspots_data)} 个热点，覆盖 {len(request.platforms or [])} 个平台，使用增强数据格式")
        
        return SelectionResponse(
            code=200,
            message="success",
            data={
                "selections": selections_list
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"选材分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"选材分析失败: {str(e)}")


@router.get("/selection/platforms", tags=["selection"])
async def get_supported_platforms(
    payload: dict = Depends(verify_token)
):
    """
    获取支持的平台列表
    
    返回当前配置中支持的所有平台及其选材规则
    """
    try:
        platforms_info = {}
        
        for platform, config in selection_engine.platform_profiles.items():
            platforms_info[platform] = {
                "name": config.get("name", platform),
                "target_audience": config.get("target_audience", []),
                "content_preferences": config.get("content_preferences", []),
                "content_style": config.get("content_style", ""),
                "optimal_length": config.get("optimal_length", ""),
                "best_post_times": config.get("best_post_times", [])
            }
        
        return {
            "code": 200,
            "message": "success",
            "data": {
                "platforms": platforms_info,
                "total_platforms": len(platforms_info)
            }
        }
        
    except Exception as e:
        logger.error(f"获取平台列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取平台列表失败: {str(e)}")


@router.get("/selection/strategies", tags=["selection"])
async def get_content_strategies(
    payload: dict = Depends(verify_token)
):
    """
    获取内容策略列表
    
    返回当前支持的所有内容策略及其适用平台
    """
    try:
        strategies_info = {}
        
        for strategy_id, strategy in selection_engine.content_strategies.items():
            strategies_info[strategy_id] = {
                "strategy_name": strategy.get("strategy_name", ""),
                "description": strategy.get("description", ""),
                "applicable_platforms": strategy.get("applicable_platforms", []),
                "content_elements": strategy.get("content_elements", [])
            }
        
        return {
            "code": 200,
            "message": "success",
            "data": {
                "strategies": strategies_info,
                "total_strategies": len(strategies_info)
            }
        }
        
    except Exception as e:
        logger.error(f"获取内容策略失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取内容策略失败: {str(e)}")