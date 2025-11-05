"""
统一异常处理
提供全局异常捕获与标准化响应输出
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.utils.logger import logger


class ExceptionHandlingMiddleware(BaseHTTPMiddleware):
    """统一异常处理中间件"""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        try:
            response = await call_next(request)
            return response
        except Exception as error:  # noqa: BLE001
            logger.error(
                "请求处理异常",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "client": request.client.host if request.client else None,
                    "error": str(error)
                },
                exc_info=True
            )

            return JSONResponse(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": 50000,
                    "message": "服务器内部错误，请稍后重试",
                    "data": None
                }
            )
