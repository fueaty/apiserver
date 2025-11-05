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
    
    # 内容选材表字段
    'rule_id': {'type': 'text'},
    'target_audience': {'type': 'text'},
    'content_preference': {'type': 'text'},
    'content_form': {'type': 'text'},
    'authority_requirement': {'type': 'text'},
    'timeliness_requirement': {'type': 'text'},
    'interactivity_requirement': {'type': 'text'},
    'avoid_keywords': {'type': 'text'},
    'rule_enabled': {'type': 'text'},
    
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

TABLE_PLANS = {
    'headlines': {
        'name': 'AI Headlines Pipeline',
        'purpose': '存放微博等热点采集的头条数据',
        'fields': {f for f in REQUIRED_FIELDS if f in ['id', 'title', 'url', 'content', 'author', 'category', 'hot', 'rank', 'collected_at', 'site_code', 'status']}
    },
    'ai_insights': {
        'name': 'AI Insights Archive',
        'purpose': '存放AI生成的深度分析内容',
        'fields': {f for f in REQUIRED_FIELDS if f in ['id', 'title', 'url', 'content', 'author', 'category', 'summary', 'tags', 'sentiment', 'seo_title', 'seo_description', 'seo_keywords', 'published_at', 'status']}
    },
    'distribution': {
        'name': 'Content Distribution Tracker',
        'purpose': '存放内容分发渠道及状态',
        'fields': {f for f in REQUIRED_FIELDS if f in ['id', 'title', 'content', 'url', 'platform_code', 'published_url', 'status', 'error_message', 'published_at']}
    },
    'platform_configs': {
        'name': 'Platform Management',
        'purpose': '管理各内容平台的配置信息',
        'fields': {f for f in REQUIRED_FIELDS if any(keyword in f for keyword in ['platform', 'domain', 'content_style', 'word_count', 'publish_time', 'scoring_weight']) or f in ['id', 'title', 'enabled', 'updated_date']}
    },
    'content_selection': {
        'name': 'Content Selection Rules',
        'purpose': '存放选材结果',
        'fields': {f for f in REQUIRED_FIELDS if f in ['id', 'title', 'source', 'platform', 'hot_level', 'rank', 'suitability_score', 'content_angle', 'recommended_strategy', 'reason', 'status']}
    },
    'data_sources': {
        'name': 'Data Sources Configuration',
        'purpose': '管理各种数据采集源',
        'fields': {f for f in REQUIRED_FIELDS if any(keyword in f for keyword in ['source', 'authority', 'frequency', 'url', 'success_rate', 'collection']) or f in ['id', 'title', 'type', 'enabled']}
    },
    'publish_tasks': {
        'name': 'Content Publishing Tasks',
        'purpose': '跟踪内容发布任务状态',
        'fields': {f for f in REQUIRED_FIELDS if any(keyword in f for keyword in ['task', 'content_id', 'scheduled', 'actual', 'result', 'link', 'views', 'likes', 'comments']) or f in ['id', 'platform_id', 'status']}
    },
    'content_evaluation': {
        'name': 'Content Quality Monitoring',
        'purpose': '评估和监控内容质量',
        'fields': {f for f in REQUIRED_FIELDS if any(keyword in f for keyword in ['evaluation', 'score', 'potential', 'risk', 'assessment', 'time']) or f in ['id', 'content_id', 'platform_fit', 'evaluator']}
    }
}