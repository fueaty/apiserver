"""智能选材API端点"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.api.v1.endpoints.auth import verify_token
from app.services.selection.engine import SelectionEngine
from app.utils.hotspot_enrich import (
    assess_content_quality,
    calculate_hot_level,
    extract_keywords,
    parse_hot_value,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class HotspotItem(BaseModel):
    """热点数据项 - 增强版

    ⚠️ 字段命名兼容两套写法（这是本端点历史遗留的坑）：

    | 采集接口 / 选材引擎(canonical) | 早期选材接口的写法 |
    |---|---|
    | `id`            | `hotspot_id`  |
    | `hot`           | `hot_value`   |
    | `collected_at`  | `collect_time`|
    | `site_code`     | `source`      |

    选材引擎（`app/services/selection/engine.py`）内部统一按 **canonical** 读取
    （`item.get("hot")` / `item.get("collected_at")` / `item.get("site_code")` /
    `hotspot.get("id")`），而采集器输出的也正是 canonical 命名。

    历史实现只声明了右列的名字、却没做任何转换就丢给引擎，
    导致**热度（权重最大项）恒为 0、时效性与平台权重全部走默认值、输出的 hotspot_id 恒为 None**。

    这里用 `AliasChoices` 让两套命名都能收，再在调用引擎前统一转成 canonical。
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    hotspot_id: str = Field(
        ..., validation_alias=AliasChoices("hotspot_id", "id"), description="热点ID"
    )
    title: str = Field(..., description="热点标题")
    source: str = Field(
        default="", validation_alias=AliasChoices("source", "site_code"), description="来源平台"
    )
    platform: str = Field(default="", description="内容平台")
    hot_value: int = Field(
        default=0, validation_alias=AliasChoices("hot_value", "hot"), description="热度值"
    )
    hot_level: str = Field(default="", description="热度等级")
    rank: int = Field(default=0, description="排名")
    category: str = Field(default="", description="分类")
    keywords: List[str] = Field(default=[], description="关键词列表")
    collect_time: str = Field(
        ..., validation_alias=AliasChoices("collect_time", "collected_at"), description="采集时间"
    )
    publish_time: str = Field(default="", description="发布时间")
    summary: str = Field(default="", description="摘要内容")
    url: str = Field(default="", description="原文链接")
    content_quality: dict = Field(default={}, description="内容质量评估")
    original_data: dict = Field(default={}, description="原始数据")

    @field_validator("hot_value", mode="before")
    @classmethod
    def _coerce_hot_value(cls, v):
        """热度可能是 "12.3万" 这类带单位的字符串，统一转成整数。"""
        if v is None:
            return 0
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        return parse_hot_value(v)


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

    入参 `hotspots[]` 同时接受采集接口的 canonical 命名（id/hot/collected_at/site_code）
    与早期写法（hotspot_id/hot_value/collect_time/source）。
    """
    try:
        # 验证请求数据
        if not request.hotspots:
            raise HTTPException(status_code=400, detail="热点列表不能为空")

        hotspots_data = []
        enrich_map = {}  # hotspot_id -> 原始增强字段，供响应回填

        for hotspot in request.hotspots:
            # pydantic v2 用 model_dump（旧代码用的 .dict() 在 v2 已废弃）
            d = hotspot.model_dump()

            hot_value = d.get("hot_value") or 0
            title = d.get("title", "")

            # 补齐增强字段（原来这里调用了未导入的函数，会 NameError）
            if not d.get("hot_level"):
                d["hot_level"] = calculate_hot_level(hot_value)
            if not d.get("keywords"):
                d["keywords"] = extract_keywords(title)
            if not d.get("content_quality"):
                d["content_quality"] = assess_content_quality(title, hot_value)

            enrich_map[d["hotspot_id"]] = {
                "source": d.get("source") or "",
                "hot_level": d.get("hot_level") or "",
                "rank": d.get("rank", 0),
                "category": d.get("category", ""),
                "keywords": d.get("keywords") or [],
                "content_quality": d.get("content_quality") or {},
                "url": d.get("url", ""),
            }

            # ---- 转成引擎期望的 canonical 键 ----
            engine_item = dict(d)
            engine_item["id"] = d["hotspot_id"]
            engine_item["hot"] = hot_value
            engine_item["site_code"] = d.get("source") or ""
            engine_item["collected_at"] = d.get("collect_time") or ""
            hotspots_data.append(engine_item)

        # 调用选材引擎进行分析
        results = await selection_engine.analyze_hotspots(
            hotspots_data, request.platforms
        )

        # 按照飞书格式构建响应数据 - 返回selections数组
        selections_list = []

        # 将所有平台的选材结果合并到一个数组中
        for platform, selections in results["selections"].items():
            profile = selection_engine.platform_profiles.get(platform, {})
            platform_insights = {
                "target_audience": profile.get("target_audience", []),
                "content_style": profile.get("content_style", ""),
                "optimal_length": profile.get("optimal_length", ""),
                "best_post_times": profile.get("best_post_times", []),
            }

            for selection in selections:
                hid = selection.get("hotspot_id") or ""
                ex = enrich_map.get(hid, {})
                keyword_list = ex.get("keywords") or extract_keywords(
                    selection.get("title", "")
                )

                selections_list.append({
                    "fields": {
                        "platform": platform,
                        "hotspot_id": hid,
                        "title": selection.get("title", ""),
                        "url": ex.get("url") or selection.get("url", ""),
                        "source": ex.get("source") or selection.get("site_code") or "",
                        "category": ex.get("category", ""),
                        "hot_level": ex.get("hot_level") or "",
                        "rank": ex.get("rank", 0),
                        "suitability_score": selection.get("total_score", 0.0),
                        "content_angle": selection.get("content_angle", ""),
                        "recommended_strategy": selection.get("recommended_strategy", ""),
                        "reason": selection.get("reason", ""),
                        "detailed_scores": selection.get("detailed_scores", {}),
                        "platform_insights": platform_insights,
                        "content_quality": ex.get("content_quality") or {},
                        "keywords_analysis": {
                            "keywords": keyword_list,
                            "keyword_count": len(keyword_list),
                        },
                    }
                })

        criteria = results.get("selection_criteria", {})
        logger.info(
            "选材分析完成: 输入 %d 个热点，产出 %d 条选材结果，覆盖平台 %s",
            len(hotspots_data),
            len(selections_list),
            criteria.get("platforms_analyzed", []),
        )

        return SelectionResponse(
            code=200,
            message="success",
            data={
                "selections": selections_list,
                "selection_criteria": criteria,
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
                "best_post_times": config.get("best_post_times", []),
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
                "content_elements": strategy.get("content_elements", []),
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
