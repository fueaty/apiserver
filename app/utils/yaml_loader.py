"""
YAML 配置加载工具
提供线程安全、带缓存的 YAML 文件读取能力
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict

import yaml

from app.utils.logger import logger


class YamlLoader:
    """YAML 配置加载器，负责缓存与线程安全读取"""

    _lock = threading.Lock()
    _cache: Dict[Path, Dict[str, Any]] = {}

    @classmethod
    def load(cls, file_path: Path) -> Dict[str, Any]:
        """加载并缓存 YAML 配置文件"""
        resolved_path = file_path.resolve()

        with cls._lock:
            if resolved_path in cls._cache:
                return cls._cache[resolved_path]

            try:
                with resolved_path.open("r", encoding="utf-8") as file:
                    data = yaml.safe_load(file) or {}
                    cls._cache[resolved_path] = data
                    return data
            except FileNotFoundError:
                logger.warning(f"配置文件未找到: {resolved_path}")
            except yaml.YAMLError as error:
                logger.error(f"解析 YAML 文件失败: {resolved_path}，错误: {error}")
            except Exception as error:
                logger.error(f"加载配置文件时发生未知错误: {resolved_path}，错误: {error}")

            cls._cache[resolved_path] = {}
            return {}

    @classmethod
    def invalidate(cls, file_path: Path) -> None:
        """失效指定路径的缓存"""
        resolved_path = file_path.resolve()
        with cls._lock:
            cls._cache.pop(resolved_path, None)

    @classmethod
    def clear_cache(cls) -> None:
        """清除全部缓存"""
        with cls._lock:
            cls._cache.clear()


def load_yaml_config(file_path: Path) -> Dict[str, Any]:
    """便捷方法：加载 YAML 配置"""
    return YamlLoader.load(file_path)
