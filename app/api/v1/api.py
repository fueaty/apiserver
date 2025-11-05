"""
API路由配置
"""

from fastapi import APIRouter
from app.api.v1.endpoints import auth, collection, publication, selection, tasks, feishu, analysis, enhanced_collection


# 创建API路由器
api_router = APIRouter()


# 注册认证路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 注册采集路由
api_router.include_router(collection.router, prefix="/collection", tags=["采集"])

# 注册发布路由
api_router.include_router(publication.router, prefix="/publication", tags=["发布"])

# 注册选材路由
api_router.include_router(selection.router, prefix="/selection", tags=["选材"])

# 注册任务管理路由
api_router.include_router(tasks.router, prefix="/tasks", tags=["任务管理"])

# 注册飞书集成路由
api_router.include_router(feishu.router, prefix="/feishu", tags=["飞书集成"])

# 注册效果分析路由
api_router.include_router(analysis.router, prefix="/analysis", tags=["效果分析"])

# 注册增强采集路由
api_router.include_router(enhanced_collection.router, prefix="/enhanced", tags=["增强采集"])