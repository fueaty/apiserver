"""
Celery工作进程启动脚本
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.core.celery_config import celery_app


if __name__ == "__main__":
    # 启动Celery工作进程
    celery_app.start()