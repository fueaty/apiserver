"""
异步任务模块
提供Celery异步任务支持
"""

from app.core.celery_config import celery_app

__all__ = ["celery_app"]