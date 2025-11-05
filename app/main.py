"""
FastAPI应用主入口
智能体工作流API服务
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import aiohttp

from app.core.config import settings
from app.api.v1.api import api_router
from app.middleware.rate_limiter import RateLimitMiddleware
from app.middleware.exception_handler import ExceptionHandlingMiddleware
from app.middleware.request_logger import RequestLoggerMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    logger.info("正在启动智能体工作流API服务...")
    
    # 创建全局HTTP会话
    app.state.http_session = aiohttp.ClientSession()
    logger.info("HTTP会话池已初始化")
    
    yield
    
    # 关闭时清理资源
    logger.info("正在关闭智能体工作流API服务...")
    await app.state.http_session.close()
    logger.info("HTTP会话池已关闭")


# 创建FastAPI应用实例
app = FastAPI(
    title="智能体工作流API服务",
    description="基于FastAPI的智能体工作流接口服务，提供身份验证、网站采集、内容发布等功能",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 添加中间件
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(ExceptionHandlingMiddleware)
app.add_middleware(RateLimitMiddleware)


# 注册API路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """根路径健康检查"""
    return {
        "message": "智能体工作流API服务运行正常",
        "version": "1.0.0",
        "status": "healthy"
    }


@app.get("/health")
async def health_check():
    """健康检查接口"""
    from app.utils.metrics import metrics_collector
    from datetime import datetime
    import redis
    
    # 获取系统指标
    system_metrics = metrics_collector.system_metrics.get_all_metrics()
    
    # 检查系统健康状况
    cpu_usage = system_metrics.get("cpu_usage_percent", 0)
    memory_usage = system_metrics.get("memory_usage", {}).get("percent", 0)
    
    # 检查Redis连接
    redis_status = "unknown"
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        if r.ping():
            redis_status = "healthy"
        else:
            redis_status = "unhealthy"
    except Exception:
        redis_status = "unreachable"
    
    # 检查Celery状态（通过Redis中的任务队列信息）
    celery_status = "unknown"
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        # 检查是否有活跃的Celery worker
        worker_keys = r.keys("celery@*")
        if worker_keys:
            celery_status = "healthy"
        else:
            celery_status = "no_workers"
    except Exception:
        celery_status = "unreachable"
    
    # 判断整体服务状态
    status = "healthy"
    if cpu_usage > 85 or memory_usage > 80:
        status = "degraded"
    elif cpu_usage > 95 or memory_usage > 90:
        status = "unhealthy"
    elif redis_status != "healthy" or celery_status != "healthy":
        status = "degraded"
    
    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "uptime": system_metrics.get("uptime_seconds", 0),
        "services": {
            "api": "healthy",
            "redis": redis_status,
            "celery": celery_status
        },
        "metrics": {
            "cpu_usage_percent": cpu_usage,
            "memory_usage_percent": memory_usage
        }
    }


@app.get("/metrics")
async def get_metrics():
    """获取详细性能指标"""
    from app.utils.metrics import metrics_collector
    
    return metrics_collector.get_comprehensive_metrics()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS
    )