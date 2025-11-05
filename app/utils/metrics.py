"""性能监控指标工具"""

import time
import psutil
import logging
from typing import Dict, Any
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)


class SystemMetrics:
    """系统性能指标收集器"""
    
    def __init__(self):
        self._lock = Lock()
        self.start_time = time.time()
    
    def get_cpu_usage(self) -> float:
        """获取CPU使用率"""
        try:
            return psutil.cpu_percent(interval=1)
        except Exception as e:
            logger.error(f"获取CPU使用率失败: {e}")
            return 0.0
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """获取内存使用情况"""
        try:
            memory = psutil.virtual_memory()
            return {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent
            }
        except Exception as e:
            logger.error(f"获取内存使用情况失败: {e}")
            return {"percent": 0.0}
    
    def get_disk_usage(self) -> Dict[str, Any]:
        """获取磁盘使用情况"""
        try:
            disk = psutil.disk_usage('/')
            return {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            }
        except Exception as e:
            logger.error(f"获取磁盘使用情况失败: {e}")
            return {"percent": 0.0}
    
    def get_network_io(self) -> Dict[str, Any]:
        """获取网络IO统计"""
        try:
            net_io = psutil.net_io_counters()
            return {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv
            }
        except Exception as e:
            logger.error(f"获取网络IO统计失败: {e}")
            return {}
    
    def get_system_uptime(self) -> float:
        """获取系统运行时间"""
        return time.time() - self.start_time
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """获取所有系统指标"""
        with self._lock:
            return {
                "timestamp": datetime.now().isoformat(),
                "cpu_usage_percent": self.get_cpu_usage(),
                "memory_usage": self.get_memory_usage(),
                "disk_usage": self.get_disk_usage(),
                "network_io": self.get_network_io(),
                "uptime_seconds": self.get_system_uptime()
            }


