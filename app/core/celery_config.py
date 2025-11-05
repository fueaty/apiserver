"""
Celery配置模块
配置异步任务队列
"""

import os
from celery import Celery
from app.core.config import settings


# 创建Celery应用
celery_app = Celery(
    "intelligent_agent_api",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.collection_tasks",
        "app.tasks.selection_tasks", 
        "app.tasks.publication_tasks"
    ]
)

# 配置Celery - 针对2核2G服务器优化
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # 时区设置
    timezone="Asia/Shanghai",
    enable_utc=True,
    
    # 任务结果设置 - 减少内存占用
    task_track_started=False,  # 关闭任务开始事件跟踪
    task_send_sent_event=False,  # 关闭任务发送事件
    
    # 任务路由
    task_routes={
        "app.tasks.collection_tasks.*": {"queue": "collection"},
        "app.tasks.selection_tasks.*": {"queue": "selection"},
        "app.tasks.publication_tasks.*": {"queue": "publication"},
    },
    
    # 任务超时设置
    task_time_limit=180,  # 3分钟（减少超时时间）
    task_soft_time_limit=150,  # 2.5分钟
    
    # 重试设置
    task_acks_late=False,  # 立即确认任务
    task_reject_on_worker_lost=False,  # 简化错误处理
    
    # 工作进程设置 - 减少内存占用
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,  # 减少每个子进程处理的任务数
    worker_max_memory_per_child=100000,  # 限制每个工作进程内存使用（100MB）
)

# 配置任务结果过期时间
celery_app.conf.result_expires = 3600  # 1小时

# 配置任务监控
celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True