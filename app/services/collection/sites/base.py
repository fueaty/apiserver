"""
采集站点基类
定义采集站点的通用接口和基础功能
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime
import aiohttp
from abc import ABC, abstractmethod


class BaseSite(ABC):
    """采集站点基类"""
    
    def __init__(self, site_code: str, config: Dict[str, Any]):
        self.site_code = site_code
        self.config = config
        self._session = None
    
    @abstractmethod
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集数据接口"""
        pass
    
    async def get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.get("timeout", 10))
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session
    
    async def cleanup(self):
        """清理资源"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def _validate_result(self, result: Dict[str, Any]) -> bool:
        """验证采集结果"""
        # 检查必要字段
        required_fields = ['title', 'url']
        return all(result.get(field) for field in required_fields)