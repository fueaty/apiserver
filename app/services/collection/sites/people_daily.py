"""
人民网热点采集脚本
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id


class PeopleDailySite(BaseSite):
    """人民网热点采集"""
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集人民网热点"""
        results = []
        session = None
        
        try:
            # 构建请求URL（使用配置中的URL）
            url = self.config.get("request", {}).get("url", "https://www.people.com.cn/rss/politics.xml")
            
            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            }
            
            # 发送请求
            session = await self.get_session()
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    # 获取响应内容
                    text = await response.text()
                    # 解析数据
                    results = self._parse_people_daily_data(text)
                else:
                    # 请求失败时返回模拟数据
                    results = self._get_mock_data()
                    
        except Exception as e:
            # 发生错误时返回模拟数据
            results = self._get_mock_data()
            
        return results
    
    def _parse_people_daily_data(self, xml_text: str) -> List[Dict[str, Any]]:
        """解析人民网热点数据"""
        from bs4 import BeautifulSoup
        import re
        
        hot_data = []
        
        try:
            soup = BeautifulSoup(xml_text, 'xml')
            items = soup.find_all('item')[:50]  # 限制最多50条
            
            for i, item in enumerate(items):
                try:
                    # 使用统一的ID生成函数
                    content_id = generate_content_id()
                    
                    # 提取标题
                    title_elem = item.find('title')
                    title = title_elem.get_text().strip() if title_elem else ''
                    
                    # 提取链接
                    link_elem = item.find('link')
                    url = link_elem.get_text().strip() if link_elem else ''
                    
                    # 提取描述
                    desc_elem = item.find('description')
                    description = desc_elem.get_text().strip() if desc_elem else ''
                    
                    # 提取发布时间
                    pubdate_elem = item.find('pubDate')
                    pubdate = pubdate_elem.get_text().strip() if pubdate_elem else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 简单热度计算（基于标题和描述长度）
                    hot_score = str(len(title) + len(description))
                    
                    if title:  # 只有标题不为空才添加
                        hot_data.append({
                            'id': content_id,
                            'title': title,
                            'url': url,
                            'hot': hot_score,
                            'rank': str(i+1),
                            'published_at': pubdate,
                            'collected_at': self._get_current_time(),
                            'site_code': self.site_code
                        })
                except Exception:
                    continue
                        
        except Exception as e:
            # 解析失败时返回空列表
            pass
            
        # 格式化数据，确保与weibo.py格式一致
        results = []
        for item in hot_data:
            result = {
                'id': item['id'],
                'title': item['title'],
                'url': item['url'],
                'hot': item['hot'],
                'rank': item['rank'],
                'published_at': item['published_at'],
                'collected_at': item['collected_at'],
                'site_code': item['site_code']
            }
            
            # 数据清洗和验证
            if self._validate_result(result):
                results.append({"fields": result})
                
        return results
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）"""
        return [
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '人民网热点新闻示例',
                'url': 'http://www.people.com.cn',
                'hot': '500000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '人民网时政要闻示例',
                'url': 'http://www.people.com.cn',
                'hot': '300000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            }
        ]