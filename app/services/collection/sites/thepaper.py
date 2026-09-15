"""
澎湃新闻热点采集脚本
"""

import json
import re
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id
# 站点单轮产出上界（唯一事实来源 + 容量守卫）
from ..site_caps import SITE_ROUND_CAPS


# 单轮采集返回的最大条数（容量约束）。
#
# 本值是容量模型里 thepaper 的硬上界，取自**唯一事实来源**
# app/services/collection/site_caps.py 的 SITE_ROUND_CAPS["thepaper"]。
# 该名录在 import 期做容量守卫：
#   · G1 单轮可写性：Σ(各站上界) ≤ limits.WATERMARK；
#   · G2 最坏日上界棘轮：Σ(上界) × 轮次 ≤ ACKNOWLEDGED_WORST_CASE_DAILY(920)。
# ⇒ 调大本值会让 WORST_CASE_DAILY 顶过已裁定基线 → site_caps import 期**直接 raise**，
#   不会再有任何"静默突破"。若确要调大，必须**手工**同步复算
#   limits.RETENTION_DAYS / limits.WATERMARK，并显式更新 ACKNOWLEDGED_WORST_CASE_DAILY。
#
# 名字 MAX_RESULTS 保留不变：tests/test_thepaper_collection.py、
# tests/test_thepaper_feishu_shape.py 均 `from ...thepaper import MAX_RESULTS`。
MAX_RESULTS = SITE_ROUND_CAPS["thepaper"]


