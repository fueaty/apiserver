"""加密工具模块"""

import os
import base64
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional

logger = logging.getLogger(__name__)


class CryptoManager:
    """加密管理器"""
    
    def __init__(self, password: Optional[str] = None):
        """
        初始化加密管理器
        
        Args:
            password: 加密密码，如果为None则从环境变量获取
        """
        self.password = password or os.getenv('ENCRYPTION_PASSWORD', 'default-secret-key')
        self.salt = os.urandom(16)
        self.fernet = self._create_fernet()
    
    def _create_fernet(self) -> Fernet:
        """创建Fernet加密器"""
        # 使用PBKDF2生成密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        return Fernet(key)
    
    def encrypt(self, data: str) -> str:
        """加密数据"""
        try:
            encrypted_data = self.fernet.encrypt(data.encode())
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error(f"加密数据失败: {e}")
            raise
    
    def decrypt(self, encrypted_data: str) -> str:
        """解密数据"""
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_data = self.fernet.decrypt(encrypted_bytes)
            return decrypted_data.decode()
        except Exception as e:
            logger.error(f"解密数据失败: {e}")
            raise
    
    def encrypt_dict(self, data_dict: dict) -> dict:
        """加密字典中的敏感字段"""
        encrypted_dict = data_dict.copy()
        
        # 需要加密的字段
        sensitive_fields = ['password', 'token', 'secret', 'key', 'credential']
        
        for key, value in data_dict.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields) and isinstance(value, str):
                encrypted_dict[key] = self.encrypt(value)
        
        return encrypted_dict
    
    def decrypt_dict(self, encrypted_dict: dict) -> dict:
        """解密字典中的敏感字段"""
        decrypted_dict = encrypted_dict.copy()
        
        # 需要解密的字段
        sensitive_fields = ['password', 'token', 'secret', 'key', 'credential']
        
        for key, value in encrypted_dict.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields) and isinstance(value, str):
                try:
                    decrypted_dict[key] = self.decrypt(value)
                except Exception:
                    # 如果解密失败，保持原值（可能是未加密的数据）
                    pass
        
        return decrypted_dict


class RequestSigner:
    """请求签名验证器"""
    
    def __init__(self, secret_key: Optional[str] = None):
        """
        初始化请求签名器
        
        Args:
            secret_key: 签名密钥，如果为None则从环境变量获取
        """
        self.secret_key = secret_key or os.getenv('SIGNATURE_SECRET', 'default-signature-key')
    
    def generate_signature(self, data: str, timestamp: int) -> str:
        """生成请求签名"""
        import hmac
        import hashlib
        
        # 组合数据和时间戳
        message = f"{data}:{timestamp}".encode()
        
        # 使用HMAC-SHA256生成签名
        signature = hmac.new(
            self.secret_key.encode(),
            message,
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def verify_signature(self, data: str, timestamp: int, signature: str) -> bool:
        """验证请求签名"""
        try:
            # 检查时间戳是否在有效范围内（5分钟内）
            current_time = int(os.path.getmtime(__file__))  # 使用文件修改时间作为参考
            time_diff = abs(current_time - timestamp)
            
            if time_diff > 300:  # 5分钟
                logger.warning(f"请求签名时间戳过期: {time_diff}秒")
                return False
            
            # 生成期望的签名
            expected_signature = self.generate_signature(data, timestamp)
            
            # 使用恒定时间比较防止时序攻击
            return hmac.compare_digest(signature, expected_signature)
            
        except Exception as e:
            logger.error(f"验证签名失败: {e}")
            return False
    
    def sign_request(self, method: str, path: str, body: str = "") -> dict:
        """为请求生成签名头"""
        import time
        
        timestamp = int(time.time())
        
        # 组合请求数据
        request_data = f"{method}:{path}:{body}"
        
        signature = self.generate_signature(request_data, timestamp)
        
        return {
            "X-Timestamp": str(timestamp),
            "X-Signature": signature
        }


# 全局加密管理器实例
crypto_manager = CryptoManager()


# 全局请求签名器实例
request_signer = RequestSigner()