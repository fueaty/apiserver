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
                    hot_level = _calculate_hot_level(hot_value)
                    
                    # 提取关键词和分类
                    title = fields.get("title", "")
                    keywords = _extract_keywords(title)
                    content_category = _categorize_content(title, category)
                    
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
                            "summary": _generate_summary(title, hot_value, int(fields.get("rank", 0)) if fields.get("rank") else 0),
                            "content_quality": _assess_content_quality(title, hot_value)
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


def _calculate_hot_level(hot_value: int) -> str:
    """计算热度等级"""
    if hot_value >= 1000000:
        return "爆款"
    elif hot_value >= 500000:
        return "热门"
    elif hot_value >= 100000:
        return "较热"
    elif hot_value >= 10000:
        return "一般"
    else:
        return "冷门"


def _extract_keywords(title: str) -> list:
    """从标题中提取关键词"""
    if not title:
        return []
    
    # 常见停用词
    stop_words = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "那", "他", "她", "它"}
    
    # 提取中文关键词（2-4个字符）
    keywords = []
    words = re.findall(r'[\u4e00-\u9fa5]{2,4}', title)
    
    for word in words:
        if word not in stop_words and word not in keywords:
            keywords.append(word)
    
    return keywords[:5]  # 最多返回5个关键词


def _categorize_content(title: str, user_category: str = None) -> str:
    """内容分类"""
    if user_category:
        return user_category
    
    # 基于标题关键词自动分类
    title_lower = title.lower()
    
    if any(keyword in title_lower for keyword in ["政治", "政府", "政策", "规划", "建议"]):
        return "政治"
    elif any(keyword in title_lower for keyword in ["经济", "财经", "股市", "金融", "投资"]):
        return "经济"
    elif any(keyword in title_lower for keyword in ["科技", "互联网", "AI", "人工智能", "技术"]):
        return "科技"
    elif any(keyword in title_lower for keyword in ["娱乐", "明星", "电影", "音乐", "综艺"]):
        return "娱乐"
    elif any(keyword in title_lower for keyword in ["体育", "足球", "篮球", "比赛", "运动员"]):
        return "体育"
    else:
        return "综合"


def _generate_summary(title: str, hot_value: int, rank: int) -> str:
    """生成内容摘要"""
    hot_level = _calculate_hot_level(hot_value)
    
    if rank == 1:
        return f"{hot_level}内容，排名第{rank}位：{title}"
    else:
        return f"{hot_level}内容，当前排名第{rank}位：{title}"


def _assess_content_quality(title: str, hot_value: int) -> dict:
    """评估内容质量"""
    # 基于标题长度和热度评估质量
    title_length = len(title)
    
    quality_score = min(10, (title_length / 20) + (min(hot_value, 1000000) / 100000))
    
    return {
        "score": round(quality_score, 2),
        "level": "优质" if quality_score >= 7 else "良好" if quality_score >= 5 else "一般",
        "factors": [
            f"标题长度：{title_length}字符",
            f"热度值：{hot_value}",
            "内容完整性：待分析"
        ]
    }