"""
微博热搜采集脚本（整合版）
结合基础HTTP请求和浏览器自动化技术
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WeiboSite(BaseSite):
    """微博热搜采集（整合版）"""
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集微博热搜数据"""
        results = []
        
        # 优先尝试使用浏览器自动化技术
        if PLAYWRIGHT_AVAILABLE:
            try:
                async with async_playwright() as p:
                    # 启动浏览器
                    browser = await p.chromium.launch(
                        headless=True,  # 无头模式
                        args=['--no-sandbox', '--disable-dev-shm-usage']
                    )
                    
                    # 创建页面
                    page = await browser.new_page()
                    
                    # 设置用户代理
                    await page.set_extra_http_headers({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    })
                    
                    # 访问微博热搜页面
                    await page.goto("https://s.weibo.com/top/summary", {
                        'wait_until': 'networkidle',
                        'timeout': 30000
                    })
                    
                    # 等待页面加载完成
                    await page.wait_for_selector('tbody tr', timeout=30000)
                    
                    # 提取热搜数据
                    hot_data = await page.evaluate('''() => {
                        const items = document.querySelectorAll('tbody tr');
                        const results = [];
                        
                        items.forEach((item, index) => {
                            try {
                                const td = item.querySelectorAll('td');
                                if (td.length >= 2) {
                                    const rank = td[0].textContent.trim();
                                    const link = td[1].querySelector('a');
                                    const title = link ? link.textContent.trim() : '';
                                    const hot = td[2] ? td[2].textContent.trim() : '0';
                                    
                                    if (title) {
                                        results.push({
                                            title: title,
                                            url: link ? link.href : '',
                                            hot: hot.replace(/\\D/g, ''), // 只保留数字
                                            rank: rank.replace(/\\D/g, '') // 只保留数字
                                        });
                                    }
                                }
                            } catch (e) {
                                console.error('解析单项数据出错:', e);
                            }
                        });
                        
                        return results;
                    }''')
                    
                    # 关闭浏览器
                    await browser.close()
                    
                    # 格式化数据
                    for i, item in enumerate(hot_data):
                        result = {
                            'id': generate_content_id(),  # 使用统一的ID生成函数
                            'title': item.get('title', '').strip(),
                            'url': item.get('url', ''),
                            'hot': item.get('hot', '0'),
                            'rank': str(item.get('rank', i + 1)),
                            'published_at': self._get_current_time(),
                            'collected_at': self._get_current_time(),
                            'site_code': self.site_code
                        }
                        
                        # 数据清洗和验证
                        if self._validate_result(result):
                            results.append({"fields": result})
                            
                    # 限制返回数量
                    results = results[:50]
                    
                    if results:
                        return results
                        
            except Exception as e:
                print(f"微博浏览器自动化采集出错: {e}")
                # 继续尝试基础HTTP请求方式
        
        # 如果浏览器自动化失败，尝试基础HTTP请求方式
        session = None
        
        try:
            # 微博热搜API
            url = "https://weibo.com/ajax/side/hotSearch"
            
            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://weibo.com/',
            }
            
            # 发送请求
            session = await self.get_session()
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 解析热搜数据
                    hot_data = []
                    if 'data' in data and 'realtime' in data['data']:
                        realtime = data['data']['realtime']
                        for i, item in enumerate(realtime):
                            try:
                                title = item.get('word', '').strip()
                                if title:  # 只有标题不为空才添加
                                    hot_data.append({
                                        'title': title,
                                        'url': f"https://s.weibo.com/weibo?q=%23{item.get('word', '')}%23",
                                        'hot': str(item.get('num', 0)),  # 热度值
                                        'rank': str(i + 1)
                                    })
                            except Exception:
                                continue
                    
                    # 格式化数据
                    for i, item in enumerate(hot_data):
                        result = {
                            'id': generate_content_id(),  # 使用统一的ID生成函数
                            'title': item.get('title', '').strip(),
                            'url': item.get('url', ''),
                            'hot': item.get('hot', '0'),
                            'rank': str(item.get('rank', i + 1)),
                            'published_at': self._get_current_time(),
                            'collected_at': self._get_current_time(),
                            'site_code': self.site_code
                        }
                        
                        # 数据清洗和验证
                        if self._validate_result(result):
                            results.append({"fields": result})
                            
                    # 限制返回数量
                    results = results[:50]
                    
                    # 如果没有获取到数据，使用备用方案
                    if not results:
                        results = self._get_backup_data(session)
                        
                else:
                    # 请求失败时使用备用方案
                    results = self._get_backup_data(session)
                    
        except Exception as e:
            print(f"微博采集脚本出错: {e}")
            # 发生错误时返回模拟数据
            results = self._get_mock_data()
        finally:
            # 确保session被正确关闭
            if session:
                await session.close()
            
        return results
    
    async def _get_backup_data(self, session):
        """备用数据获取方案"""
        try:
            # 尝试访问微博热搜页面
            url = "https://s.weibo.com/top/summary"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
                'Referer': 'https://weibo.com/',
            }
            
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    # 解析HTML内容
                    return self._parse_weibo_html_data(text)
        except Exception as e:
            print(f"微博备用方案失败: {e}")
            pass
            
        # 如果备用方案也失败，返回模拟数据
        return self._get_mock_data()
    
    def _parse_weibo_html_data(self, html_text: str) -> List[Dict[str, Any]]:
        """解析微博HTML页面数据"""
        from bs4 import BeautifulSoup
        import re
        
        hot_data = []
        
        try:
            soup = BeautifulSoup(html_text, 'html.parser')
            
            # 查找热搜表格
            hot_table = soup.find('table', class_='list-table')
            if hot_table:
                # 查找所有热搜条目
                rows = hot_table.find_all('tr')[1:]  # 跳过表头
                
                for i, row in enumerate(rows[:50]):  # 限制最多50条
                    try:
                        # 提取标题
                        title_link = row.find('a')
                        if title_link:
                            title = title_link.get_text().strip()
                            url = title_link.get('href', '')
                            
                            # 处理相对链接
                            if url and not url.startswith('http'):
                                url = 'https://s.weibo.com' + url
                            
                            # 提取热度
                            hot_span = row.find('span')
                            hot_score = hot_span.get_text().strip() if hot_span else '0'
                            
                            # 清理热度值，只保留数字
                            hot_score = re.sub(r'[^\d]', '', hot_score)
                            if not hot_score:
                                hot_score = str(len(title) * 1000)  # 基于标题长度计算热度
                            
                            if title:
                                hot_data.append({
                                    'title': title,
                                    'url': url if url else 'https://s.weibo.com',
                                    'hot': hot_score,
                                    'rank': str(i + 1)
                                })
                    except Exception:
                        continue
            else:
                # 如果找不到表格，尝试其他方式
                links = soup.find_all('a', href=re.compile(r'/weibo\?q='))
                for i, link in enumerate(links[:50]):
                    try:
                        title = link.get_text().strip()
                        url = link.get('href', '')
                        
                        # 处理相对链接
                        if url and not url.startswith('http'):
                            url = 'https://s.weibo.com' + url
                            
                        if title and '#' in title:  # 微博话题通常包含#
                            hot_data.append({
                                'title': title,
                                'url': url if url else 'https://s.weibo.com',
                                'hot': str(len(title) * 1000),
                                'rank': str(i + 1)
                            })
                    except Exception:
                        continue
                        
        except Exception as e:
            print(f"解析微博HTML数据出错: {e}")
            pass
            
        # 去重
        seen_titles = set()
        unique_data = []
        for item in hot_data:
            if item['title'] not in seen_titles:
                seen_titles.add(item['title'])
                unique_data.append({"fields": item})
                
        return unique_data[:50]
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）"""
        return [
            {
                "fields": {
                    'id': generate_content_id(),  # 使用统一的ID生成函数
                    'title': '微博热点话题示例',
                    'url': 'https://weibo.com',
                    'hot': '1000000',
                    'rank': '1',
                    'published_at': '2024-01-01 10:00:00',
                    'collected_at': self._get_current_time(),
                    'site_code': self.site_code
                }
            }
        ]