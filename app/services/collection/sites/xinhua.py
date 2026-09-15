"""
新华网热点采集脚本
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

# xinhua 的【终】上界：仅用于下方「去重后的 `unique_data[:30]`」。
# ⚠️ `unique_items[:100]`（候选池）与 `processed_count >= 50`（早停）是【预】/【阈】，
#     **不在**容量模型内，保持原样。
_MAX = SITE_ROUND_CAPS["xinhua"]


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
            # 采集失败 → 唯一回退入口：生产默认**不伪造**（返回空 + 告警）。
            # 传 callable（self._get_mock_data）惰性求值：默认路径根本不构造假数据。
            results = fallback_or_empty(self.site_code, f"collect 异常: {e}", self._get_mock_data)
            
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
                    
                    # 过滤明显截断的标题（以冒号结尾）：新华首页专题卡片的引题
                    # 常以「武汉昙华林：」形式出现（主标题在图片上取不到）
                    if title.rstrip().endswith(('：', ':')):
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
            
        # 如果没有解析到数据，走唯一回退入口（生产默认返回空、不伪造）
        if not hot_data:
            hot_data = fallback_or_empty(
                self.site_code, "解析结果为空（选择器未命中/页面结构变化）", self._get_mock_data
            )
        else:
            # 再次去重，基于标题
            seen_titles = set()
            unique_data = []
            for item in hot_data:
                if item['title'] not in seen_titles:
                    seen_titles.add(item['title'])
                    unique_data.append(item)
            hot_data = unique_data[:_MAX]  # 限制最多 _MAX 条（容量上界，见 site_caps）
            
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

            # 关键：本段「按固定键重建 result」会把 _get_mock_data() 打的 mock 标记抹掉。
            # 当解析路径回退到 mock（上方 `hot_data = fallback_or_empty(..., self._get_mock_data)`，
            # 仅 opt-in 时才返回带标记的 mock）时，必须把标记**透传**回来，否则 mock 在这里被
            #「洗白」成普通记录 → 静默混入写集（这是 xinhua 解析路径的潜在泄漏点，
            # 见 mock_utils.py 模块注释）。
            if item.get(MOCK_FLAG) is True:
                result[MOCK_FLAG] = True

            # 数据清洗和验证
            if self._validate_result(result):
                results.append({"fields": result})
                
        return results
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）。

        ⚠️ 演示数据**绝不允许进入飞书表**。每条都显式打 `is_mock=True` 标记：
        写入层（script/collection_pipeline.py）用 split_real_and_mock() 按此标记把
        mock 行排除出写集，而**不是**依赖「mock 恰好没被包成 {'fields': item}」
        这个 bug 来兜底（见 mock_utils.py）。
        """
        return [
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '新华社热点新闻示例',
                'url': 'https://www.xinhuanet.com',
                'hot': '500000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code,
                MOCK_FLAG: True,  # mock 显式标记，禁止入库
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '新华社时政要闻示例',
                'url': 'https://www.xinhuanet.com',
                'hot': '300000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code,
                MOCK_FLAG: True,  # mock 显式标记，禁止入库
            }
        ]