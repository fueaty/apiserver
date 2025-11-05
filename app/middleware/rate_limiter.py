"""
速率限制中间件
基于令牌桶算法的API限流
"""

import time
from typing import Dict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.utils.logger import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""
    
    def __init__(self, app):
        super().__init__(app)
        self.rate_limits: Dict[str, dict] = {}
        self._setup_rate_limits()
    
    def _setup_rate_limits(self):
        """设置速率限制规则"""
        # 全局默认限制
        self.rate_limits["global"] = {
            "max_requests": settings.RATE_LIMIT_PER_MINUTE,
            "window": 60,  # 60秒窗口
            "tokens": settings.RATE_LIMIT_PER_MINUTE,
            "last_refill": time.time()
        }
        
        # 特定接口限制
        self.rate_limits["collection"] = {
            "max_requests": 10,  # 每分钟10次
            "window": 60,
            "tokens": 10,
            "last_refill": time.time()
        }
        
        self.rate_limits["publication"] = {
            "max_requests": 5,  # 每分钟5次
            "window": 60,
            "tokens": 5,
            "last_refill": time.time()
        }
    
    async def dispatch(self, request: Request, call_next):
        """处理请求"""
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        
        # 确定适用的限流规则
        rule_key = self._get_rate_limit_rule(path)
        
        # 检查速率限制
        if not self._check_rate_limit(rule_key, client_ip):
            logger.warning(f"速率限制触发: IP={client_ip}, Path={path}")
            return Response(
                content='{"code": 429, "message": "请求频率超限，请稍后重试"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"}
            )
        
        # 继续处理请求
        response = await call_next(request)
        return response
    
    def _get_rate_limit_rule(self, path: str) -> str:
        """根据路径获取适用的限流规则"""
        if "/collection" in path:
            return "collection"
        elif "/publication" in path:
            return "publication"
        else:
            return "global"
    
    def _check_rate_limit(self, rule_key: str, client_ip: str) -> bool:
        """检查速率限制"""
        rule = self.rate_limits.get(rule_key, self.rate_limits["global"])
        current_time = time.time()
        
        # 计算时间窗口内需要补充的令牌
        time_passed = current_time - rule["last_refill"]
        if time_passed > rule["window"]:
            # 重置令牌桶
            rule["tokens"] = rule["max_requests"]
            rule["last_refill"] = current_time
        else:
            # 补充令牌（线性补充）
            tokens_to_add = (time_passed / rule["window"]) * rule["max_requests"]
            rule["tokens"] = min(rule["max_requests"], rule["tokens"] + tokens_to_add)
            rule["last_refill"] = current_time
        
        # 检查是否有足够的令牌
        if rule["tokens"] >= 1:
            rule["tokens"] -= 1
            return True
        else:
            return False