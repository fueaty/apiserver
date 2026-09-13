# -*- coding: utf-8 -*-
"""ai_insights 生成与写入 API 端点（需求③）

- ``POST /analysis/insights/generate``  ：从 headlines 生成深度内容并写入 ai_insights（P0）
- ``GET  /analysis/insights/preflight`` ：返回 LLM 配置状态 + ai_insights 线上表结构是否一致（P1）

约定：
  - record_ids 与 urls 均空 → 400；headlines 记录全不存在 → 404；部分成功 → 200。
  - 响应统一 ``{"code","message","data"}``；鉴权统一 ``Depends(verify_token)``。
  - 服务层依赖延迟构造，便于端点测试注入桩。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.endpoints.auth import verify_token
from app.utils.logger import logger


router = APIRouter()


# ---------------------------------------------------------------------------
# 请求模型（Pydantic v2）
# ---------------------------------------------------------------------------
class LLMOverride(BaseModel):
    provider: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class InsightsGenerateRequest(BaseModel):
    record_ids: Optional[List[str]] = None    # 二选一
    urls: Optional[List[str]] = None
    generate: Optional[List[str]] = None      # 缺省=全部可生成字段
    llm: Optional[LLMOverride] = None         # 本次调用覆盖默认
    dry_run: bool = False
    write: bool = True


# ---------------------------------------------------------------------------
# 依赖构造（延迟 import / 可被测试替换）
# ---------------------------------------------------------------------------
def _get_service():
    from app.services.analysis.insights_service import InsightsService
    return InsightsService()


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@router.post("/insights/generate", summary="生成 ai_insights 深度内容并写入")
async def generate_insights(request: InsightsGenerateRequest, payload: dict = Depends(verify_token)):
    if not request.record_ids and not request.urls:
        raise HTTPException(
            status_code=400,
            detail={"code": 400, "message": "record_ids 与 urls 至少提供一个", "data": None},
        )

    from app.services.analysis.insights_service import HEADLINE_NOT_FOUND

    service = _get_service()
    data = await service.generate(request.model_dump())

    results = data.get("results", []) or []
    # headlines 记录全不存在 → 404
    if results and all(r.get("error_code") == HEADLINE_NOT_FOUND for r in results):
        raise HTTPException(
            status_code=404,
            detail={"code": 404, "message": "headlines 记录全不存在", "data": data},
        )

    return {"code": 200, "message": "success", "data": data}


@router.get("/insights/preflight", summary="ai_insights 生成前置检查")
async def insights_preflight(payload: dict = Depends(verify_token)):
    service = _get_service()
    data = await service.preflight()
    return {"code": 200, "message": "success", "data": data}
