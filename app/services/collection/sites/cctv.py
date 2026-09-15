"""
央视新闻热点采集脚本
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id
# mock 行的显式标记（见 app/services/collection/mock_utils.py）。
# 目的：让「mock 不得入库」由**意图**保证，而不是靠「忘了给 mock 包 fields 这个 bug」。
# 有测试锁：tests/test_mock_governance.py（动态枚举所有含 _get_mock_data 的站点）。
from ..mock_utils import MOCK_FLAG, fallback_or_empty
# 站点单轮产出上界（唯一事实来源：app/services/collection/site_caps.py）
from ..site_caps import SITE_ROUND_CAPS

# cctv 的【终】上界：仅用于下方「去重后的 `unique_data[:50]`」。
# ⚠️ `news_items[:50]`（解析遍历）是【预】上限，**不在**容量模型内，保持原样。
_MAX = SITE_ROUND_CAPS["cctv"]


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
            # 采集失败 → 唯一回退入口（生产默认返回空、不伪造）
            results = fallback_or_empty(self.site_code, f"collect 异常: {e}", self._get_mock_data)
            
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
        seen_urls = set()  # 同一篇文章的「标题链接/图片链接」只保留第一条（后者常取到正文句子）
        
        try:
            soup = BeautifulSoup(html_text, 'html.parser')
            
            # 查找新闻条目，使用更精确的选择器
            # 查找包含新闻链接的元素
            news_items = soup.find_all(['a'], href=re.compile(r'.*\.shtml'))
            
            # 预筛上限 200（非容量上界——终截断由 unique_data[:_MAX] 把守）：
            # 央视首页 .shtml 链接中栏目入口/专题入口占大头，预筛 50 时
            # 过滤后仅剩个位数真新闻（2026-09 实测 6 条）
            for item in news_items[:200]:  # 限制最多200条
                try:
                    # 提取标题
                    title = item.get_text().strip()
                    
                    # 提取链接
                    url = item.get('href', '')
                    
                    # 过滤栏目入口页（index.shtml）：其链接文本是栏目名
                    # （如“央视快评”“小央画话”），不是新闻标题
                    # （2026-09 巡检：22 条中 13 条为栏目名）
                    if 'index.shtml' in url:
                        continue
                    
                    # 过滤无效标题
                    if not title or len(title) < 4 or 'href' in title:
                        continue
                    
                    # URL 去重：同一篇文章只保留第一个通过过滤的链接
                    # （央视首页同一文章常有标题链接+图片链接两个入口，
                    #   图片链接的 get_text() 会取到正文首句）
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
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
                        'rank': str(len(hot_data) + 1),
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
            
        # 如果没有解析到数据，走唯一回退入口（生产默认返回空、不伪造）
        if not hot_data:
            hot_data = fallback_or_empty(
                self.site_code, "解析结果为空（选择器未命中/页面结构变化）", self._get_mock_data
            )
        else:
            # 去重，基于标题
            seen_titles = set()
            unique_data = []
            for item in hot_data:
                if item['title'] not in seen_titles:
                    seen_titles.add(item['title'])
                    unique_data.append(item)
            hot_data = unique_data[:_MAX]  # 限制最多 _MAX 条（容量上界，见 site_caps）
            
        return hot_data
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）。

        ⚠️ 演示数据**绝不允许进入飞书表**。每条显式打 `is_mock=True` 标记：
        本函数返回**扁平**行，collect() 在 format=='feishu' 时再包成
        {"fields": item} —— 故标记落在**内层 dict**，包装后仍被 is_mock_record 识别。
        """
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
                'status': 'collected',
                MOCK_FLAG: True,  # mock 显式标记，禁止入库
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
                'status': 'collected',
                MOCK_FLAG: True,  # mock 显式标记，禁止入库
            }
        ]