class ApplicationMetrics:
    """应用性能指标收集器"""
    
    def __init__(self):
        self._lock = Lock()
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0.0
        self.response_times = []
        self.api_calls = {}
        self.start_time = time.time()
    
    def record_request(self, endpoint: str, response_time: float, is_error: bool = False):
        """记录请求指标"""
        with self._lock:
            self.request_count += 1
            self.total_response_time += response_time
            self.response_times.append(response_time)
            
            if is_error:
                self.error_count += 1
            
            # 记录API调用统计
            if endpoint not in self.api_calls:
                self.api_calls[endpoint] = {
                    "count": 0,
                    "total_time": 0.0,
                    "errors": 0
                }
            
            self.api_calls[endpoint]["count"] += 1
            self.api_calls[endpoint]["total_time"] += response_time
            if is_error:
                self.api_calls[endpoint]["errors"] += 1
            
            # 保持最近1000个响应时间记录
            if len(self.response_times) > 1000:
                self.response_times = self.response_times[-1000:]
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取应用指标"""
        with self._lock:
            avg_response_time = (
                self.total_response_time / self.request_count 
                if self.request_count > 0 else 0
            )
            
            error_rate = (
                self.error_count / self.request_count * 100 
                if self.request_count > 0 else 0
            )
            
            # 计算响应时间百分位数
            sorted_times = sorted(self.response_times)
            p95 = sorted_times[int(len(sorted_times) * 0.95)] if sorted_times else 0
            p99 = sorted_times[int(len(sorted_times) * 0.99)] if sorted_times else 0
            
            return {
                "timestamp": datetime.now().isoformat(),
                "uptime_seconds": time.time() - self.start_time,
                "request_count": self.request_count,
                "error_count": self.error_count,
                "error_rate_percent": round(error_rate, 2),
                "avg_response_time_seconds": round(avg_response_time, 3),
                "p95_response_time_seconds": round(p95, 3),
                "p99_response_time_seconds": round(p99, 3),
                "total_response_time_seconds": round(self.total_response_time, 3),
                "api_calls": self.api_calls
            }
    
    def get_api_statistics(self) -> Dict[str, Any]:
        """获取API调用统计"""
        with self._lock:
            api_stats = {}
            for endpoint, stats in self.api_calls.items():
                avg_time = (
                    stats["total_time"] / stats["count"] 
                    if stats["count"] > 0 else 0
                )
                error_rate = (
                    stats["errors"] / stats["count"] * 100 
                    if stats["count"] > 0 else 0
                )
                
                api_stats[endpoint] = {
                    "call_count": stats["count"],
                    "error_count": stats["errors"],
                    "error_rate_percent": round(error_rate, 2),
                    "avg_response_time_seconds": round(avg_time, 3),
                    "total_time_seconds": round(stats["total_time"], 3)
                }
            
            return api_stats


class TaskMetrics:
    """任务性能指标收集器"""
    
    def __init__(self):
        self._lock = Lock()
        self.task_stats = {}
        self.running_tasks = {}
    
    def record_task_start(self, task_name: str):
        """记录任务开始"""
        with self._lock:
            if task_name not in self.task_stats:
                self.task_stats[task_name] = {
                    "started": 0,
                    "completed": 0,
                    "failed": 0,
                    "total_time": 0.0,
                    "last_start_time": None
                }
            
            self.task_stats[task_name]["started"] += 1
            self.task_stats[task_name]["last_start_time"] = time.time()
            
            # 记录运行中的任务
            task_id = f"{task_name}_{int(time.time())}"
            self.running_tasks[task_id] = {
                "task_name": task_name,
                "start_time": time.time()
            }
    
    def record_task_completion(self, task_name: str, execution_time: float, is_failure: bool = False):
        """记录任务完成"""
        with self._lock:
            if task_name not in self.task_stats:
                self.task_stats[task_name] = {
                    "started": 1,
                    "completed": 0,
                    "failed": 0,
                    "total_time": 0.0
                }
            
            if is_failure:
                self.task_stats[task_name]["failed"] += 1
            else:
                self.task_stats[task_name]["completed"] += 1
            
            self.task_stats[task_name]["total_time"] += execution_time
    
    def get_task_metrics(self) -> Dict[str, Any]:
        """获取任务性能指标"""
        with self._lock:
            task_metrics = {}
            for task_name, stats in self.task_stats.items():
                total_executions = stats["started"]
                success_rate = (
                    stats["completed"] / total_executions * 100 
                    if total_executions > 0 else 0
                )
                avg_time = (
                    stats["total_time"] / total_executions 
                    if total_executions > 0 else 0
                )
                
                task_metrics[task_name] = {
                    "total_executions": total_executions,
                    "successful": stats["completed"],
                    "failed": stats["failed"],
                    "success_rate_percent": round(success_rate, 2),
                    "avg_execution_time_seconds": round(avg_time, 3),
                    "total_execution_time_seconds": round(stats["total_time"], 3)
                }
            
            return task_metrics
    
    def get_running_tasks(self) -> Dict[str, Any]:
        """获取运行中的任务"""
        with self._lock:
            running_tasks_info = {}
            for task_id, task_info in self.running_tasks.items():
                running_time = time.time() - task_info["start_time"]
                running_tasks_info[task_id] = {
                    "task_name": task_info["task_name"],
                    "running_time_seconds": round(running_time, 3)
                }
            
            return running_tasks_info


class MetricsCollector:
    """综合指标收集器"""
    
    def __init__(self):
        self.system_metrics = SystemMetrics()
        self.app_metrics = ApplicationMetrics()
        self.task_metrics = TaskMetrics()
    
    def get_comprehensive_metrics(self) -> Dict[str, Any]:
        """获取综合性能指标"""
        return {
            "system": self.system_metrics.get_all_metrics(),
            "application": self.app_metrics.get_metrics(),
            "api_statistics": self.app_metrics.get_api_statistics(),
            "task_metrics": self.task_metrics.get_task_metrics(),
            "running_tasks": self.task_metrics.get_running_tasks()
        }
    
    def record_api_call(self, endpoint: str, response_time: float, is_error: bool = False):
        """记录API调用"""
        self.app_metrics.record_request(endpoint, response_time, is_error)
    
    def record_task_start(self, task_name: str):
        """记录任务开始"""
        self.task_metrics.record_task_start(task_name)
    
    def record_task_completion(self, task_name: str, execution_time: float, is_failure: bool = False):
        """记录任务完成"""
        self.task_metrics.record_task_completion(task_name, execution_time, is_failure)


# 全局指标收集器实例
metrics_collector = MetricsCollector()