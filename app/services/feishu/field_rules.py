from typing import Dict, Any

# 基础字段定义
BASE_FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # 通用字段（文本）
    'id': {'type': 'text'},
    'title': {'type': 'text'},
    'url': {'type': 'text'},
    'content': {'type': 'text'},
    'author': {'type': 'text'},
    'category': {'type': 'text'},
    'summary': {'type': 'text'},
    'tags': {'type': 'text'},
    'seo_title': {'type': 'text'},
    'seo_description': {'type': 'text'},
    'seo_keywords': {'type': 'text'},

    # 数值字段
    'hot': {'type': 'text'},
    'rank': {'type': 'text'},

    # 日期字段
    'published_at': {'type': 'text'},
    'collected_at': {'type': 'text'},

    # 状态、平台相关字段
    'site_code': {'type': 'text'},
    'platform_code': {'type': 'text'},
    'published_url': {'type': 'text'},
    'status': {'type': 'text'},
    'error_message': {'type': 'text'},

    # AI 分析字段
    'sentiment': {'type': 'text'},

    # 平台管理表字段
    'platform_id': {'type': 'text'},
    'platform_name': {'type': 'text'},
    'enabled': {'type': 'text'},
    'core_domains': {'type': 'text'},
    'primary_domain': {'type': 'text'},
    'secondary_domain': {'type': 'text'},
    'content_style': {'type': 'text'},
    'optimal_word_count': {'type': 'text'},
    'best_publish_time': {'type': 'text'},
    'avoid_domains': {'type': 'text'},
    'scoring_weight': {'type': 'text'},
    'updated_date': {'type': 'text'},
    
    # 内容选材表字段（规则表）
    'rule_id': {'type': 'text'},
    'target_audience': {'type': 'text'},
    'content_preference': {'type': 'text'},
    'content_form': {'type': 'text'},
    'authority_requirement': {'type': 'text'},
    'timeliness_requirement': {'type': 'text'},
    'interactivity_requirement': {'type': 'text'},
    'avoid_keywords': {'type': 'text'},
    'rule_enabled': {'type': 'text'},

    # 选材「结果」表字段（content_selection 写入口径的唯一事实来源）
    # ⚠️ 写入方见 app/api/v1/endpoints/enhanced_collection.py 中构造 feishu_record 的位置；
    #    这里少定义一个字段，字段同步就会把线上同名列连同数据一起删掉（见下方 _resolve_fields）。
    'source': {'type': 'text'},
    'platform': {'type': 'text'},
    'hot_level': {'type': 'text'},
    'suitability_score': {'type': 'text'},
    'content_angle': {'type': 'text'},
    'recommended_strategy': {'type': 'text'},
    'reason': {'type': 'text'},
    
    # 采集源管理表字段
    'source_id': {'type': 'text'},
    'source_name': {'type': 'text'},
    'source_type': {'type': 'text'},
    'authority_level': {'type': 'text'},
    'collection_frequency': {'type': 'text'},
    'source_enabled': {'type': 'text'},
    'collection_url': {'type': 'text'},
    'last_collection_time': {'type': 'text'},
    'collection_success_rate': {'type': 'text'},
    
    # 发布任务表字段
    'task_id': {'type': 'text'},
    'content_id': {'type': 'text'},
    'task_status': {'type': 'text'},
    'scheduled_publish_time': {'type': 'text'},
    'actual_publish_time': {'type': 'text'},
    'publish_result': {'type': 'text'},
    'publish_link': {'type': 'text'},
    'views': {'type': 'text'},
    'likes': {'type': 'text'},
    'comments': {'type': 'text'},
    
    # 内容质量评估表字段
    'evaluation_id': {'type': 'text'},
    'platform_fit': {'type': 'text'},
    'content_quality_score': {'type': 'text'},
    'authority_score': {'type': 'text'},
    'timeliness_score': {'type': 'text'},
    'interaction_potential_score': {'type': 'text'},
    'risk_assessment': {'type': 'text'},
    'evaluation_time': {'type': 'text'},
    'evaluator': {'type': 'text'},
}

# 为不同表格类型定义字段定义
FIELD_DEFINITIONS: Dict[str, Dict[str, Dict[str, Any]]] = {
    'headlines': BASE_FIELD_DEFINITIONS,
    'ai_insights': BASE_FIELD_DEFINITIONS,
    'distribution': BASE_FIELD_DEFINITIONS,
    'platform_configs': BASE_FIELD_DEFINITIONS,
    'content_selection': BASE_FIELD_DEFINITIONS,
    'data_sources': BASE_FIELD_DEFINITIONS,
    'publish_tasks': BASE_FIELD_DEFINITIONS,
    'content_evaluation': BASE_FIELD_DEFINITIONS,
}

REQUIRED_FIELDS = set(BASE_FIELD_DEFINITIONS.keys())