class ThepaperSite(BaseSite):
    """澎湃新闻热点采集"""

    # 澎湃首页右侧「热榜」的官方数据接口（返回 JSON，data.hotNews 为真实热榜 20 条，
    # 含 praiseTimes/interactionNum/publishTime）。
    HOT_RANK_API = "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"

    def __init__(self, site_code: str = "thepaper", config: Dict[str, Any] = None):
        super().__init__(site_code, config)
        self.site_code = site_code or "thepaper"
        # 定义澎湃新闻的分类页面URL
        self.category_urls = [
            "https://www.thepaper.cn/list_25422",   # 浦江头条
            "https://www.thepaper.cn/list_25432",   # 自贸区连线
            "https://www.thepaper.cn/list_25600",   # 快看
            "https://www.thepaper.cn/list_25434",   # 10%公司
            "https://www.thepaper.cn/list_122905",  # 大国外交
            "https://www.thepaper.cn/list_25462",   # 中国政库
            "https://www.thepaper.cn/list_25487",   # 教育家
        ]
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集澎湃新闻热点 - 仅采集真实数据，不使用模拟数据"""
        results = []
        session = None
        
        try:
            # 设置更真实的浏览器请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://www.baidu.com/',
                'DNT': '1',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
            }
            
            session = await self.get_session()
            
            # ── 热榜来源 1（首选）：官方热榜 API —— 真实热榜顺序 + 真实互动热度 ──
            # 2026-09 巡检：下方“首页 HTML 解析”三条路径（__NEXT_DATA__ JSON、
            # carousel 等 hash 类名选择器、页面元素兜底）已全部失效（类名 hash
            # 轮换 + 结构变更），旧版每轮热榜 0 条、全靠分类页补量，hot/rank
            # 均为公式伪造。此 API 是澎湃首页自身在用的数据源，失败时自动落回旧路径。
            api_results = await self._fetch_hot_ranking_via_api(session)
            results.extend(api_results)
            
            # ── 热榜来源 2（降级）：首页 HTML 解析（API 不可用时，行为同旧版）──
            if not api_results:
                # 首先访问澎湃新闻主页获取推荐内容
                url = "https://www.thepaper.cn/"
                async with session.get(url, headers=headers, timeout=20) as response:
                    if response.status == 200:
                        text = await response.text()
                        # 使用专门的热榜解析方法
                        homepage_results = self._parse_thepaper_hot_ranking(text)
                        results.extend(homepage_results)
                    else:
                        print(f"澎湃新闻主页请求失败，状态码: {response.status}")
            
            # 然后访问各个分类页面获取更多内容
            category_results = []
            for i, category_url in enumerate(self.category_urls):
                try:
                    # 添加延迟避免请求过于频繁
                    import asyncio
                    await asyncio.sleep(2 + i * 1)  # 增加延迟时间
                    
                    # 为每个分类页面设置特定的Referer
                    category_headers = headers.copy()
                    category_headers['Referer'] = 'https://www.thepaper.cn/'
                    
                    async with session.get(category_url, headers=category_headers, timeout=20) as response:
                        if response.status == 200:
                            text = await response.text()
                            # 解析分类页面内容
                            category_data = self._parse_category_page(text, category_url)
                            category_results.extend(category_data)
                        else:
                            pass  # 忽略分类页面访问失败的情况
                except Exception:
                    continue  # 忽略分类页面访问异常
            
            # 合并热榜和分类页面的结果
            results.extend(category_results)
            
            # 去重处理
            if results:
                results = self._deduplicate_hot_data(results)
                if api_results:
                    # 真热榜：API 顺序即排名；保留真实互动热度，不用公式重算
                    # （旧版 max(50000, ..., 200000-(i-1)*500) 会把真实热度覆盖成
                    #   伪造值，且分类页的公式热度会压过真热榜导致其沉底）
                    for i, item in enumerate(results, 1):
                        item['rank'] = str(i)
                else:
                    # 降级路径：按热度排序 + 公式热度（旧行为）
                    # 按热度排序
                    results.sort(key=lambda x: int(x.get('hot', 0)), reverse=True)
                    # 确保每个项目都有正确的排名
                    for i, item in enumerate(results, 1):
                        item['rank'] = str(i)
                        # 动态调整热度值，确保排名高的新闻热度更高
                        item['hot'] = str(max(50000, int(item['hot']), 200000 - (i - 1) * 500))
                # 限制返回最多 MAX_RESULTS 条数据（容量约束，见模块顶部 MAX_RESULTS）
                results = results[:MAX_RESULTS]
                    
        except Exception as e:
            # 请求失败时记录错误
            print(f"澎湃新闻请求失败: {e}")
        finally:
            # 确保session被正确关闭
            if session:
                await session.close()

        # ⚠️ 返回前**无条件**截断（幂等）；放在 except 之后是关键：
        # 上面的「去重 + 排序 + 热度重算」整块躺在 try 里。一旦
        #   results.sort(key=lambda x: int(x.get('hot', 0))) 遇到非数字 hot → ValueError，或
        #   item['hot'] 缺键 → KeyError，
        # 异常会被上面的 except 吞掉；若不在此处兜底，就会返回**未经截断的全量列表**。
        # 容量模型按本值（MAX_RESULTS）计入 DAILY_BUDGET；本值受 site_caps 守卫约束
        # （G1 单轮 / G2 棘轮，见模块顶部 MAX_RESULTS 注释），
        # 「被守卫依赖的上界」不能带“异常时静默失效”的分支，故 return 前必定再截一次。
        #
        # ⚠️ 返回前**必须**包装成 {"fields": item}：这是飞书批写层
        #    FeishuService._align_records_with_fields 要求的对象形状，该函数对
        #    「缺 'fields' 键」的记录直接 `continue` 跳过（feishu_service.py:305）。
        #    其余 8 个站点（baidu/cctv/people_daily/tech_36kr/weibo/xiaohongshu/zhihu/xinhua）
        #    返回前都做了这层包装，thepaper 此前**漏了它** → 采集到 100 条却「入库 0 条」
        #    （被静默丢弃，无任何日志）。顺序：先按 MAX_RESULTS 截断，再逐条包装（幂等）。
        return [{"fields": item} for item in results[:MAX_RESULTS]]

    async def _fetch_hot_ranking_via_api(self, session) -> List[Dict[str, Any]]:
        """通过官方热榜 API 获取澎湃真实热榜（首选热榜来源）。
        
        Returns:
            热榜记录列表；任何失败（网络/非 200/无 hotNews 字段）一律返回 []，
            由调用方落回「首页 HTML 解析」旧路径。
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.thepaper.cn/',
        }
        try:
            async with session.get(self.HOT_RANK_API, headers=headers, timeout=10) as response:
                if response.status != 200:
                    print(f"澎湃热榜 API 请求失败，状态码: {response.status}，落回首页解析")
                    return []
                data = await response.json()
            hot_news = (data.get('data') or {}).get('hotNews') or []
            if not hot_news:
                print("澎湃热榜 API 返回无 hotNews 数据，落回首页解析")
                return []
            
            results = []
            for i, item in enumerate(hot_news[:50], 1):
                title = (item.get('name') or '').strip()
                cont_id = item.get('contId') or ''
                if not title or not cont_id:
                    continue
                # 真实互动热度：点赞×10 + 互动×5（沿用旧版公式，此前从未拿到过真实数据）
                praise = int(item.get('praiseTimes') or 0)
                interaction = int(item.get('interactionNum') or 0)
                results.append({
                    'id': generate_content_id(),
                    'title': title,
                    'url': f"https://www.thepaper.cn/newsDetail_forward_{cont_id}",
                    'hot': str(praise * 10 + interaction * 5),
                    'rank': str(i),
                    'published_at': item.get('publishTime') or self._get_current_time(),
                    'collected_at': self._get_current_time(),
                    'site_code': self.site_code,
                    'category': '热榜',
                    'content': '',
                    'author': '澎湃新闻',
                    'status': 'collected'
                })
            print(f"澎湃热榜 API 获取到 {len(results)} 条真实热榜")
            return results
        except Exception as e:
            print(f"澎湃热榜 API 调用失败: {e}，落回首页解析")
            return []
    
    def _parse_category_page(self, html_text: str, category_url: str) -> List[Dict[str, Any]]:
        """解析澎湃新闻分类页面内容"""
        from bs4 import BeautifulSoup
        import re
        
        results = []
        try:
            soup = BeautifulSoup(html_text, 'lxml')
            
            # 查找新闻列表项
            news_items = []
            
            # 查找包含新闻的元素
            # 方法1: 查找包含newsDetail_forward链接的元素
            links = soup.find_all('a', href=re.compile(r'/newsDetail_forward_\d+'))
            for link in links:
                title_elem = link.find(['h2', 'div', 'span'], string=True) or link
                title = title_elem.get_text().strip() if title_elem else ''
                if title:
                    href = link.get('href', '')
                    url = f"https://www.thepaper.cn{href}" if href.startswith('/') else href
                    news_items.append({
                        'title': title,
                        'url': url
                    })
            
            # 方法2: 查找包含图片新闻的元素
            img_cards = soup.find_all('div', class_=re.compile(r'.*card.*'))
            for card in img_cards:
                title_elem = card.find(['h2', 'h3'])
                if title_elem:
                    title = title_elem.get_text().strip()
                    link_elem = card.find('a', href=re.compile(r'/newsDetail_forward_\d+'))
                    if link_elem:
                        href = link_elem.get('href', '')
                        url = f"https://www.thepaper.cn{href}" if href.startswith('/') else href
                        news_items.append({
                            'title': title,
                            'url': url
                        })
            
            # 处理找到的新闻项
            processed_titles = set()
            for i, item in enumerate(news_items[:50]):  # 每个分类页面最多处理50条
                title = item.get('title', '').strip()
                url = item.get('url', '')
                
                # 避免重复和无效项
                if not title or not url or title in processed_titles:
                    continue
                processed_titles.add(title)
                
                if self._is_valid_news(title, url):
                    content_id = generate_content_id()
                    # 根据位置计算热度值，前面的新闻热度更高
                    hot_value = max(50000, 150000 - i * 1000)
                    results.append({
                        'id': content_id,
                        'title': title,
                        'url': self._normalize_url(url),
                        'hot': str(hot_value),
                        'rank': str(len(results) + 1),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code,
                        'category': '分类新闻',
                        'content': '',        
                        'author': '澎湃新闻',
                        'status': 'collected'
                    })
                    
        except Exception as e:
            print(f"解析分类页面 {category_url} 出错: {e}")
            import traceback
            traceback.print_exc()
            
        return results

    def _parse_thepaper_hot_ranking(self, html_text: str) -> List[Dict[str, Any]]:
        """专门解析澎湃新闻热榜 - 根据最新网站结构优化解析逻辑"""
        from bs4 import BeautifulSoup
        import re
        import json
        
        hot_data = []
        
        try:
            # 使用lxml解析器以提高性能和兼容性
            soup = BeautifulSoup(html_text, 'lxml')
            
            # 主要策略: 从页面的JSON数据中提取热榜数据
            print("尝试从页面JSON数据中提取热榜数据")
            # 查找包含推荐内容的JSON数据
            script_pattern = re.compile(r'window\.__NEXT_DATA__\s*=\s*({.*?});', re.DOTALL)
            script_match = script_pattern.search(html_text)
            if script_match:
                try:
                    json_data = json.loads(script_match.group(1))
                    # 从JSON数据中提取推荐内容
                    props_data = json_data.get('props', {})
                    page_props = props_data.get('pageProps', {})
                    data = page_props.get('data', {})
                    
                    # 尝试不同的数据字段，特别是recommendImg字段
                    hot_list_data = []
                    if 'recommendImg' in data and data['recommendImg']:
                        hot_list_data.extend(data['recommendImg'])
                        print(f"从recommendImg字段提取到 {len(data['recommendImg'])} 个热榜项目")
                    if 'recommendTxt' in data and data['recommendTxt']:
                        # 处理recommendTxt字段，它是一个二维数组
                        recommend_txt = data['recommendTxt']
                        txt_count = 0
                        # 将二维数组扁平化为一维数组
                        for sublist in recommend_txt:
                            if isinstance(sublist, list):
                                txt_count += len(sublist)
                                hot_list_data.extend(sublist)
                            else:
                                txt_count += 1
                                hot_list_data.append(sublist)
                        print(f"从recommendTxt字段提取到 {txt_count} 个热榜项目")
                    
                    # 从contentList中提取数据
                    if 'recommendChannels' in data and data['recommendChannels']:
                        for channel in data['recommendChannels']:
                            if 'contentList' in channel and channel['contentList']:
                                hot_list_data.extend(channel['contentList'])
                        print(f"从recommendChannels字段提取到额外项目，当前总数: {len(hot_list_data)}")
                    
                    # 从listRecommendIds中提取数据
                    if 'listRecommendIds' in data and data['listRecommendIds']:
                        list_recommend = data['listRecommendIds']
                        if isinstance(list_recommend, list):
                            hot_list_data.extend(list_recommend)
                        print(f"从listRecommendIds字段提取到额外项目，当前总数: {len(hot_list_data)}")
                    
                    # 从financialInformationNews中提取数据
                    if 'financialInformationNews' in data and data['financialInformationNews']:
                        financial_news = data['financialInformationNews']
                        if isinstance(financial_news, list):
                            hot_list_data.extend(financial_news)
                        print(f"从financialInformationNews字段提取到额外项目，当前总数: {len(hot_list_data)}")
                    
                    # 从noImgRecommend中提取数据
                    if 'noImgRecommend' in data and data['noImgRecommend']:
                        no_img_recommend = data['noImgRecommend']
                        if isinstance(no_img_recommend, list):
                            hot_list_data.extend(no_img_recommend)
                        print(f"从noImgRecommend字段提取到额外项目，当前总数: {len(hot_list_data)}")
                    
                    # 从excludeContIds中提取数据（这些是需要排除的ID）
                    exclude_ids = set()
                    if 'excludeContIds' in data and data['excludeContIds']:
                        exclude_ids = set(data['excludeContIds'])
                        print(f"从excludeContIds字段找到 {len(exclude_ids)} 个排除项")
                    
                    # 遍历data中的所有键值对，查找可能包含新闻数据的列表
                    additional_fields = []
                    for key, value in data.items():
                        if isinstance(value, list) and len(value) > 0:
                            # 检查列表中的元素是否为字典且包含新闻相关字段
                            if len(value) > 0 and isinstance(value[0], dict) and ('contId' in value[0] or 'name' in value[0] or 'title' in value[0]):
                                # 避免重复添加已处理过的字段
                                if key not in ['recommendImg', 'recommendTxt', 'contentList', 'listRecommendIds', 
                                               'financialInformationNews', 'noImgRecommend', 'excludeContIds']:
                                    additional_fields.append(key)
                                    hot_list_data.extend(value)
                                    print(f"从{key}字段提取到额外项目，当前总数: {len(hot_list_data)}")
                    
                    # 特别处理nodeInfo字段
                    if 'nodeInfo' in data and data['nodeInfo']:
                        node_info = data['nodeInfo']
                        if 'recommendList' in node_info and node_info['recommendList']:
                            hot_list_data.extend(node_info['recommendList'])
                            print(f"从nodeInfo.recommendList字段提取到额外项目，当前总数: {len(hot_list_data)}")
                    
                    if additional_fields:
                        print(f"从以下额外字段提取数据: {', '.join(additional_fields)}")
                    
                    if hot_list_data and isinstance(hot_list_data, list):
                        print(f"从JSON数据中总共提取到 {len(hot_list_data)} 个热榜项目")
                        processed_items = set()  # 用于去重
                        valid_items_count = 0
                        for i, item in enumerate(hot_list_data[:200], 1):  # 限制最多200个
                            # 处理不同格式的数据
                            if isinstance(item, dict):
                                title = item.get('name', '') or item.get('title', '') or item.get('originalName', '')
                                cont_id = item.get('contId', '') or item.get('id', '')
                                
                                # 如果cont_id在排除列表中，则跳过
                                if cont_id and cont_id in exclude_ids:
                                    continue
                                
                                url = f"/newsDetail_forward_{cont_id}" if cont_id else item.get('link', '') or item.get('url', '')
                                
                                # 避免重复项 - 使用更宽松的去重策略
                                item_key = title.strip()
                                if item_key in processed_items or not item_key:
                                    continue
                                processed_items.add(item_key)
                                
                                if self._is_valid_news(title, url):
                                    valid_items_count += 1
                                    content_id = generate_content_id()
                                    
                                    # 计算热度值，考虑点赞数、评论数等
                                    praise_times = int(item.get('praiseTimes', 0) or 0)
                                    interaction_num = int(item.get('interactionNum', 0) or 0)
                                    base_hot = praise_times * 10 + interaction_num * 5
                                    hot_value = max(50000, base_hot, 200000 - (valid_items_count-1) * 800)
                                    
                                    hot_data.append({
                                        'id': content_id,
                                        'title': title.strip(),
                                        'url': self._normalize_url(url),
                                        'hot': str(hot_value),
                                        'rank': str(valid_items_count),
                                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        'collected_at': self._get_current_time(),
                                        'site_code': self.site_code,
                                        'category': '热榜',
                                        'content': '',        
                                        'author': '澎湃新闻',
                                        'status': 'collected'
                                    })
                                    # 如果已经收集到足够多的数据，就停止
                                    if valid_items_count >= 50:
                                        break
                    
                    # 如果从JSON中没有提取到足够的数据，则尝试从页面元素中提取
                    if len(hot_data) < 30:
                        print("从JSON数据中提取的数据不足，尝试从页面元素中提取")
                        hot_data.extend(self._extract_from_page_elements(soup))
                        
                except Exception as e:
                    print(f"解析JSON数据出错: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 如果还没有数据，则尝试从carousel区域提取
            if len(hot_data) < 25:
                print("数据仍然不足，尝试从carousel区域提取")
                hot_data.extend(self._extract_from_page_elements(soup))
            
            # 去重处理
            if hot_data:
                original_count = len(hot_data)
                hot_data = self._deduplicate_hot_data(hot_data)
                deduplicated_count = len(hot_data)
                print(f"去重前 {original_count} 条，去重后 {deduplicated_count} 条")
                
                # 按热度排序
                hot_data.sort(key=lambda x: int(x.get('hot', 0)), reverse=True)
                # 确保每个项目都有正确的排名
                for i, item in enumerate(hot_data, 1):
                    item['rank'] = str(i)
                    # 动态调整热度值，确保排名高的新闻热度更高
                    item['hot'] = str(max(50000, int(item['hot']), 200000 - (i - 1) * 1000))
                # 限制返回最多50条数据
                hot_data = hot_data[:50]
            
            print(f"解析完成，共获取 {len(hot_data)} 条澎湃新闻热榜数据")
            
        except Exception as e:
            # 解析失败时记录详细错误
            print(f"解析澎湃新闻热榜数据出错: {e}")
            import traceback
            traceback.print_exc()
            
        # 仅返回实际采集到的真实数据
        return hot_data

    def _extract_from_page_elements(self, soup) -> List[Dict[str, Any]]:
        """从页面元素中提取热榜数据 - 作为备选方案"""
        hot_list = []
        try:
            # 查找carousel区域
            carousel_items = soup.select('.index_carousel_img__HbOWM')
            print(f"从carousel区域找到 {len(carousel_items)} 个项目")
            
            # 查找右侧边栏
            sidebar_items = soup.select('.index_vscrollBlock__l0Q3G')
            print(f"从右侧边栏找到 {len(sidebar_items)} 个项目")
            
            # 查找推荐区域
            recommend_items = soup.select('.index_recommend__a7gig h2')
            print(f"从推荐区域找到 {len(recommend_items)} 个项目")
            
            # 查找更多推荐区域
            more_recommend_items = soup.select('.small_cardcontent__BTALp h2')
            print(f"从更多推荐区域找到 {len(more_recommend_items)} 个项目")
            
            # 查找新闻列表区域
            news_list_items = soup.select('.index_scrolllist__A8MtY a')
            print(f"从新闻列表区域找到 {len(news_list_items)} 个项目")
            
            # 处理carousel区域的项目
            processed_titles = set()
            valid_count = 0
            
            # 处理carousel区域
            for element in carousel_items:
                if valid_count >= 30:
                    break
                    
                # 提取图片的alt属性作为标题
                img_elem = element.find('img')
                if img_elem and img_elem.get('alt'):
                    title = img_elem.get('alt').strip()
                else:
                    continue
                
                # 提取链接
                link_elem = element.find('a', href=True)
                if link_elem:
                    url = link_elem.get('href')
                    if url.startswith('/'):
                        url = f"https://www.thepaper.cn{url}"
                else:
                    continue
                
                # 验证并添加数据
                if title and title not in processed_titles and self._is_valid_news(title, url):
                    processed_titles.add(title)
                    valid_count += 1
                    content_id = generate_content_id()
                    hot_list.append({
                        'id': content_id,
                        'title': title,
                        'url': self._normalize_url(url),
                        'hot': str(max(50000, 180000 - valid_count * 2000)),
                        'rank': str(valid_count),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code,
                        'category': '页面元素',
                        'content': '',
                        'author': '澎湃新闻',
                        'status': 'collected'
                    })
            
            # 处理右侧边栏
            for element in sidebar_items:
                if valid_count >= 30:
                    break
                    
                # 提取标题
                title = element.get_text().strip()
                
                # 提取链接
                link_elem = element.find_parent('a')
                if link_elem and link_elem.get('href'):
                    url = link_elem.get('href')
                    if url.startswith('/'):
                        url = f"https://www.thepaper.cn{url}"
                else:
                    continue
                
                # 验证并添加数据
                if title and title not in processed_titles and self._is_valid_news(title, url):
                    processed_titles.add(title)
                    valid_count += 1
                    content_id = generate_content_id()
                    hot_list.append({
                        'id': content_id,
                        'title': title,
                        'url': self._normalize_url(url),
                        'hot': str(max(50000, 180000 - valid_count * 2000)),
                        'rank': str(valid_count),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code,
                        'category': '页面元素',
                        'content': '',
                        'author': '澎湃新闻',
                        'status': 'collected'
                    })
            
            # 处理其他区域的元素
            all_other_elements = []
            all_other_elements.extend(recommend_items)
            all_other_elements.extend(more_recommend_items)
            all_other_elements.extend(news_list_items)
            
            for element in all_other_elements:
                if valid_count >= 30:
                    break
                    
                # 提取标题
                title = element.get_text().strip()
                
                # 提取链接
                link_elem = element.find_parent('a')
                if link_elem and link_elem.get('href'):
                    url = link_elem.get('href')
                    if url.startswith('/'):
                        url = f"https://www.thepaper.cn{url}"
                else:
                    continue
                
                # 验证并添加数据
                if title and title not in processed_titles and self._is_valid_news(title, url):
                    processed_titles.add(title)
                    valid_count += 1
                    content_id = generate_content_id()
                    hot_list.append({
                        'id': content_id,
                        'title': title,
                        'url': self._normalize_url(url),
                        'hot': str(max(50000, 180000 - valid_count * 2000)),
                        'rank': str(valid_count),
                        'published_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'collected_at': self._get_current_time(),
                        'site_code': self.site_code,
                        'category': '页面元素',
                        'content': '',
                        'author': '澎湃新闻',
                        'status': 'collected'
                    })
                    
        except Exception as e:
            print(f"从页面元素提取数据时出错: {e}")
            import traceback
            traceback.print_exc()
            
        return hot_list

    def _is_valid_news(self, title: str, url: str) -> bool:
        """验证新闻标题和URL是否有效"""
        # 检查标题
        if not title or not title.strip() or len(title.strip()) < 4:
            return False
            
        # 检查URL
        if not url or not url.strip():
            return False
            
        # 检查是否为有效的新闻链接
        if 'newsDetail_forward' not in url and not url.startswith('http'):
            return False
            
        return True

    def _normalize_url(self, url: str) -> str:
        """标准化URL"""
        if not url:
            return ''
            
        if url.startswith('//'):
            return f"https:{url}"
        elif url.startswith('/'):
            return f"https://www.thepaper.cn{url}"
        elif url.startswith('http'):
            return url
        else:
            return f"https://www.thepaper.cn/{url}"

    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _deduplicate_hot_data(self, hot_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """对热榜数据进行去重处理"""
        if not hot_data:
            return hot_data
            
        # 使用标题作为去重依据
        seen_titles = set()
        deduplicated_data = []
        
        for item in hot_data:
            title = item.get('title', '').strip()
            if title and title not in seen_titles:
                seen_titles.add(title)
                deduplicated_data.append(item)
                
        return deduplicated_data
