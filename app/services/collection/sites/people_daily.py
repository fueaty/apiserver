"""
人民网热点采集脚本
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id
# mock 行的显式标记（见 app/services/collection/mock_utils.py）。
# 目的：让「mock 不得入库」由**意图**保证，而不是靠「忘了给 mock 包 fields 这个 bug」。
# 有测试锁：tests/test_mock_governance.py。
from ..mock_utils import MOCK_FLAG, fallback_or_empty
# 站点单轮产出上界（唯一事实来源：app/services/collection/site_caps.py）
from ..site_caps import SITE_ROUND_CAPS

# people_daily 的【终】上界：`find_all('item')[:50]` 无独立终截断，**兼作最终上界**。
_MAX = SITE_ROUND_CAPS["people_daily"]

# RSS 时效守卫阈值：最新一条 pubDate 距今超过该天数即视为源失效（停更）。
# 背景（2026-09 巡检）：politics.xml 停更于 2025-06-05，旧代码无时效校验，
# 天天“成功”写回 15 个月前的 50 条旧闻。宁可 0 条 + 告警，不要旧数据。
_STALE_DAYS = 7


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
                    # 请求失败 → 唯一回退入口（生产默认返回空、不伪造）
                    results = fallback_or_empty(
                        self.site_code, f"HTTP 状态码 {response.status}", self._get_mock_data)
            
            # ── 时效守卫：RSS 停更时不再采回旧闻，降级为爬人民网首页 ──
            if results and self._is_stale(results):
                print(f"[people_daily] 时效守卫触发：RSS 最新条目距今超过 {_STALE_DAYS} 天，"
                      f"疑似源停更，弃用 {len(results)} 条旧数据，降级为首页爬取")
                results = await self._collect_via_homepage(session)
                    
        except Exception as e:
            # 采集失败 → 唯一回退入口（生产默认返回空、不伪造）
            results = fallback_or_empty(self.site_code, f"collect 异常: {e}", self._get_mock_data)
            
        return results
    
    @staticmethod
    def _parse_pub_date(s: str):
        """解析 RSS pubDate（兼容 'YYYY-MM-DD HH:MM:SS' 与 'YYYY-MM-DD' 两种格式）。"""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def _is_stale(self, results: List[Dict[str, Any]]) -> bool:
        """判断本批 RSS 结果是否整体过期（最新 pubDate 距今超过 _STALE_DAYS 天）。"""
        newest = None
        for item in results:
            fields = item.get('fields') or {}
            pub = self._parse_pub_date(str(fields.get('published_at') or ''))
            if pub and (newest is None or pub > newest):
                newest = pub
        if newest is None:
            # 解析不出任何时间（如 RSS 格式变化）→ 不拦截，维持旧行为
            return False
        return (datetime.now() - newest).days > _STALE_DAYS
    
    async def _collect_via_homepage(self, session) -> List[Dict[str, Any]]:
        """RSS 失效时的降级路径：爬人民网首页当年文章链接（与 xinhua 首页采集同模式）。
        
        只认 `/n1/<当年>/MM/DD/` 形态的文章链接，旧专题/旧文章一律排除。
        任何失败返回空列表（不伪造），由 pipeline 的站点级缺口告警兜底。
        """
        from bs4 import BeautifulSoup
        import re
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        }
        
        try:
            async with session.get("http://www.people.com.cn/", headers=headers, timeout=15) as response:
                if response.status != 200:
                    print(f"[people_daily] 首页爬取失败，状态码: {response.status}")
                    return []
                text = await response.text()
        except Exception as e:
            print(f"[people_daily] 首页爬取异常: {e}")
            return []
        
        hot_data = []
        seen_urls = set()
        try:
            soup = BeautifulSoup(text, 'html.parser')
            year = datetime.now().year
            # 只认「当年」的文章链接。人民网文章 URL 形态：
            # /n1/2026/0914/c461529-40797890.html（月日合并为一段 4 位数字）
            pat = re.compile(r'/n1/%d/' % year)
            for a in soup.find_all('a', href=pat):
                try:
                    url = a.get('href', '')
                    title = a.get_text().strip()
                    if not title or len(title) < 6 or len(title) > 100:
                        continue
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    if not url.startswith('http'):
                        url = 'http://www.people.com.cn' + url
                    hot_data.append({
                        'id': generate_content_id(),
                        'title': title,
                        'url': url,
                        'hot': str(len(title)),
                        'rank': str(len(hot_data) + 1),
                        'published_at': self._get_current_time(),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code
                    })
                    if len(hot_data) >= _MAX:
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"[people_daily] 首页解析异常: {e}")
        
        print(f"[people_daily] 首页爬取到 {len(hot_data)} 条当年文章")
        return [{"fields": item} for item in hot_data]
    
    def _parse_people_daily_data(self, xml_text: str) -> List[Dict[str, Any]]:
        """解析人民网热点数据"""
        from bs4 import BeautifulSoup
        import re
        
        hot_data = []
        
        try:
            soup = BeautifulSoup(xml_text, 'xml')
            items = soup.find_all('item')[:_MAX]  # 限制最多 _MAX 条（容量上界，见 site_caps）
            
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
        """获取模拟数据（用于演示或备用）。

        ⚠️ 演示数据**绝不允许进入飞书表**。每条都显式打 `is_mock=True` 标记，
        写入层按标记排除（见 mock_utils.py），不依赖「mock 恰好没被包 fields」这个 bug。
        """
        return [
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '人民网热点新闻示例',
                'url': 'http://www.people.com.cn',
                'hot': '500000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code,
                MOCK_FLAG: True,  # mock 显式标记，禁止入库
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '人民网时政要闻示例',
                'url': 'http://www.people.com.cn',
                'hot': '300000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code,
                MOCK_FLAG: True,  # mock 显式标记，禁止入库
            }
        ]