def _resolve_fields(keywords=None, explicit=None):
    """解析某张表应同步的字段集合（关键词命中 ∪ 显式名单）。

    为什么需要这个函数：`ensure_table_fields()` 会执行
        fields_to_delete = 线上字段 - required_fields
    也就是说，**凡是没被解析进来的线上列都会被删除（连带数据）**。
    历史实现把显式名单写成 `{f for f in REQUIRED_FIELDS if f in [...]}`——
    未定义的字段名会在这里被静默过滤掉，于是线上对应的列就被当成“多余字段”删掉。
    缺陷 8 正是如此：content_selection 声明 11 个字段，实际只解析出 id/title/rank/status，
    另外 7 个（source/platform/hot_level/suitability_score/content_angle/
    recommended_strategy/reason）面临被删除的风险。

    因此这里对「显式名单」做定义校验，未定义即 import 期报错，绝不静默放过。

    Args:
        keywords: 关键词列表；字段名命中任一关键词即纳入
        explicit: 显式字段名列表；必须全部已在 BASE_FIELD_DEFINITIONS 中定义

    Returns:
        解析后的字段名集合
    """
    explicit = explicit or []

    undefined = sorted(name for name in explicit if name not in BASE_FIELD_DEFINITIONS)
    if undefined:
        raise ValueError(
            "TABLE_PLANS 显式引用了未定义的字段 %s。"
            "请先在 BASE_FIELD_DEFINITIONS 中补全定义——否则字段同步会把线上同名列"
            "及其数据一并删除。" % (undefined,)
        )

    selected = set()
    for name in BASE_FIELD_DEFINITIONS:
        if keywords and any(keyword in name for keyword in keywords):
            selected.add(name)
        elif explicit and name in explicit:
            selected.add(name)
    return selected


TABLE_PLANS = {
    # ⚠️ 每张表的字段一律用「显式名单」声明，不要再改成关键词匹配。
    # 历史上 platform_configs/data_sources/content_evaluation 等表用
    # `any(keyword in f for keyword in [...])` 匹配，导致只在选材结果表里
    # 使用的 source / platform / suitability_score 等通用词，会被别的表
    # 顺带命中并被 ensure_table_fields 创建成多余列（跨表污染）。
    # 显式名单让每张表的线上结构可静态审计，配合 _resolve_fields 的定义校验，
    # 既不会漏建（缺陷 8），也不会多建。
    'headlines': {
        'name': 'AI Headlines Pipeline',
        'purpose': '存放微博等热点采集的头条数据',
        # 需求①(R1-1)：补入 published_at，使真实发布时间不被 _align_records_with_fields
        # 当多余字段丢弃。定义已在 BASE_FIELD_DEFINITIONS（纯新增名单项，不触发守卫）。
        # 名单项 11 -> 12；写入方 enhanced_collection.py 的 headlines feishu_record 已同步补键。
        'fields': _resolve_fields(explicit=['id', 'title', 'url', 'content', 'author', 'category', 'hot', 'rank', 'collected_at', 'published_at', 'site_code', 'status'])
    },
    'ai_insights': {
        'name': 'AI Insights Archive',
        'purpose': '存放AI生成的深度分析内容',
        'fields': _resolve_fields(explicit=['id', 'title', 'url', 'content', 'author', 'category', 'summary', 'tags', 'sentiment', 'seo_title', 'seo_description', 'seo_keywords', 'published_at', 'status'])
    },
    'distribution': {
        'name': 'Content Distribution Tracker',
        'purpose': '存放内容分发渠道及状态',
        'fields': _resolve_fields(explicit=['id', 'title', 'content', 'url', 'platform_code', 'published_url', 'status', 'error_message', 'published_at'])
    },
    'platform_configs': {
        'name': 'Platform Management',
        'purpose': '管理各内容平台的配置信息',
        'fields': _resolve_fields(explicit=['id', 'title', 'enabled', 'updated_date', 'platform_id', 'platform_name', 'platform_code', 'core_domains', 'primary_domain', 'secondary_domain', 'content_style', 'optimal_word_count', 'best_publish_time', 'avoid_domains', 'scoring_weight', 'platform_fit', 'scheduled_publish_time', 'actual_publish_time'])
    },
    'content_selection': {
        'name': 'Content Selection Rules',
        'purpose': '存放选材结果',
        # 这 11 个字段必须与写入方（app/api/v1/endpoints/enhanced_collection.py
        # 构造 feishu_record 处）逐一对应，少一个就会被当多余列删掉。
        'fields': _resolve_fields(explicit=['id', 'title', 'source', 'platform', 'hot_level', 'rank', 'suitability_score', 'content_angle', 'recommended_strategy', 'reason', 'status'])
    },
    'data_sources': {
        'name': 'Data Sources Configuration',
        'purpose': '管理各种数据采集源',
        'fields': _resolve_fields(explicit=['id', 'title', 'enabled', 'source_id', 'source_name', 'source_type', 'authority_level', 'collection_frequency', 'source_enabled', 'collection_url', 'last_collection_time', 'collection_success_rate', 'url', 'published_url', 'authority_requirement', 'authority_score'])
    },
    'publish_tasks': {
        'name': 'Content Publishing Tasks',
        'purpose': '跟踪内容发布任务状态',
        # 需求①(R1-3)：补入 error_message，使发布失败原因可落库。定义已在
        # BASE_FIELD_DEFINITIONS（纯新增名单项）。名单项 13 -> 14。
        'fields': _resolve_fields(explicit=['id', 'status', 'task_id', 'content_id', 'platform_id', 'task_status', 'scheduled_publish_time', 'actual_publish_time', 'publish_result', 'publish_link', 'views', 'likes', 'comments', 'error_message'])
    },
    'content_evaluation': {
        'name': 'Content Quality Monitoring',
        'purpose': '评估和监控内容质量',
        'fields': _resolve_fields(explicit=['id', 'content_id', 'platform_fit', 'evaluator', 'evaluation_id', 'content_quality_score', 'authority_score', 'timeliness_score', 'interaction_potential_score', 'risk_assessment', 'evaluation_time', 'sentiment', 'timeliness_requirement', 'best_publish_time', 'last_collection_time', 'scheduled_publish_time', 'actual_publish_time'])
    }
}