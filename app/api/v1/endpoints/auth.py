"""
身份验证API端点
提供JWT令牌验证和刷新功能
"""

from datetime import datetime, timedelta
from typing import Optional
import os
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.core.config import settings, config_manager
from app.utils.logger import logger


# 创建路由器和安全方案
router = APIRouter()
security = HTTPBearer()


# 内存存储有效令牌（生产环境应使用Redis）
_token_cache = {}


def load_valid_auth_keys():
    """从secret/auth_key.json加载有效的auth_key"""
    auth_keys = set()
    auth_key_file = "/root/apiserver/secret/auth_key.json"
    
    if os.path.exists(auth_key_file):
        try:
            with open(auth_key_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for entry in data.get("token_list", []):
                    if entry.get("status") == "active":
                        auth_keys.add(entry.get("token"))
        except Exception as e:
            logger.error(f"读取auth_key文件失败: {e}")
    
    return auth_keys


def get_jwt_secret() -> str:
    """获取JWT签名密钥"""
    try:
        creds = config_manager.get_credentials()
        secret = creds.get("jwt", {}).get("secret_key")
        if secret:
            return secret
    except Exception as e:
        logger.warning(f"从凭证管理器获取JWT密钥失败，使用默认密钥: {e}")
    
    logger.info("使用settings中的SECRET_KEY作为JWT密钥")
    return settings.SECRET_KEY


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """创建JWT访问令牌"""
    # 获取JWT密钥
    jwt_secret = get_jwt_secret()
    
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    
    encoded_jwt = jwt.encode(to_encode, jwt_secret, algorithm=settings.ALGORITHM)
    
    # 缓存令牌信息
    _token_cache[encoded_jwt] = {
        'client_id': data.get('client_id'),
        'expires_at': expire.timestamp()
    }
    
    return encoded_jwt


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证JWT令牌"""
    token = credentials.credentials
    
    try:
        # 获取JWT密钥
        jwt_secret = get_jwt_secret()
        
        # 检查内存缓存
        if token not in _token_cache:
            # 检查是否为预设的有效auth_key
            valid_auth_keys = load_valid_auth_keys()
            if token not in valid_auth_keys:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "code": 40101,
                        "message": "无效的认证令牌",
                        "data": None
                    }
                )
        
        # 验证JWT令牌
        payload = jwt.decode(token, jwt_secret, algorithms=[settings.ALGORITHM])
        
        # 检查令牌是否过期
        if datetime.utcnow().timestamp() > payload.get("exp", 0):
            # 从缓存中移除过期令牌
            _token_cache.pop(token, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": 40102,
                    "message": "令牌已过期",
                    "data": None
                }
            )
        
        return payload
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": 40101,
                "message": "无效的认证令牌",
                "data": None
            }
        )


@router.post("/verify", summary="验证令牌")
async def verify_access_token(payload: dict = Depends(verify_token)):
    """
    验证访问令牌的有效性
    
    - 需要Authorization头: Bearer <token>
    - 返回: 令牌信息
    """
    return {
        "code": 200,
        "message": "success",
        "data": {
            "client_id": payload.get("client_id"),
            "expires_at": payload.get("exp"),
            "valid": True
        }
    }


@router.post("/refresh", summary="刷新令牌")
async def refresh_access_token(payload: dict = Depends(verify_token)):
    """
    刷新访问令牌
    
    - 需要Authorization头: Bearer <token>
    - 返回: 新的访问令牌
    """
    client_id = payload.get("client_id")
    
    # 创建新的访问令牌
    new_access_token = create_access_token(
        data={"client_id": client_id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    logger.info(f"为客户端 {client_id} 刷新访问令牌")
    
    return {
        "code": 200,
        "message": "success",
        "data": {
            "authkey": new_access_token,
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "token_type": "Bearer"
        }
    }