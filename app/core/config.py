"""
应用配置管理
基于pydantic-settings的配置管理，支持热重载
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List, Optional, Dict, Any
import os
import yaml
import time
from threading import Lock


class Settings(BaseSettings):
    """应用配置类"""
    
    # 基础配置
    APP_NAME: str = "智能体工作流API服务"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 2
    
    # 路径配置
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    CONFIG_DIR: Path = BASE_DIR.parent / "config"
    SITES_CONFIG_FILE: Path = CONFIG_DIR / "sites.yaml"
    PLATFORMS_CONFIG_FILE: Path = CONFIG_DIR / "platforms.yaml"
    CREDENTIALS_CONFIG_FILE: Path = CONFIG_DIR / "credentials.yaml"
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120  # 2小时
    
    # CORS配置
    ALLOWED_ORIGINS: List[str] = ["*"]
    
    # 数据库配置（可选，用于扩展）
    DATABASE_URL: Optional[str] = None
    
    # 速率限制配置
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    
    # 采集配置
    COLLECTION_TIMEOUT: int = 10
    COLLECTION_MAX_RETRIES: int = 3
    
    # 发布配置
    PUBLICATION_TIMEOUT: int = 15
    PUBLICATION_MAX_RETRIES: int = 3
    
    # Redis配置（用于Celery任务队列）- 针对2核2G服务器优化
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 10  # 减少连接数
    REDIS_MAX_MEMORY: str = "256mb"  # 限制内存使用
    REDIS_MAX_MEMORY_POLICY: str = "allkeys-lru"  # 内存不足时删除最近最少使用的key
    
    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: List[str] = ["json"]
    
    # 异步任务配置
    ASYNC_TASK_TIMEOUT: int = 300  # 5分钟
    ASYNC_TASK_RETRY_COUNT: int = 3
    ASYNC_TASK_RETRY_DELAY: int = 60  # 1分钟
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "/var/log/intelligent-agent-api/app.log"
    
    # 热重载配置
    CONFIG_RELOAD_INTERVAL: int = 30  # 30秒检查一次配置更新
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局配置实例
settings = Settings()


class ConfigManager:
    """配置管理器，支持热重载"""
    
    def __init__(self):
        self._sites_config = None
        self._platforms_config = None
        self._last_modified = {}
        self._lock = Lock()
        
    def load_yaml_config(self, file_path: Path) -> Dict[str, Any]:
        """加载YAML配置文件"""
        try:
            if not file_path.exists():
                print(f"配置文件不存在: {file_path}")
                return {}
                
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"加载配置文件失败 {file_path}: {e}")
            return {}
    
    def get_sites_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """获取站点配置，支持热重载"""
        with self._lock:
            if force_reload or self._should_reload(settings.SITES_CONFIG_FILE):
                self._sites_config = self.load_yaml_config(settings.SITES_CONFIG_FILE)
                self._update_last_modified(settings.SITES_CONFIG_FILE)
            return self._sites_config or {}
    
    def get_platforms_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """获取平台配置，支持热重载"""
        with self._lock:
            if force_reload or self._should_reload(settings.PLATFORMS_CONFIG_FILE):
                self._platforms_config = self.load_yaml_config(settings.PLATFORMS_CONFIG_FILE)
                self._update_last_modified(settings.PLATFORMS_CONFIG_FILE)
            return self._platforms_config or {}

    def get_credentials(self, force_reload: bool = False) -> Dict[str, Any]:
        """获取凭证配置，支持热重载"""
        with self._lock:
            if force_reload or self._should_reload(settings.CREDENTIALS_CONFIG_FILE):
                self._credentials_config = self.load_yaml_config(settings.CREDENTIALS_CONFIG_FILE)
                self._update_last_modified(settings.CREDENTIALS_CONFIG_FILE)
            return self._credentials_config or {}
    
    def _should_reload(self, file_path: Path) -> bool:
        """检查是否需要重新加载配置"""
        if not file_path.exists():
            return False
            
        current_mtime = file_path.stat().st_mtime
        last_mtime = self._last_modified.get(str(file_path), 0)
        
        return current_mtime > last_mtime
    
    def _update_last_modified(self, file_path: Path):
        """更新文件最后修改时间"""
        if file_path.exists():
            self._last_modified[str(file_path)] = file_path.stat().st_mtime


# 全局配置管理器实例
config_manager = ConfigManager()