"""
央视新闻热点采集脚本
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id


class CctvSite(BaseSite):
    """央视新闻热点采集"""
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集央视新闻热点"""
        results = []
        session = None
        
        try:
            # 直接访问央视新闻主页
            url = "https://news.cctv.com/"
            
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
                    results = self._parse_cctv_homepage_data(text)
                else:
                    # 请求失败时返回模拟数据
                    raise Exception(f"请求失败，状态码: {response.status}")
                    
        except Exception as e:
            print(f"央视新闻采集脚本出错: {e}")
            # 发生错误时返回模拟数据
            results = self._get_mock_data()
            
        # 根据参数决定返回格式
        format_type = params.get("format", "raw")
        if format_type == "feishu":
            # 转换为飞书格式
            results = [
                {"fields": item} 
                for item in results
            ]
            
        return results
    
    def _parse_cctv_homepage_data(self, html_text: str) -> List[Dict[str, Any]]:
        """解析央视新闻主页数据"""
        from bs4 import BeautifulSoup
        import re
        
        hot_data = []
        
        try:
            soup = BeautifulSoup(html_text, 'html.parser')
            
            # 查找新闻条目，使用更精确的选择器
            # 查找包含新闻链接的元素
            news_items = soup.find_all(['a'], href=re.compile(r'.*\.shtml'))
            
            for i, item in enumerate(news_items[:50]):  # 限制最多50条
                try:
                    # 提取标题
                    title = item.get_text().strip()
                    
                    # 提取链接
                    url = item.get('href', '')
                    
                    # 过滤无效标题
                    if not title or len(title) < 4 or 'href' in title:
                        continue
                    
                    # 简单热度计算（基于标题长度）
                    hot_score = str(len(title) * 10)
                    
                    # 使用统一的ID生成函数
                    content_id = generate_content_id()
                    
                    # 添加所有必需字段以匹配飞书表格字段要求
                    hot_data.append({
                        'id': content_id,
                        'title': title,
                        'url': url,
                        'hot': hot_score,
                        'rank': str(i+1),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code,
                        'category': '新闻',  # 添加category字段
                        'content': '',       # 添加content字段
                        'author': '央视新闻', # 添加author字段
                        'status': 'collected' # 添加status字段
                    })
                except Exception as e:
                    # 跳过解析出错的条目
                    continue
                        
        except Exception as e:
            # 解析失败时返回空列表
            print(f"解析央视新闻主页数据出错: {e}")
            pass
            
        # 如果没有解析到数据，返回模拟数据
        if not hot_data:
            hot_data = self._get_mock_data()
        else:
            # 去重，基于标题
            seen_titles = set()
            unique_data = []
            for item in hot_data:
                if item['title'] not in seen_titles:
                    seen_titles.add(item['title'])
                    unique_data.append(item)
            hot_data = unique_data[:50]  # 限制最多50条
            
        return hot_data
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）"""
        return [
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '央视新闻热点示例',
                'url': 'https://news.cctv.com',
                'hot': '500000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code,
                'category': '示例分类',
                'content': '这是央视新闻的示例内容',
                'author': '央视新闻',
                'status': 'collected'
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '央视时政要闻示例',
                'url': 'https://news.cctv.com',
                'hot': '300000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code,
                'category': '时政',
                'content': '这是央视时政新闻的示例内容',
                'author': '央视新闻',
                'status': 'collected'
            }
        ]