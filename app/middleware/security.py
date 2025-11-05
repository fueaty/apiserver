"""安全中间件模块"""

import logging
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Optional

from app.utils.crypto import request_signer

logger = logging.getLogger(__name__)


class SignatureVerificationMiddleware(BaseHTTPMiddleware):
    """请求签名验证中间件"""
    
    def __init__(self, app: ASGIApp, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
    
    async def dispatch(self, request: Request, call_next):
        """处理请求并验证签名"""
        
        # 如果签名验证未启用，直接处理请求
        if not self.enabled:
            return await call_next(request)
        
        # 跳过健康检查等不需要签名的端点
        if request.url.path in ['/health', '/metrics', '/docs', '/redoc']:
            return await call_next(request)
        
        # 获取签名头
        timestamp_header = request.headers.get("X-Timestamp")
        signature_header = request.headers.get("X-Signature")
        
        # 检查必要的签名头
        if not timestamp_header or not signature_header:
            logger.warning(f"请求缺少签名头: {request.method} {request.url.path}")
            raise HTTPException(
                status_code=401,
                detail="请求签名验证失败：缺少必要的签名头"
            )
        
        try:
            # 解析时间戳
            timestamp = int(timestamp_header)
            
            # 获取请求体
            body = await self._get_request_body(request)
            
            # 验证签名
            request_data = f"{request.method}:{request.url.path}:{body}"
            
            if not request_signer.verify_signature(request_data, timestamp, signature_header):
                logger.warning(f"请求签名验证失败: {request.method} {request.url.path}")
                raise HTTPException(
                    status_code=401,
                    detail="请求签名验证失败：签名不匹配"
                )
            
            # 签名验证通过，继续处理请求
            logger.info(f"请求签名验证成功: {request.method} {request.url.path}")
            return await call_next(request)
            
        except ValueError as e:
            logger.error(f"请求签名验证错误: {e}")
            raise HTTPException(
                status_code=400,
                detail="请求签名验证失败：时间戳格式错误"
            )
        except Exception as e:
            logger.error(f"请求签名验证异常: {e}")
            raise HTTPException(
                status_code=500,
                detail="请求签名验证失败：内部错误"
            )
    
    async def _get_request_body(self, request: Request) -> str:
        """获取请求体内容"""
        try:
            # 对于GET请求，没有请求体
            if request.method == "GET":
                return ""
            
            # 读取请求体
            body_bytes = await request.body()
            return body_bytes.decode("utf-8")
        except Exception as e:
            logger.warning(f"获取请求体失败: {e}")
            return ""


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """IP白名单中间件"""
    
    def __init__(self, app: ASGIApp, enabled: bool = True, whitelist: Optional[list] = None):
        super().__init__(app)
        self.enabled = enabled
        self.whitelist = whitelist or []
    
    async def dispatch(self, request: Request, call_next):
        """处理请求并检查IP白名单"""
        
        # 如果IP白名单未启用，直接处理请求
        if not self.enabled:
            return await call_next(request)
        
        # 获取客户端IP
        client_ip = request.client.host if request.client else "unknown"
        
        # 检查IP是否在白名单中
        if client_ip not in self.whitelist and "*" not in self.whitelist:
            logger.warning(f"IP地址不在白名单中: {client_ip} 访问 {request.method} {request.url.path}")
            raise HTTPException(
                status_code=403,
                detail="访问被拒绝：IP地址不在白名单中"
            )
        
        # IP验证通过，继续处理请求
        logger.info(f"IP白名单验证通过: {client_ip} 访问 {request.method} {request.url.path}")
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全头中间件"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        """处理请求并添加安全头"""
        
        # 处理请求
        response = await call_next(request)
        
        # 添加安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        # 移除服务器信息头
        if "server" in response.headers:
            del response.headers["server"]
        
        return response