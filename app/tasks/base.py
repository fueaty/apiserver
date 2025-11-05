"""
异步任务基类
提供通用的任务管理和状态跟踪功能
"""

import time
import logging
from typing import Dict, Any, Optional
from celery import Task
from app.utils.metrics import metrics_collector

logger = logging.getLogger(__name__)


class BaseTask(Task):
    """异步任务基类"""
    
    def __init__(self):
        super().__init__()
        self.task_start_time = None
    
    def on_success(self, retval, task_id, args, kwargs):
        """任务成功完成时的回调"""
        execution_time = time.time() - self.task_start_time
        
        logger.info(
            f"任务 {task_id} 执行成功: "
            f"耗时 {execution_time:.2f}秒, "
            f"参数: {args}, {kwargs}"
        )
        
        # 记录性能指标
        metrics_collector.record_task_completion(
            self.name, execution_time, False
        )
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任务失败时的回调"""
        execution_time = time.time() - self.task_start_time if self.task_start_time else 0
        
        logger.error(
            f"任务 {task_id} 执行失败: "
            f"耗时 {execution_time:.2f}秒, "
            f"错误: {exc}, "
            f"参数: {args}, {kwargs}"
        )
        
        # 记录性能指标
        metrics_collector.record_task_completion(
            self.name, execution_time, True
        )
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """任务重试时的回调"""
        logger.warning(
            f"任务 {task_id} 正在重试: "
            f"重试原因: {exc}, "
            f"参数: {args}, {kwargs}"
        )
    
    def before_start(self, task_id, args, kwargs):
        """任务开始前的回调"""
        self.task_start_time = time.time()
        
        logger.info(
            f"任务 {task_id} 开始执行: "
            f"参数: {args}, {kwargs}"
        )
        
        # 记录任务开始指标
        metrics_collector.record_task_start(self.name)


class TaskManager:
    """任务管理器"""
    
    def __init__(self):
        self._tasks = {}
    
    def register_task(self, task_name: str, task_func):
        """注册任务"""
        self._tasks[task_name] = task_func
    
    def get_task(self, task_name: str):
        """获取任务函数"""
        return self._tasks.get(task_name)
    
    def list_tasks(self) -> Dict[str, Any]:
        """列出所有任务"""
        return {
            "total": len(self._tasks),
            "tasks": list(self._tasks.keys())
        }


# 全局任务管理器
task_manager = TaskManager()