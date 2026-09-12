#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
解析从mcp工具获取的小红书页面内容
"""

import json
import re


def parse_xiaohongshu_mcp_content(html_content):
    """
    解析从mcp工具获取的小红书页面内容
    """
    # 查找window.__INITIAL_STATE__变量
    pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*(?:\n|;|</script>)'
    match = re.search(pattern, html_content, re.DOTALL)
    
    if match:
        try:
            # 获取JSON字符串
            json_str = match.group(1)
            
            # 清理JSON字符串
            # 替换HTML实体
            json_str = json_str.replace('\\u002F', '/').replace('\\u003C', '<').replace('\\u003E', '>')
            
            # 移除可能的尾随字符
            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            
            # 解析JSON
            data = json.loads(json_str)
            
            # 提取feed数据
            feeds = data.get('feed', {}).get('feeds', [])
            if not feeds:
                feeds = data.get('home', {}).get('feeds', [])
            if not feeds:
                feeds = data.get('recommend', {}).get('feeds', [])
            
            print(f"成功提取到 {len(feeds)} 条feed数据")
            
            # 解析每条feed
            results = []
            for i, feed in enumerate(feeds[:20]):  # 限制最多20条
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
                    note_id = note_card.get('noteId') or note_card.get('note_id') or note_card.get('id', '')
                    xsec_token = feed.get('xsecToken', '')
                    if note_id and xsec_token:
                        url = f'https://www.xiaohongshu.com/discovery/item/{note_id}?xsec_token={xsec_token}&xsec_source='
                    elif note_id:
                        url = f'https://www.xiaohongshu.com/discovery/item/{note_id}'
                    else:
                        url = 'https://www.xiaohongshu.com/explore'
                    
                    # 获取点赞数
                    interact_info = note_card.get('interactInfo') or note_card.get('interact_info') or {}
                    liked_count = str(interact_info.get('likedCount') or interact_info.get('liked_count', '0'))
                    
                    # 过滤无效标题
                    if not full_title or len(full_title) < 2 or len(full_title) > 100:
                        continue
                    
                    results.append({
                        'title': full_title,
                        'url': url,
                        'hot': liked_count,
                        'rank': str(i + 1)
                    })
                    
                except Exception as e:
                    print(f"处理feed数据时出错: {e}")
                    continue
            
            return results
            
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {e}")
        except Exception as e:
            print(f"解析过程中出现错误: {e}")
    
    return []


if __name__ == "__main__":
    # 读取从mcp获取的页面内容
    try:
        with open('/opt/apiserver/xiaohongshu_mcp_content.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        results = parse_xiaohongshu_mcp_content(html_content)
        print(f"解析结果数量: {len(results)}")
        
        for i, result in enumerate(results[:10]):
            print(f"{i+1}. {result['title']} (热度: {result['hot']})")
            print(f"   链接: {result['url']}")
            
    except Exception as e:
        print(f"读取文件时出错: {e}")