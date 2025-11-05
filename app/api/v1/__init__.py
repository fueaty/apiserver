from fastapi import APIRouter

from .endpoints import auth, collection, selection, publication, analysis, tasks, feishu, enhanced_collection

api_router = APIRouter()

# 注册各模块路由
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(collection.router, prefix="/collection", tags=["collection"])
api_router.include_router(selection.router, prefix="/selection", tags=["selection"])
api_router.include_router(publication.router, prefix="/publication", tags=["publication"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(feishu.router, prefix="/feishu", tags=["feishu"])
api_router.include_router(enhanced_collection.router, prefix="/enhanced-collection", tags=["enhanced-collection"])

# 健康检查端点
@api_router.get("/health", tags=["system"])
async def health_check():
    """系统健康检查接口"""
    return {
        "status": "ok",
        "message": "API服务运行正常"
    }