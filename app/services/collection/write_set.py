# -*- coding: utf-8 -*-
"""采集结果的**写入集**构造（单一实现，行为可测）。

为什么把「从采集引擎结果 → 飞书写入集」的构造抽到本模块：这条构造里藏着
「mock 不得入库」这条**安全保证**，但它原先**内联在两条生产写入路径里**：

  · ``script/collection_pipeline.py``            （cron 主路径）
  · ``app/api/v1/endpoints/enhanced_collection.py``（采集 API 直写路径）

内联的后果：只能靠「源码文本里有没有出现某个函数名」这种**文本锁**去守，
而文本锁对**行为失效**（例如把 `continue` 改成 `pass`：检查了却不生效）完全无感。
把它抽成**纯函数**后，两条路径都调用同一实现，测试可以**直接喂混合批次**
断言「最终写集里 mock == 0」——行为级接线锁。

两条写入路径的入口：
  · `split_write_set(collection_results)` → (real, mock)     —— pipeline
  · `build_headline_records(results, category)` → (优化结果, 飞书记录, 跳过数) —— API 端点
"""

from typing import Any, Dict, List, Optional, Tuple

from app.services.collection.mock_utils import is_mock_record, split_real_and_mock
from app.utils.id_generator import generate_content_id


def split_write_set(
    collection_results: List[Dict[str, Any]],
) -> Tuple[List[Any], List[Any]]:
    """把引擎采集结果拼成扁平记录列表，再按 ``is_mock`` 标记拆成 (real, mock)。

    等价于旧 pipeline 的「手工 extend 出 raw 列表 + split_real_and_mock(raw)」，
    集中一处以便行为测试。**mock 一律落在第二个返回值里、绝不进 real。**

    Args:
        collection_results: `CollectionEngine.collect()` 的返回值（每个元素形如
            ``{"site_code": ..., "news": [...]}``）。

    Returns:
        (real_records, mock_records)：real 为入库集，mock 为排除集（单独上报）。
    """
    raw: List[Any] = []
    for result in collection_results or []:
        if result and result.get("news"):
            raw.extend(result["news"])
    return split_real_and_mock(raw)


def build_headline_records(
    results: List[Dict[str, Any]],
    category: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """从引擎采集结果构造 headlines 写入集（enhanced_collection 的第二写入路径）。

    ⚠️ **时序**：mock 过滤必须发生在**按固定键重建 feishu_record 之前**——重建只保留
    白名单键，会把 ``is_mock`` 标记洗白（与 ``sites/xinhua.py`` 解析路径同类陷阱），
    一旦顺序颠倒，mock 就会静默混入写集。

    本函数逻辑与旧端点逐字等价（含热度解析表达式），仅把「内联」变为「可测函数」，
    并显式返回被跳过的 mock 数以便调用方告警。

    Args:
        results: `CollectionEngine.collect()` 的返回值。
        category: 端点传入的分类筛选（写入 category 字段），默认 None。

    Returns:
        (optimized_results, feishu_records, mock_skipped)：
          · optimized_results: 供选材引擎使用的优化结果（已剔除 mock）；
          · feishu_records:    写入 headlines 的记录（已剔除 mock）；
          · mock_skipped:      被排除的 mock 条数（>0 时应告警）。
    """
    optimized_results: List[Dict[str, Any]] = []
    feishu_records: List[Dict[str, Any]] = []
    mock_skipped = 0

    for result in results or []:
        if not (result and result.get("news")):
            continue

        optimized_result: Dict[str, Any] = {
            "site_code": result["site_code"],
            "collect_time": result["collect_time"],
            "data_count": result["data_count"],
            "news": [],
        }

        for news_item in result["news"]:
            # —— mock 治理：过滤必须早于下面的「按固定键重建」（否则标记被洗白）——
            if is_mock_record(news_item):
                mock_skipped += 1
                continue

            # 提取 fields 中的字段
            fields = news_item.get("fields", {})

            # 生成标准化的热点 ID
            hotspot_id = generate_content_id()

            # 计算热度等级（保留原实现的计算，便于与旧行为逐字一致）
            hot_text = fields.get("hot", 0)
            if isinstance(hot_text, str) and '万' in hot_text:
                hot_value = int(float(hot_text.replace('万', '')) * 10000)
            else:
                hot_value = int(hot_text) if hot_text else 0
            hot_level = ""  # 由选材引擎计算

            # 提取关键词和分类
            title = fields.get("title", "")
            keywords: List[Any] = []  # 由选材引擎计算
            content_category = category if category else ""  # 由选材引擎计算

            # 按照飞书格式返回，包含 fields 字段
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
                    "content_quality": {},  # 由选材引擎计算
                }
            }

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
                    # 需求①(R1-2)：published_at 已加入 TABLE_PLANS['headlines']，
                    # 写入侧必须同步补键，否则该 dict 字段集 ≠ 表规划，字段会被丢弃。
                    "published_at": fields.get("published_at", ""),
                    "site_code": result["site_code"],
                    "status": "collected",
                }
            }
            feishu_records.append(feishu_record)

        optimized_results.append(optimized_result)

    return optimized_results, feishu_records, mock_skipped
