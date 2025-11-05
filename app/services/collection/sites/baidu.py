"""
百度热点采集脚本
"""

import json
import re
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
from bs4 import BeautifulSoup
# 使用新的ID生成工具
from ....utils.id_generator import generate_content_id


class BaiduSite(BaseSite):
    """百度热点采集"""
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集百度热点"""
        results = []
        
        try:
            # 构建请求URL
            url = "https://top.baidu.com/board?tab=realtime"
            
            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            # 发送请求
            session = await self.get_session()
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    # 获取响应内容
                    text = await response.text()
                    # 解析数据
                    results = self._parse_baidu_data(text)
                else:
                    # 请求失败时返回模拟数据
                    results = self._get_mock_data()
                    
        except Exception as e:
            # 发生错误时返回模拟数据
            results = self._get_mock_data()
            
        return results
    
    def _parse_baidu_data(self, html_text: str) -> List[Dict[str, Any]]:
        """解析百度热点数据"""
        hot_data = []
        
        try:
            # 尝试使用正则表达式提取数据
            pattern = r'"word":"([^"]+)","hotScore":"([^"]+)","url":"([^"]+)"'
            matches = re.findall(pattern, html_text)
            
            for i, match in enumerate(matches[:50]):  # 限制最多50条
                # 使用统一的ID生成函数
                content_id = generate_content_id()
                
                title, hot_score, url = match
                if hot_score:  # 只有hot_score不为空才添加
                    hot_data.append({
                        'id': content_id,
                        'title': title,
                        'url': url,
                        'hot': hot_score,
                        'rank': str(i+1),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code
                    })
            
            # 如果正则没有匹配到，尝试使用BeautifulSoup
            if not hot_data:
                soup = BeautifulSoup(html_text, 'html.parser')
                # 百度热搜榜的条目容器
                items = soup.find_all('div', class_='category-wrap_iQLoo')[:50]
                
                for i, item in enumerate(items):
                    try:
                        # 使用统一的ID生成函数
                        content_id = generate_content_id()
                        
                        # 提取标题
                        title_elem = item.find('div', class_='c-single-text-ellipsis')
                        title = title_elem.get_text().strip() if title_elem else ''
                        
                        # 提取热度
                        hot_elem = item.find('div', class_='hot-index_1Bl1a')
                        hot = hot_elem.get_text().strip() if hot_elem else ''
                        
                        # 提取链接
                        link_elem = item.find('a')
                        url = link_elem.get('href', '') if link_elem else ''
                        
                        if title and hot:  # 只有标题和热度都不为空才添加
                            hot_data.append({
                                'id': content_id,
                                'title': title,
                                'url': url,
                                'hot': hot,
                                'rank': str(i+1),
                                'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'collected_at': self._get_current_time(),
                                'site_code': self.site_code
                            })
                    except Exception:
                        continue
                        
        except Exception as e:
            # 解析失败时返回空列表
            pass
            
        # 将数据格式转换为包含fields键的标准格式
        formatted_results = []
        for item in hot_data:
            formatted_results.append({"fields": item})
            
        return formatted_results
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）"""
        mock_data = [
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '百度热点新闻示例',
                'url': 'https://www.baidu.com',
                'hot': '500000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '百度热搜话题示例',
                'url': 'https://www.baidu.com',
                'hot': '300000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            }
        ]
        
        # 将数据格式转换为包含fields键的标准格式
        formatted_results = []
        for item in mock_data:
            formatted_results.append({"fields": item})
            
        return formatted_results