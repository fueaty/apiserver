"""请求日志记录中间件"""

import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.utils.metrics import metrics_collector

logger = logging.getLogger(__name__)


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """请求日志记录中间件"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        """处理请求并记录日志"""
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 获取客户端IP
        client_ip = request.client.host if request.client else "unknown"
        
        # 记录请求信息
        logger.info(
            f"Request started: {request.method} {request.url.path} "
            f"from {client_ip} "
            f"with headers: {dict(request.headers)}"
        )
        
        try:
            # 处理请求
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 记录性能指标
            is_error = response.status_code >= 400
            metrics_collector.record_api_call(
                str(request.url.path), process_time, is_error
            )
            
            # 记录响应信息
            logger.info(
                f"Request completed: {request.method} {request.url.path} "
                f"status_code={response.status_code} "
                f"process_time={process_time:.3f}s "
                f"from {client_ip}"
            )
            
            # 添加处理时间到响应头
            response.headers["X-Process-Time"] = str(process_time)
            
            return response
            
        except Exception as e:
            # 计算错误处理时间
            process_time = time.time() - start_time
            
            # 记录错误信息
            logger.error(
                f"Request failed: {request.method} {request.url.path} "
                f"error={str(e)} "
                f"process_time={process_time:.3f}s "
                f"from {client_ip}"
            )
            
            # 重新抛出异常
            raise


class PerformanceMetrics:
    """性能指标收集器"""
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.total_process_time = 0.0
        self.max_process_time = 0.0
        self.min_process_time = float('inf')
    
    def record_request(self, process_time: float, is_error: bool = False):
        """记录请求指标"""
        self.request_count += 1
        self.total_process_time += process_time
        
        if is_error:
            self.error_count += 1
        
        # 更新最大最小处理时间
        if process_time > self.max_process_time:
            self.max_process_time = process_time
        if process_time < self.min_process_time:
            self.min_process_time = process_time
    
    def get_metrics(self) -> dict:
        """获取性能指标"""
        avg_process_time = (
            self.total_process_time / self.request_count 
            if self.request_count > 0 else 0
        )
        
        error_rate = (
            self.error_count / self.request_count * 100 
            if self.request_count > 0 else 0
        )
        
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(error_rate, 2),
            "avg_process_time": round(avg_process_time, 3),
            "max_process_time": round(self.max_process_time, 3),
            "min_process_time": round(self.min_process_time, 3),
            "total_process_time": round(self.total_process_time, 3)
        }


# 全局性能指标实例
performance_metrics = PerformanceMetrics()