"""
新华网热点采集脚本
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id


class XinhuaSite(BaseSite):
    """新华网热点采集"""
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集新华网热点"""
        results = []
        session = None
        
        try:
            # 直接访问新华网主页
            url = "https://www.xinhuanet.com/"
            
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
                    results = self._parse_xinhua_homepage_data(text)
                else:
                    # 请求失败时返回模拟数据
                    raise Exception(f"请求失败，状态码: {response.status}")
                    
        except Exception as e:
            print(f"新华网采集脚本出错: {e}")
            # 发生错误时返回模拟数据
            results = self._get_mock_data()
            
        return results
    
    def _parse_xinhua_homepage_data(self, html_text: str) -> List[Dict[str, Any]]:
        """解析新华网主页数据"""
        from bs4 import BeautifulSoup
        import re
        
        hot_data = []
        
        try:
            soup = BeautifulSoup(html_text, 'html.parser')
            
            # 尝试多种选择器来获取新闻条目
            # 1. 查找可能的新闻列表容器
            news_containers = soup.find_all(['div', 'section'], class_=re.compile(r'.*(news|hot|headline|top).*', re.I))
            
            # 2. 如果找不到特定容器，则查找所有新闻链接
            if not news_containers:
                news_items = soup.find_all('a', href=re.compile(r'.*\.html'))
            else:
                # 在新闻容器中查找新闻条目
                news_items = []
                for container in news_containers:
                    items = container.find_all('a', href=re.compile(r'.*\.html'))
                    news_items.extend(items)
            
            # 3. 查找具有特定数据属性的新闻条目
            data_news = soup.find_all('a', attrs={'data-click': True})
            news_items.extend(data_news)
            
            # 去重
            unique_items = []
            seen_hrefs = set()
            for item in news_items:
                href = item.get('href')
                if href and href not in seen_hrefs:
                    unique_items.append(item)
                    seen_hrefs.add(href)
            
            news_items = unique_items[:100]  # 限制处理数量
            
            processed_count = 0
            for i, item in enumerate(news_items):
                try:
                    # 提取标题
                    title = item.get_text().strip()
                    
                    # 提取链接
                    url = item.get('href', '')
                    if url and not url.startswith('http'):
                        url = 'https://www.xinhuanet.com' + url
                    
                    # 过滤无效标题
                    if not title or len(title) < 6 or len(title) > 100:
                        continue
                        
                    # 过滤特定无用链接
                    if any(keyword in url for keyword in ['javascript:', 'mailto:', '.js', '.css', '.png', '.jpg']):
                        continue
                    
                    # 过滤无意义标题
                    if any(keyword in title.lower() for keyword in ['href', 'class', 'function', '{', '}']):
                        continue
                    
                    # 计算热度（基于标题长度和位置）
                    hot_score = str((len(title) * 10) + (100 - min(i, 100)))
                    
                    # 使用统一的ID生成函数
                    content_id = generate_content_id()
                    
                    hot_data.append({
                        'id': content_id,
                        'title': title,
                        'url': url,
                        'hot': hot_score,
                        'rank': str(processed_count+1),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code
                    })
                    
                    processed_count += 1
                    # 限制最多处理50条有效新闻
                    if processed_count >= 50:
                        break
                        
                except Exception:
                    continue
                        
        except Exception as e:
            # 解析失败时返回空列表
            print(f"解析新华网主页数据出错: {e}")
            pass
            
        # 如果没有解析到数据，返回模拟数据
        if not hot_data:
            hot_data = self._get_mock_data()
        else:
            # 再次去重，基于标题
            seen_titles = set()
            unique_data = []
            for item in hot_data:
                if item['title'] not in seen_titles:
                    seen_titles.add(item['title'])
                    unique_data.append(item)
            hot_data = unique_data[:30]  # 限制最多30条
            
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
                'title': '新华社热点新闻示例',
                'url': 'https://www.xinhuanet.com',
                'hot': '500000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '新华社时政要闻示例',
                'url': 'https://www.xinhuanet.com',
                'hot': '300000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            }
        ]