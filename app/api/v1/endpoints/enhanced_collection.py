"""
增强版采集API端点
提供采集后直接入库和选材后入库的功能
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Body
import asyncio
import sys

from app.services.collection.engine import CollectionEngine
from app.services.selection.engine import SelectionEngine
from app.services.feishu.feishu_service import FeishuService
from app.api.v1.endpoints.auth import verify_token
from app.utils.logger import logger
from app.core.config import config_manager
from app.services.feishu.field_rules import TABLE_PLANS


router = APIRouter()
collection_engine = CollectionEngine()
selection_engine = SelectionEngine()
feishu_service = FeishuService()


@router.get("/collect-and-store", summary="采集网站信息并直接入库")
async def collect_and_store(
    date: Optional[str] = Query(None, description="采集日期(YYYY-MM-DD)"),
    site_code: Optional[List[str]] = Query(None, description="网站编码列表"),
    category: Optional[str] = Query(None, description="分类筛选"),
    keyword: Optional[str] = Query(None, description="关键词筛选"),
    payload: dict = Depends(verify_token)
):
    """
    采集指定网站的信息并直接存储到飞书多维表格
    
    - **date**: 采集日期，格式YYYY-MM-DD
    - **site_code**: 网站编码，多个用逗号分隔
    - **category**: 内容分类筛选
    - **keyword**: 关键词筛选
    - 需要Authorization头: Bearer <token>
    
    返回: 采集和存储结果
    """
    try:
        # 构建采集参数
        params = {
            "date": date,
            "site_code": site_code if site_code else None,  # 明确处理列表为空的情况
            "category": category,
            "keyword": keyword,
            "client_id": payload.get("client_id")
        }
        
        logger.info(f"开始采集并存储任务，客户端: {payload.get('client_id')}, 参数: {params}")
        
        # 执行采集
        results = await collection_engine.collect(params)
        
        # 过滤空结果并优化数据格式
        optimized_results = []
        feishu_records = []
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
                    from app.utils.id_generator import generate_content_id
                    hotspot_id = generate_content_id()
                    
                    # 计算热度等级
                    hot_text = fields.get("hot", 0)
                    if isinstance(hot_text, str) and '万' in hot_text:
                        # 处理包含"万"的热度值，如"5.7万"
                        hot_value = int(float(hot_text.replace('万', '')) * 10000)
                    else:
                        hot_value = int(hot_text) if hot_text else 0
                    hot_level = ""  # 由选材引擎计算
                    
                    # 提取关键词和分类
                    title = fields.get("title", "")
                    keywords = []  # 由选材引擎计算
                    content_category = category if category else ""  # 由选材引擎计算
                    
                    # 按照飞书格式返回，包含fields字段
                    optimized_news = {
                        "fields": {
                            "hotspot_id": hotspot_id,
                            "title": title,
                            "source": result["site_code"],
                            "platform": fields.get("platform", result["site_code"]),
                            "hot_value": int(float(fields.get("hot").replace('万', '')) * 10000) if isinstance(fields.get("hot"), str) and '万' in fields.get("hot") else int(fields.get("hot")) if isinstance(fields.get("hot"), (int, float)) else int(float(fields.get("hot"))) if isinstance(fields.get("hot"), str) and fields.get("hot").replace('万', '').isdigit() else 0,
                            "hot_level": "",  # 由选材引擎计算
                            "rank": int(fields.get("rank", 0)) if fields.get("rank") else 0,
                            "url": fields.get("url", ""),
                            "publish_time": fields.get("date", ""),
                            "category": "",  # 由选材引擎计算
                            "keywords": keywords,
                            "collect_time": result["collect_time"],
                            "summary": fields.get("content", ""),  # 使用原始内容作为摘要
                            "content_quality": {}  # 由选材引擎计算
                        }
                    }

                    # print(f"正在处理新闻：\n{optimized_news}")
                    optimized_result["news"].append(optimized_news)
                    
                    # 构造飞书记录
                    feishu_record = {
                        "fields": {
                            "id": hotspot_id,
                            "title": title,
                            "url": fields.get("url", ""),
                            "content": fields.get("content", ""),
                            "author": "",  # 采集数据中暂无作者信息
                            "category": content_category,
                            "hot": str(int(float(fields.get("hot").replace('万', '')) * 10000) if isinstance(fields.get("hot"), str) and '万' in fields.get("hot") else int(fields.get("hot")) if isinstance(fields.get("hot"), (int, float)) else int(float(fields.get("hot"))) if isinstance(fields.get("hot"), str) and fields.get("hot").replace('万', '').isdigit() else 0),
                            "rank": str(int(fields.get("rank", 0)) if fields.get("rank") else 0),
                            "collected_at": result["collect_time"],
                            "site_code": result["site_code"],
                            "status": "collected"
                        }
                    }
                    feishu_records.append(feishu_record)
                
                optimized_results.append(optimized_result)
        
        logger.info(f"采集任务完成，共采集 {len(optimized_results)} 个站点，{sum(len(r['news']) for r in optimized_results)} 条新闻")
        
        # 存储到飞书多维表格
        logger.info(f"开始存储 {len(feishu_records)} 条记录到飞书多维表格")
        
        # 从配置中获取参数
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            raise Exception("飞书配置参数缺失，请检查 config/credentials.yaml 文件")
        
        # 同步字段
        required_fields = TABLE_PLANS["headlines"]["fields"]
        success, message = await feishu_service.ensure_table_fields(app_token, table_id, required_fields)
        if not success:
            logger.warning(f"飞书表格字段同步失败: {message}")
        
        # 插入记录
        result = await feishu_service.batch_add_records(app_token, table_id, feishu_records)
        
        if result.get("code") == 0:
            record_count = len(result.get("data", {}).get("records", []))
            logger.info(f"成功插入 {record_count} 条记录到飞书多维表格")
        else:
            logger.error(f"插入记录到飞书多维表格失败: {result.get('msg')}")
            raise Exception(f"插入记录到飞书多维表格失败: {result.get('msg')}")
        
        return {
            "code": 200,
            "message": "采集并存储成功",
            "data": {
                "results": optimized_results,
                "feishu_records": len(feishu_records),
                "stored_records": record_count
            }
        }
        
    except Exception as e:
        logger.error(f"采集并存储任务失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500103,
                "message": f"采集并存储失败: {str(e)}",
                "data": None
            }
        )


@router.post("/select-and-store", summary="从热点库提取数据进行选材分析，并将选材结果存储到飞书多维表格")
async def select_and_store(
    platforms: Optional[List[str]] = None,
    payload: dict = Depends(verify_token)
):
    """
    从热点库提取数据进行选材分析，并将选材结果存储到飞书多维表格
    
    - **platforms**: 目标平台列表
    - 需要Authorization头: Bearer <token>
    
    返回: 选材和存储结果
    """
    try:
        logger.info(f"开始选材并存储任务，目标平台: {platforms}")
        
        # 从飞书多维表格获取热点数据
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            raise Exception("飞书配置参数缺失，请检查 config/credentials.yaml 文件")
        
        # 查询记录
        records = await feishu_service.list_records(app_token, table_id, page_size=100)
        
        if not records:
            raise Exception("未找到热点数据")
        
        # 转换为选材引擎需要的格式
        hotspots_data = []
        for record in records:
            fields = record.get("fields", {})
            hotspot_item = {
                "hotspot_id": fields.get("id", ""),
                "title": fields.get("title", ""),
                "source": fields.get("site_code", ""),
                "platform": fields.get("site_code", ""),
                "hot_value": int(fields.get("hot", 0)) if fields.get("hot") else 0,
                "hot_level": "",
                "rank": int(fields.get("rank", 0)) if fields.get("rank") else 0,
                "category": fields.get("category", ""),
                "keywords": _extract_keywords(fields.get("title", "")),
                "collect_time": fields.get("collected_at", ""),
                "publish_time": "",
                "summary": fields.get("content", ""),
                "content_quality": {},
                "original_data": fields
            }
                
            hotspots_data.append(hotspot_item)
        
        logger.info(f"从飞书多维表格获取到 {len(hotspots_data)} 条热点数据")
        
        # 调用选材引擎进行分析
        results = await selection_engine.analyze_hotspots(hotspots_data, platforms)
        
        logger.info(f"选材分析完成: 分析 {len(hotspots_data)} 个热点，覆盖 {len(platforms or [])} 个平台")
        logger.info(f"选材结果: {results}")
        
        # 按照飞书格式构建响应数据 - 返回selections数组
        selections_list = []
        feishu_records = []
        
        # 将所有平台的选材结果合并到一个数组中
        for platform, selections in results["selections"].items():
            logger.info(f"平台 {platform} 有 {len(selections)} 条选材结果")
            for selection in selections:
                # 按照飞书格式构建fields字段，包含platform字段
                selection_record = {
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
                }
                selections_list.append(selection_record)
                
                # 构造飞书记录用于存储
                feishu_record = {
                    "fields": {
                        "id": selection.get("hotspot_id", ""),
                        "title": selection.get("title", ""),
                        "source": selection.get("source", ""),
                        "platform": platform,
                        "hot_level": selection.get("hot_level", ""),
                        "rank": str(selection.get("rank", 0)),
                        "suitability_score": str(selection.get("total_score", 0.0)),
                        "content_angle": selection.get("content_angle", ""),
                        "recommended_strategy": selection.get("recommended_strategy", ""),
                        "reason": selection.get("reason", ""),
                        "status": "selected"
                    }
                }
                feishu_records.append(feishu_record)
        
        # 存储选材结果到飞书多维表格
        logger.info(f"开始存储 {len(feishu_records)} 条选材结果到飞书多维表格")
        
        # 如果没有选材结果，则直接返回成功
        if not feishu_records:
            logger.info("没有选材结果需要存储")
            return {
                "code": 200,
                "message": "选材并存储成功（无符合条件的结果）",
                "data": {
                    "selections": selections_list,
                    "stored_records": 0
                }
            }
        
        # 获取选材结果表的配置
        selection_app_token = creds.get("feishu", {}).get("tables", {}).get("content_selection", {}).get("app_token")
        selection_table_id = creds.get("feishu", {}).get("tables", {}).get("content_selection", {}).get("table_id")
        
        if not selection_app_token or not selection_table_id:
            raise Exception("飞书选材结果表配置参数缺失，请检查 config/credentials.yaml 文件")
        
        # 同步字段
        selection_required_fields = TABLE_PLANS["content_selection"]["fields"]
        success, message = await feishu_service.ensure_table_fields(
            selection_app_token, selection_table_id, selection_required_fields, "Selections")
        if not success:
            logger.warning(f"飞书选材结果表字段同步失败: {message}")
        
        # 插入记录
        result = await feishu_service.batch_add_records(selection_app_token, selection_table_id, feishu_records)
        
        if result.get("code") == 0:
            record_count = len(result.get("data", {}).get("records", []))
            logger.info(f"成功插入 {record_count} 条选材结果到飞书多维表格")
        else:
            logger.error(f"插入选材结果到飞书多维表格失败: {result.get('msg')}")
            raise Exception(f"插入选材结果到飞书多维表格失败: {result.get('msg')}")
        
        return {
            "code": 200,
            "message": "选材并存储成功",
            "data": {
                "selections": selections_list,
                "stored_records": len(feishu_records)
            }
        }
        
    except Exception as e:
        logger.error(f"选材并存储任务失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": 500104,
                "message": f"选材并存储失败: {str(e)}",
                "data": None
            }
        )


def _extract_keywords(title: str) -> list:
    """从标题中提取关键词"""
    if not title:
        return []
    
    import re
    
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


def _parse_hot_value(hot_str):
    """解析热度值字符串，处理包含单位的情况"""
    if not hot_str:
        return 0
    
    try:
        # 如果是数字直接返回
        if isinstance(hot_str, (int, float)):
            return int(hot_str)
        
        # 转换为字符串处理
        hot_text = str(hot_str).strip()
        
        # 处理"万"单位
        if '万' in hot_text:
            number = float(hot_text.replace('万', ''))
            return int(number * 10000)
        
        # 处理"千"单位
        elif '千' in hot_text:
            number = float(hot_text.replace('千', ''))
            return int(number * 1000)
        
        # 直接转换为整数
        else:
            return int(float(hot_text))
            
    except (ValueError, TypeError):
        # 解析失败时返回默认值0
        return 0
