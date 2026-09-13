# -*- coding: utf-8 -*-
"""
热点数据增强工具（共享模块）

背景：`calculate_hot_level` / `extract_keywords` / `categorize_content` /
`generate_summary` / `assess_content_quality` / `parse_hot_value` 这组函数
原先在 `app/api/v1/endpoints/collection.py` 和 `enhanced_collection.py` 里
**各复制了一份**（内容逐字相同），而 `selection.py` 又**直接调用却没导入**，
一旦走到那些分支就抛 NameError → HTTP 500。

本模块把它们收敛为唯一定义，三个端点统一从这里导入。

行为与原先完全一致（逐字搬运，未改逻辑）。
"""

import re

__all__ = [
    "calculate_hot_level",
    "extract_keywords",
    "categorize_content",
    "generate_summary",
    "assess_content_quality",
    "parse_hot_value",
]

# 中文停用词（与原实现保持一致）
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "他", "她", "它",
}

_CATEGORY_RULES = (
    ("政治", ["政治", "政府", "政策", "规划", "建议"]),
    ("经济", ["经济", "财经", "股市", "金融", "投资"]),
    ("科技", ["科技", "互联网", "AI", "人工智能", "技术"]),
    ("娱乐", ["娱乐", "明星", "电影", "音乐", "综艺"]),
    ("体育", ["体育", "足球", "篮球", "比赛", "运动员"]),
)


def calculate_hot_level(hot_value) -> str:
    """计算热度等级"""
    try:
        hot_value = float(hot_value or 0)
    except (TypeError, ValueError):
        hot_value = 0.0

    if hot_value >= 1000000:
        return "爆款"
    if hot_value >= 500000:
        return "热门"
    if hot_value >= 100000:
        return "较热"
    if hot_value >= 10000:
        return "一般"
    return "冷门"


def extract_keywords(title: str) -> list:
    """从标题中提取关键词（最长 5 个）"""
    if not title:
        return []

    keywords = []
    for word in re.findall(r"[\u4e00-\u9fa5]{2,4}", title):
        if word not in _STOP_WORDS and word not in keywords:
            keywords.append(word)

    return keywords[:5]


def categorize_content(title: str, user_category: str = None) -> str:
    """内容分类（优先使用调用方传入的分类）"""
    if user_category:
        return user_category

    title_lower = (title or "").lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in title_lower for kw in keywords):
            return category
    return "综合"


def generate_summary(title: str, hot_value, rank) -> str:
    """生成内容摘要"""
    hot_level = calculate_hot_level(hot_value)
    if rank == 1:
        return f"{hot_level}内容，排名第{rank}位：{title}"
    return f"{hot_level}内容，当前排名第{rank}位：{title}"


def assess_content_quality(title: str, hot_value) -> dict:
    """评估内容质量"""
    title_length = len(title or "")
    try:
        hot_num = float(hot_value or 0)
    except (TypeError, ValueError):
        hot_num = 0.0

    quality_score = min(10, (title_length / 20) + (min(hot_num, 1000000) / 100000))

    return {
        "score": round(quality_score, 2),
        "level": "优质" if quality_score >= 7 else "良好" if quality_score >= 5 else "一般",
        "factors": [
            f"标题长度：{title_length}字符",
            f"热度值：{hot_value}",
            "内容完整性：待分析",
        ],
    }


def parse_hot_value(hot_str):
    """解析热度值字符串，处理包含「万」「千」单位的情况"""
    if not hot_str:
        return 0

    try:
        if isinstance(hot_str, (int, float)):
            return int(hot_str)

        hot_text = str(hot_str).strip()

        if "万" in hot_text:
            return int(float(hot_text.replace("万", "")) * 10000)
        if "千" in hot_text:
            return int(float(hot_text.replace("千", "")) * 1000)
        return int(float(hot_text))

    except (ValueError, TypeError):
        return 0
