"""
robots.txt协议检查器
"""

import re
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse
import aiohttp
from app.utils.logger import logger


class RobotsTxtChecker:
    """robots.txt协议检查器"""
    
    def __init__(self):
        self._cache = {}  # 缓存robots.txt内容
        self._user_agent = "IntelligentAgentAPI/1.0"
    
    async def can_fetch(self, url: str, user_agent: Optional[str] = None) -> bool:
        """
        检查是否允许抓取指定URL
        
        Args:
            url: 目标URL
            user_agent: 用户代理，默认为应用标识
            
        Returns:
            True表示允许抓取，False表示禁止
        """
        if not user_agent:
            user_agent = self._user_agent
            
        # 解析URL获取域名
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        if not domain:
            logger.warning(f"无法解析URL的域名: {url}")
            return True  # 默认允许
        
        # 获取robots.txt内容
        robots_url = f"https://{domain}/robots.txt"
        robots_content = await self._get_robots_content(robots_url)
        
        if not robots_content:
            # 如果无法获取robots.txt，默认允许抓取
            return True
        
        # 解析robots.txt规则
        rules = self._parse_robots_txt(robots_content, user_agent)
        
        # 检查路径是否允许
        path = parsed_url.path or "/"
        return self._check_path_allowed(path, rules)
    
    async def _get_robots_content(self, robots_url: str) -> Optional[str]:
        """获取robots.txt内容"""
        # 检查缓存
        if robots_url in self._cache:
            return self._cache[robots_url]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(robots_url, timeout=5) as response:
                    if response.status == 200:
                        content = await response.text()
                        self._cache[robots_url] = content
                        return content
                    elif response.status == 404:
                        # 没有robots.txt文件，缓存空结果
                        self._cache[robots_url] = ""
                        return ""
                    else:
                        logger.warning(f"获取robots.txt失败: {robots_url}, 状态码: {response.status}")
                        return None
        except Exception as e:
            logger.warning(f"获取robots.txt异常: {robots_url}, 错误: {str(e)}")
            return None
    
    def _parse_robots_txt(self, content: str, user_agent: str) -> Dict[str, List[str]]:
        """解析robots.txt内容"""
        rules = {"allow": [], "disallow": []}
        
        if not content:
            return rules
        
        lines = content.split('\n')
        current_ua = None
        
        for line in lines:
            line = line.strip()
            
            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue
            
            # 解析User-agent
            if line.lower().startswith('user-agent:'):
                current_ua = line.split(':', 1)[1].strip()
                continue
            
            # 解析Allow/Disallow规则
            if current_ua and (current_ua == '*' or current_ua.lower() in user_agent.lower()):
                if line.lower().startswith('allow:'):
                    path = line.split(':', 1)[1].strip()
                    rules["allow"].append(path)
                elif line.lower().startswith('disallow:'):
                    path = line.split(':', 1)[1].strip()
                    rules["disallow"].append(path)
        
        return rules
    
    def _check_path_allowed(self, path: str, rules: Dict[str, List[str]]) -> bool:
        """检查路径是否允许抓取"""
        # 默认允许
        if not rules["disallow"]:
            return True
        
        # 检查disallow规则
        for disallow_pattern in rules["disallow"]:
            if disallow_pattern and self._path_matches_pattern(path, disallow_pattern):
                # 检查是否有更具体的allow规则覆盖
                for allow_pattern in rules["allow"]:
                    if self._path_matches_pattern(path, allow_pattern):
                        # allow规则优先级更高
                        return True
                return False
        
        return True
    
    def _path_matches_pattern(self, path: str, pattern: str) -> bool:
        """检查路径是否匹配模式"""
        if not pattern:
            return False
        
        # 处理通配符
        regex_pattern = re.escape(pattern)
        regex_pattern = regex_pattern.replace(r'\*', '.*')
        regex_pattern = regex_pattern.replace(r'\$', '$')
        
        # 确保以^开头，以$结尾（如果pattern以$结尾）
        if pattern.endswith('$'):
            regex_pattern = f"^{regex_pattern}$"
        else:
            regex_pattern = f"^{regex_pattern}"
        
        try:
            return bool(re.match(regex_pattern, path))
        except re.error:
            logger.warning(f"正则表达式错误: {regex_pattern}")
            return False
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()


# 全局实例
robots_checker = RobotsTxtChecker()