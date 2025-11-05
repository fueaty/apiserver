"""
小红书热门话题采集脚本
基于网页版Cookie进行身份验证实现
"""

import json
import re
import asyncio
from typing import List, Dict, Any
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import yaml
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id


class XiaohongshuSite(BaseSite):
    """小红书热门话题采集"""
    
    def __init__(self, site_code: str, config: Dict[str, Any]):
        super().__init__(site_code, config)
        self.load_xiaohongshu_config()
    
    def load_xiaohongshu_config(self):
        """加载小红书专用配置"""
        try:
            config_path = "/root/apiserver/config/xiaohongshu.yaml"
            with open(config_path, 'r', encoding='utf-8') as f:
                self.xhs_config = yaml.safe_load(f)
        except Exception as e:
            print(f"加载小红书配置文件失败: {e}")
            self.xhs_config = {}
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集小红书热门话题"""
        results = []
        
        try:
            # 直接通过网页解析方式获取数据
            web_results = await self._collect_via_web()
            if web_results and len(web_results) > 0:
                # 检查是否为模拟数据
                if not self._is_mock_data(web_results):
                    #print("返回真实采集数据")
                    # 格式化为统一的数据结构
                    formatted_results = []
                    for item in web_results:
                        formatted_results.append({
                            "fields": item
                        })
                    return formatted_results
                else:
                    print("网页采集结果为模拟数据")
            else:
                print("网页采集结果为空")
            
            # 如果网页解析方式失败，返回模拟数据
            print("返回模拟数据")
            mock_data = self._get_mock_data()
            formatted_results = []
            for item in mock_data:
                formatted_results.append({
                    "fields": item
                })
            return formatted_results
                    
        except Exception as e:
            print(f"小红书采集脚本出错: {e}")
            # 发生错误时返回模拟数据
            mock_data = self._get_mock_data()
            formatted_results = []
            for item in mock_data:
                formatted_results.append({
                    "fields": item
                })
            return formatted_results
    
    async def _collect_via_web(self) -> List[Dict[str, Any]]:
        """通过网页方式采集小红书热门话题"""
        results = []
        session = None
        
        try:
            # 获取配置中的cookie
            cookie = self.xhs_config.get('cookie', {}).get('auth', '')
            if not cookie:
                print("未配置小红书Cookie")
                return []
            
            # 尝试访问小红书探索页面
            url = "https://www.xiaohongshu.com/explore"
            
            # 设置请求头，模拟浏览器行为
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36',
                'Referer': 'https://www.xiaohongshu.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
                'Connection': 'keep-alive',
                'Cookie': cookie
            }
            
            # 发送请求
            session = await self.get_session()
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    text = await response.text()
                    # print(f"成功获取页面内容，长度: {len(text)}")
                    # 解析HTML内容，提取话题数据
                    results = self._parse_xiaohongshu_html_data(text)
                        
        except Exception as e:
            # print(f"小红书网页采集方式出错: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 确保session被正确关闭
            if session:
                await session.close()
                
        return results
    
    def _clean_json_string(self, json_str):
        """清理并修复JSON字符串"""
        # 移除注释
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
        
        # 替换HTML实体
        json_str = json_str.replace('\\u002F', '/').replace('\\u003C', '<').replace('\\u003E', '>').replace('\\u0026', '&')
        
        # 修复转义字符
        json_str = re.sub(r'\\\\', r'\\', json_str)
        json_str = re.sub(r'\\([^"\\/bfnrtu])', r'\1', json_str)
        
        # 修复多余的逗号
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        # 移除可能的BOM
        if json_str.startswith('\ufeff'):
            json_str = json_str[1:]
            
        # 移除末尾可能的无效字符
        json_str = re.sub(r'}\s*[^\s}]*$', '}', json_str)
            
        return json_str.strip()
    
    def _extract_json_with_multiple_methods(self, html_text):
        """使用多种方法尝试提取和解析JSON数据"""
        # 方法1: 标准的__INITIAL_STATE__提取
        json_pattern1 = r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*<'
        match1 = re.search(json_pattern1, html_text, re.DOTALL)
        
        if match1:
            try:
                json_str = self._clean_json_string(match1.group(1))
                # 替换undefined为null
                json_str = re.sub(r'\bundefined\b', 'null', json_str)
                return json.loads(json_str)
            except Exception as e1:
                pass
        
        # 方法2: 更宽松的匹配
        json_pattern2 = r'window\.__INITIAL_STATE__\s*=\s*({.*?})(?:\s*;|\s*<)'
        match2 = re.search(json_pattern2, html_text, re.DOTALL)
        
        if match2:
            try:
                json_str = self._clean_json_string(match2.group(1))
                # 替换undefined为null
                json_str = re.sub(r'\bundefined\b', 'null', json_str)
                return json.loads(json_str)
            except Exception as e2:
                pass
                
        # 方法3: 匹配到脚本结束
        json_pattern3 = r'window\.__INITIAL_STATE__\s*=\s*({.*?});?\s*</script>'
        match3 = re.search(json_pattern3, html_text, re.DOTALL)
        
        if match3:
            try:
                json_str = self._clean_json_string(match3.group(1))
                # 替换undefined为null
                json_str = re.sub(r'\bundefined\b', 'null', json_str)
                return json.loads(json_str)
            except Exception as e3:
                pass
                
        # 方法4: 匹配整个对象
        json_pattern4 = r'window\.__INITIAL_STATE__\s*=\s*(\{(?:[^{}]|(?1))*\})'
        match4 = re.search(json_pattern4, html_text, re.DOTALL)
        
        if match4:
            try:
                json_str = self._clean_json_string(match4.group(1))
                # 替换undefined为null
                json_str = re.sub(r'\bundefined\b', 'null', json_str)
                return json.loads(json_str)
            except Exception as e4:
                pass
                
        return None
    
    def _parse_xiaohongshu_html_data(self, html_text: str) -> List[Dict[str, Any]]:
        """解析小红书页面数据，专门提取热门话题"""
        hot_data = []
        results = []
        
        try:
            # 尝试解析JSON数据
            json_data = self._extract_json_with_multiple_methods(html_text)
            
            if json_data:
                # print("JSON解析成功")
                # 提取推荐笔记数据
                feeds = []
                
                # 尝试多种可能的路径获取feeds
                if 'recommendFeeds' in json_data:
                    feeds = json_data['recommendFeeds']
                elif 'home' in json_data and 'recommendFeeds' in json_data['home']:
                    feeds = json_data['home']['recommendFeeds']
                elif 'main' in json_data and 'recommendFeeds' in json_data['main']:
                    feeds = json_data['main']['recommendFeeds']
                elif 'feeds' in json_data:
                    feeds = json_data['feeds']
                else:
                    # 遍历顶层键值寻找包含feeds的结构
                    for key, value in json_data.items():
                        if isinstance(value, dict) and 'feeds' in value:
                            feeds = value['feeds']
                            break
                        elif isinstance(value, dict) and 'recommendFeeds' in value:
                            feeds = value['recommendFeeds']
                            break
                
                # print(f"找到 {len(feeds)} 条笔记数据")
                
                # 处理推荐笔记数据
                for i, feed in enumerate(feeds[:30]):  # 限制最多30条
                    try:
                        # 获取笔记卡片信息
                        note_card = feed.get('noteCard') or feed.get('note_card') or feed
                        
                        # 获取标题
                        title = note_card.get('displayTitle', '').strip()
                        if not title:
                            title = note_card.get('title', '').strip()
                        
                        # 获取作者信息
                        user_info = note_card.get('user', {})
                        user_name = user_info.get('nickname', '').strip()
                        
                        # 构造完整标题
                        if user_name and title:
                            full_title = f"{title} by {user_name}"
                        elif title:
                            full_title = title
                        else:
                            continue
                        
                        # 获取笔记ID和链接
                        note_id = (note_card.get('noteId') or 
                                 note_card.get('note_id') or 
                                 note_card.get('id') or
                                 feed.get('noteId') or
                                 feed.get('note_id') or
                                 feed.get('id') or
                                 '')
                        
                        xsec_token = (feed.get('xsecToken') or
                                    feed.get('xsec_token') or
                                    note_card.get('xsecToken') or
                                    note_card.get('xsec_token') or
                                    '')
                        
                        if note_id and xsec_token:
                            url = f'https://www.xiaohongshu.com/discovery/item/{note_id}?xsec_token={xsec_token}&xsec_source='
                        elif note_id:
                            url = f'https://www.xiaohongshu.com/discovery/item/{note_id}'
                        else:
                            # 如果没有note_id，则跳过该条目
                            continue
                        
                        # 获取点赞数
                        interact_info = note_card.get('interactInfo') or note_card.get('interact_info') or {}
                        liked_count = str(interact_info.get('likedCount') or interact_info.get('liked_count', '0'))
                        
                        # 处理热度值
                        hot_text = liked_count
                        hot_value = 0
                        
                        if isinstance(hot_text, str):
                            # 处理包含"万"的热度值，如"5.1万"或"1.7万"或"2.4万"
                            if '万' in hot_text:
                                try:
                                    # 先移除"万"字，然后转换为浮点数，再乘以10000
                                    hot_value = int(float(hot_text.replace('万', '')) * 10000)
                                except ValueError:
                                    hot_value = 0
                            elif '千' in hot_text:
                                # 处理包含"千"的热度值，如"5.1千"
                                try:
                                    # 先移除"千"字，然后转换为浮点数，再乘以1000
                                    hot_value = int(float(hot_text.replace('千', '')) * 1000)
                                except ValueError:
                                    hot_value = 0
                            else:
                                # 尝试直接转换为整数
                                try:
                                    hot_value = int(hot_text)
                                except ValueError:
                                    hot_value = 0
                        elif isinstance(hot_text, (int, float)):
                            hot_value = int(hot_text)
                        
                        # 只保留热度大于100的帖子（为了测试能获取到一些数据）
                        if hot_value < 100:
                            continue
                        
                        # 过滤无效标题
                        if not full_title or len(full_title) < 2 or len(full_title) > 100:
                            continue
                        
                        # 过滤常见无意义内容
                        invalid_keywords = ['首页', '关注', '发现', '商城', '登录', '注册', '下载', 'APP', '消息', '我',
                                          'ICP', '沪公网安备', '营业执照', '沪ICP备', '网络文化经营许可证']
                        if any(keyword in full_title for keyword in invalid_keywords):
                            continue
                        
                        # 只采集高热度帖子 - 热度大于100或包含"万"
                        hot_value = 0
                        hot_text = liked_count
                        if '万' in hot_text:
                            # 处理"万"单位
                            try:
                                hot_value = float(hot_text.replace('万+', '').replace('万', '')) * 10000
                            except ValueError:
                                hot_value = 10000  # 如果无法解析，默认为10000
                        elif hot_text.isdigit():
                            hot_value = int(hot_text)
                        else:
                            # 处理"1千+"这类情况
                            if '千+' in hot_text:
                                hot_value = 1000
                            elif '万+' in hot_text:
                                hot_value = 10000
                            # 处理"1千"到"9千"的情况
                            elif '千' in hot_text:
                                try:
                                    hot_value = int(hot_text.replace('千', '')) * 1000
                                except ValueError:
                                    hot_value = 1000
                            else:
                                # 尝试直接转换为整数
                                try:
                                    hot_value = int(hot_text)
                                except ValueError:
                                    hot_value = 0
                        
                        # 只保留热度大于100的帖子（为了测试能获取到一些数据）
                        if hot_value < 100:
                            continue
                        
                        # 标题去重检查
                        if full_title in [item['title'] for item in hot_data]:
                            continue
                        
                        hot_data.append({
                            'title': full_title,
                            'url': url,
                            'hot': liked_count,
                            'rank': str(i + 1)
                        })
                        
                    except Exception as inner_e:
                        continue
            else:
                print("JSON解析失败，尝试使用BeautifulSoup解析HTML")
                # 如果JSON解析失败，尝试使用BeautifulSoup解析HTML
                results = self._parse_with_beautifulsoup(html_text)
                return results
                        
        except Exception as e:
            print(f"解析小红书JSON数据出错: {e}")
            # 如果JSON解析失败，尝试使用BeautifulSoup解析HTML
            results = self._parse_with_beautifulsoup(html_text)
            return results
            
        # 去重
        seen_titles = set()
        unique_data = []
        for item in hot_data:
            if item['title'] not in seen_titles and len(item['title']) > 2:
                seen_titles.add(item['title'])
                unique_data.append(item)
                
        hot_data = unique_data[:30]  # 限制最多30条
        
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
            
            # 不再使用_validate_result，直接添加到结果中
            results.append(result)
                
        #print(f"最终返回 {len(results)} 条结果")
        return results
    
    def _parse_with_beautifulsoup(self, html_text: str) -> List[Dict[str, Any]]:
        """使用BeautifulSoup解析HTML内容"""
        hot_data = []
        results = []
        
        try:
            from bs4 import BeautifulSoup
            
            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(html_text, 'html.parser')
            
            # 查找所有可能的笔记元素
            note_items = []
            
            # 方法1: 查找包含/discovery/item/链接的a标签
            note_items.extend(soup.find_all('a', href=re.compile(r'/discovery/item/')))
            
            # 方法2: 查找包含note-item类的元素
            note_items.extend(soup.find_all(class_=re.compile(r'note-item|noteCard|feed-item')))
            
            # 方法3: 查找包含data-note-id属性的元素
            note_items.extend(soup.find_all(attrs={"data-note-id": True}))
            
            # 方法4: 查找所有a标签并检查href属性
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '')
                if '/discovery/item/' in href and link not in note_items:
                    note_items.append(link)
            
            print(f"BeautifulSoup找到 {len(note_items)} 个可能的笔记元素")
            
            # 提取笔记数据
            for i, item in enumerate(note_items[:30]):  # 限制最多30条
                try:
                    # 获取标题
                    title = ''
                    
                    # 尝试多种方式获取标题
                    title_elem = item.find('div', class_=re.compile(r'title|note-title|note-desc', re.I))
                    if not title_elem:
                        title_elem = item.find(class_=re.compile(r'title|note-title|note-desc', re.I))
                    if not title_elem:
                        title_elem = item.find('span', class_=re.compile(r'title|note-title|note-desc', re.I))
                    if not title_elem:
                        title_elem = item.find('p', class_=re.compile(r'title|note-title|note-desc', re.I))
                    
                    # 如果在item中找不到标题，尝试在其父元素中查找
                    if not title_elem:
                        parent = item.find_parent(class_=re.compile(r'note|card|item', re.I))
                        if parent:
                            title_elem = parent.find(class_=re.compile(r'title|note-title|note-desc', re.I))
                    
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                    else:
                        # 尝试从title属性获取
                        title = item.get('title', '').strip()
                        if not title:
                            # 尝试从data-title属性获取
                            title = item.get('data-title', '').strip()
                    
                    # 如果还获取不到标题，尝试获取元素内的文本
                    if not title:
                        text_content = item.get_text(strip=True)
                        if text_content and len(text_content) > 2 and len(text_content) < 100:
                            title = text_content
                    
                    # 如果还是获取不到标题，跳过
                    if not title or len(title) < 2:
                        continue
                    
                    # 获取链接
                    href = item.get('href', '')
                    if not href:
                        # 尝试从data-href属性获取
                        href = item.get('data-href', '')
                    
                    # 如果href为空，尝试从父元素获取
                    if not href:
                        parent_link = item.find_parent('a', href=re.compile(r'/discovery/item/'))
                        if parent_link:
                            href = parent_link.get('href', '')
                    
                    # 如果还是没有链接，尝试从data-note-id构造
                    if not href:
                        note_id = item.get('data-note-id', '')
                        if note_id:
                            href = f'/discovery/item/{note_id}'
                    
                    # 特殊处理：尝试从onclick属性中提取链接
                    if not href:
                        onclick = item.get('onclick', '')
                        # 匹配类似 "window.open('/discovery/item/xxx')" 的模式
                        match = re.search(r"window\.open\('(/discovery/item/[^']*)'", onclick)
                        if match:
                            href = match.group(1)
                    
                    # 特殊处理：尝试从data属性中提取笔记ID
                    if not href:
                        for attr_name, attr_value in item.attrs.items():
                            if attr_name.startswith('data-') and isinstance(attr_value, str) and re.match(r'^[a-f0-9]{24}$', attr_value):
                                href = f'/discovery/item/{attr_value}'
                                break
                    
                    # 特殊处理：尝试从笔记卡片的ID属性构造链接
                    if not href:
                        item_id = item.get('id', '')
                        if item_id and re.match(r'^[a-f0-9]{24}$', item_id):
                            href = f'/discovery/item/{item_id}'
                    
                    # 如果仍然没有链接，尝试从父元素中查找
                    if not href:
                        parent = item.find_parent()
                        while parent and not href:
                            if parent.name == 'a' and parent.get('href', ''):
                                href = parent.get('href', '')
                                break
                            parent = parent.find_parent()
                    
                    url = ''
                    if href:
                        if href.startswith('//'):
                            url = f'https:{href}'
                        elif href.startswith('/'):
                            url = f'https://www.xiaohongshu.com{href}'
                        elif href.startswith('http'):
                            url = href
                        else:
                            url = f'https://www.xiaohongshu.com{href}'
                    else:
                        # 如果实在获取不到链接，跳过该条目
                        continue
                    
                    # 获取热度信息
                    hot = '0'
                    hot_elem = item.find(class_=re.compile(r'like|hot|count|收藏|赞', re.I))
                    if not hot_elem:
                        # 在父元素中查找
                        parent = item.find_parent(class_=re.compile(r'note|card|item', re.I))
                        if parent:
                            hot_elem = parent.find(class_=re.compile(r'like|hot|count|收藏|赞', re.I))
                    
                    if hot_elem:
                        hot_text = hot_elem.get_text(strip=True)
                        # 提取数字
                        hot_numbers = re.findall(r'(\d+\.?\d*[万kK]?)', hot_text)
                        if hot_numbers:
                            hot = hot_numbers[0]
                            # 处理万、k等单位
                            if '万' in hot:
                                try:
                                    hot = str(int(float(hot.replace('万', '')) * 10000))
                                except ValueError:
                                    hot = '10000'
                            elif 'k' in hot.lower():
                                try:
                                    hot = str(int(float(hot.lower().replace('k', '')) * 1000))
                                except ValueError:
                                    hot = '1000'
                    
                    # 只采集高热度帖子 - 热度大于1000或包含"万"
                    hot_value = 0
                    hot_text = hot
                    if '万' in hot_text:
                        # 处理"万"单位
                        try:
                            hot_value = int(float(hot_text.replace('万+', '').replace('万', '')) * 10000)
                        except ValueError:
                            hot_value = 10000  # 如果无法解析，默认为10000
                    elif 'k' in hot_text.lower():
                        # 处理"k"单位
                        try:
                            hot_value = int(float(hot_text.lower().replace('k+', '').replace('k', '')) * 1000)
                        except ValueError:
                            hot_value = 1000  # 如果无法解析，默认为1000
                    elif hot_text.isdigit():
                        hot_value = int(hot_text)
                    else:
                        # 尝试转换为浮点数
                        try:
                            hot_value = int(float(hot_text))
                        except ValueError:
                            hot_value = 0
                    
                    # 只保留热度大于1000的帖子
                    if hot_value < 1000:
                        print(f"过滤低热度帖子: {title} (热度: {hot})")
                        continue
                    
                    # 获取作者信息
                    author_elem = item.find(class_=re.compile(r'user|author|nickname|name', re.I))
                    if not author_elem:
                        # 在父元素中查找
                        parent = item.find_parent(class_=re.compile(r'note|card|item', re.I))
                        if parent:
                            author_elem = parent.find(class_=re.compile(r'user|author|nickname|name', re.I))
                    
                    author = ''
                    if author_elem:
                        author = author_elem.get_text(strip=True)
                    
                    # 构造完整标题
                    if author and title:
                        full_title = f"{title} by {author}"
                    elif title:
                        full_title = title
                    else:
                        continue
                    
                    # 过滤无效标题
                    if not full_title or len(full_title) < 2 or len(full_title) > 100:
                        continue
                    
                    # 过滤常见无意义内容
                    invalid_keywords = ['首页', '关注', '发现', '商城', '登录', '注册', '下载', 'APP', '消息', '我',
                                      'ICP', '沪公网安备', '营业执照', '沪ICP备', '网络文化经营许可证']
                    if any(keyword in full_title for keyword in invalid_keywords):
                        continue
                        
                    # 标题去重检查
                    if full_title in [item['title'] for item in hot_data]:
                        continue
                    
                    hot_data.append({
                        'title': full_title,
                        'url': url,
                        'hot': hot,
                        'rank': str(i + 1)
                    })
                    
                except Exception as inner_e:
                    print(f"处理单个item数据出错: {inner_e}")
                    continue
            
            print(f"BeautifulSoup提取到 {len(hot_data)} 条有效数据")
                        
        except Exception as e:
            print(f"解析小红书HTML数据出错: {e}")
            import traceback
            traceback.print_exc()
            pass
            
        # 去重
        seen_titles = set()
        unique_data = []
        for item in hot_data:
            if item['title'] not in seen_titles and len(item['title']) > 2:
                seen_titles.add(item['title'])
                unique_data.append(item)
                
        hot_data = unique_data[:30]  # 限制最多30条
        
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
            
            # 不再使用_validate_result，直接添加到结果中
            results.append(result)
                
        print(f"BeautifulSoup最终返回 {len(results)} 条结果")
        return results
    
    def _is_mock_data(self, data: List[Dict[str, Any]]) -> bool:
        """判断是否为模拟数据"""
        if not data:
            return True
        
        # 检查数据条数
        if len(data) < 1:  # 改为1条即可，更宽松的判断
            return True
            
        first_item = data[0]
        title = first_item.get('title', '') if isinstance(first_item, dict) else ''
        # 检查是否包含示例相关的关键词
        is_mock = '示例' in title or 'Example' in title or '模拟' in title
        #print(f"检查是否为模拟数据: {is_mock}, 标题: {title}")
        return is_mock
    
    def _get_mock_data(self) -> List[Dict[str, Any]]:
        """获取模拟数据（用于演示或备用）"""
        return [
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '小红书热门话题示例',
                'url': 'https://www.xiaohongshu.com',
                'hot': '50000',
                'rank': '1',
                'published_at': '2024-01-01 09:00:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            },
            {
                'id': generate_content_id(),  # 使用统一的ID生成函数
                'title': '小红书生活分享示例',
                'url': 'https://www.xiaohongshu.com',
                'hot': '30000',
                'rank': '2',
                'published_at': '2024-01-01 08:30:00',
                'collected_at': self._get_current_time(),
                'site_code': self.site_code
            }
        ]