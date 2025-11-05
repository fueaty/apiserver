"""
通用依赖与异常处理工具
"""

from fastapi import HTTPException, status


def create_http_exception(code: int, message: str) -> HTTPException:
    """构造统一格式的 HTTP 异常"""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": code,
            "message": message,
            "data": None
        }
    )
