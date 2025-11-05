"""
日志工具模块
提供统一的日志记录功能
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from app.core.config import settings


# 创建日志格式器
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# 创建根日志记录器
logger = logging.getLogger("intelligent-agent-api")
logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))


# 控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# 文件处理器（如果配置了日志文件）
if settings.LOG_FILE:
    try:
        # 确保日志目录存在
        log_dir = os.path.dirname(settings.LOG_FILE)
        os.makedirs(log_dir, exist_ok=True)
        
        # 创建轮转文件处理器
        file_handler = RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"无法创建文件日志处理器: {e}")


# 防止日志传播到根日志记录器
logger.propagate = False