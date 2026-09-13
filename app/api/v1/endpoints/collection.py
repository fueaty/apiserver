"""
网站信息采集API端点
提供实时网站内容采集功能
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
import re

from app.services.collection.engine import CollectionEngine
from app.api.v1.endpoints.auth import verify_token
from app.utils.logger import logger
from app.utils.hotspot_enrich import (
    assess_content_quality,
    calculate_hot_level,
    categorize_content,
    extract_keywords,
    generate_summary,
)


router = APIRouter()
collection_engine = CollectionEngine()


@router.get("/", summary="采集网站信息")
async def collect_website_info(
    date: Optional[str] = Query(None, description="采集日期(YYYY-MM-DD)"),
    site_code: Optional[str] = Query(None, description="网站编码(逗号分隔)"),
    category: Optional[str] = Query(None, description="分类筛选"),
    keyword: Optional[str] = Query(None, description="关键词筛选"),
    payload: dict = Depends(verify_token)
):
    """
    采集指定网站的信息
    
    - **date**: 采集日期，格式YYYY-MM-DD
    - **site_code**: 网站编码，多个用逗号分隔
    - **category**: 内容分类筛选
    - **keyword**: 关键词筛选
    - 需要Authorization头: Bearer <token>
    
    返回: 结构化的采集结果，格式优化为选材引擎可直接使用
    """
    try:
        # 构建采集参数
        params = {
            "date": date,
            "site_code": site_code,
            "category": category,
            "keyword": keyword,
            "client_id": payload.get("client_id")
        }
        
        logger.info(f"开始采集任务，客户端: {payload.get('client_id')}, 参数: {params}")
        
        # 执行采集
        results = await collection_engine.collect(params)
        
        # 过滤空结果并优化数据格式
        optimized_results = []
        for result in results:
            if result and result.get("news"):
                # 优化数据格式，便于选材引擎直接使用
                optimized_result = {
                    "site_code": result["site_code"],
                    "collect_time": result["collect_time"],
                    "data_count": result["data_count"],
                    "news": []
                }
                
                # 转换新闻数据格式，增加字段处理
                for news_item in result["news"]:
                    # 提取fields中的字段
                    fields = news_item.get("fields", {})
                    
                    # 生成标准化的热点ID
                    hotspot_id = f"{result['site_code']}_{fields.get('id', 'unknown')}_{fields.get('date', '').replace(' ', '_').replace(':', '')}"
                    
                    # 计算热度等级
                    hot_value = int(fields.get("hot", 0)) if fields.get("hot") else 0
                    hot_level = calculate_hot_level(hot_value)
                    
                    # 提取关键词和分类
                    title = fields.get("title", "")
                    keywords = extract_keywords(title)
                    content_category = categorize_content(title, category)
                    
                    # 按照飞书格式返回，包含fields字段
                    optimized_news = {
                        "fields": {
                            "hotspot_id": hotspot_id,
                            "title": title,
                            "source": result["site_code"],
                            "platform": fields.get("platform", result["site_code"]),
                            "hot_value": hot_value,
                            "hot_level": hot_level,
                            "rank": int(fields.get("rank", 0)) if fields.get("rank") else 0,
                            "url": fields.get("url", ""),
                            "publish_time": fields.get("date", ""),
                            "category": content_category,
                            "keywords": keywords,
                            "collect_time": result["collect_time"],
                            "summary": generate_summary(title, hot_value, int(fields.get("rank", 0)) if fields.get("rank") else 0),
                            "content_quality": assess_content_quality(title, hot_value)
                        }
                    }
                    optimized_result["news"].append(optimized_news)
                
                optimized_results.append(optimized_result)
        
        logger.info(f"采集任务完成，共采集 {len(optimized_results)} 个站点，{sum(len(r['news']) for r in optimized_results)} 条新闻")
        
        return {
            "code": 200,
            "message": "success",
            "data": optimized_results
        }
        
    except Exception as e:
        logger.error(f"采集任务失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500101,
                "message": f"采集失败: {str(e)}",
                "data": None
            }
        )


@router.get("/sites", summary="获取可用站点列表")
async def get_available_sites(payload: dict = Depends(verify_token)):
    """
    获取当前可用的采集站点列表
    
    - 需要Authorization头: Bearer <token>
    - 返回: 站点配置信息
    """
    try:
        sites_config = collection_engine.get_available_sites()
        
        return {
            "code": 200,
            "message": "success",
            "data": {
                "sites": sites_config,
                "total": len(sites_config)
            }
        }
        
    except Exception as e:
        logger.error(f"获取站点列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500102,
                "message": f"获取站点列表失败: {str(e)}",
                "data": None
            }
        )
