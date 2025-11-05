#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Debug script for parsing Xiaohongshu page content fetched via mcp tools
"""

import json
import re
import gzip
from io import BytesIO


def debug_parse_xiaohongshu_content(html_content):
    """
    Debug function to parse Xiaohongshu page content
    """
    print("开始解析小红书页面内容...")
    print(f"页面内容长度: {len(html_content)} 字符")
    
    # 尝试查找window.__INITIAL_STATE__变量
    pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*(?:\n|;|</script>)'
    match = re.search(pattern, html_content, re.DOTALL)
    
    if match:
        print("✓ 找到 window.__INITIAL_STATE__ 变量")
        json_str = match.group(1)
        print(f"JSON字符串长度: {len(json_str)} 字符")
        
        # 尝试清理JSON字符串
        try:
            # 替换常见的转义字符
            json_str = json_str.replace('\\u002F', '/').replace('\\u003C', '<').replace('\\u003E', '>')
            
            # 尝试修复可能的JSON格式问题
            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            
            # 尝试解析JSON
            data = json.loads(json_str)
            print("✓ JSON解析成功")
            
            # 探索数据结构
            print("\n探索数据结构:")
            explore_data_structure(data, max_depth=3)
            
            # 尝试提取feed数据
            feeds = extract_feeds(data)
            print(f"\n提取到 {len(feeds)} 条feed数据")
            
            # 处理解析到的数据
            results = process_feeds(feeds)
            return results
            
        except json.JSONDecodeError as e:
            print(f"✗ JSON解析失败: {e}")
            # 显示出错位置附近的文本
            error_pos = e.pos
            start = max(0, error_pos - 50)
            end = min(len(json_str), error_pos + 50)
            print(f"错误位置附近的内容: ...{json_str[start:end]}...")
            
    else:
        print("✗ 未找到 window.__INITIAL_STATE__ 变量")
        # 尝试其他可能的模式
        alt_patterns = [
            r'window\.G_SSP\s*=\s*({.*?})\s*(?:\n|;|</script>)',
            r'<script[^>]*>\s*window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>',
        ]
        
        for i, pattern in enumerate(alt_patterns):
            match = re.search(pattern, html_content, re.DOTALL)
            if match:
                print(f"✓ 在替代模式 {i+1} 中找到匹配内容")
                break
        else:
            print("✗ 在所有替代模式中都未找到匹配内容")
    
    return []


def explore_data_structure(data, max_depth=3, current_depth=0, visited=None):
    """
    探索数据结构以找到可能的feed数据
    """
    if visited is None:
        visited = set()
        
    if current_depth >= max_depth:
        return
        
    indent = "  " * current_depth
    
    if isinstance(data, dict):
        print(f"{indent}字典 ({len(data)} 项):")
        for key in list(data.keys())[:5]:  # 限制显示前5项
            print(f"{indent}  {key}: ", end="")
            value = data[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                print(type(value).__name__)
            elif id(value) in visited:
                print("(循环引用)")
            else:
                visited.add(id(value))
                if isinstance(value, dict):
                    if value:
                        print(f"{type(value).__name__} {{")
                        explore_data_structure(value, max_depth, current_depth + 1, visited)
                        print(f"{indent}  }}")
                    else:
                        print(f"{type(value).__name__} {{}}")
                elif isinstance(value, list):
                    if value:
                        print(f"{type(value).__name__} [")
                        explore_data_structure(value[0] if value else None, max_depth, current_depth + 1, visited)
                        print(f"{indent}  ] (共{len(value)}项)")
                    else:
                        print(f"{type(value).__name__} []")
                else:
                    print(type(value).__name__)
                visited.discard(id(value))
                    
    elif isinstance(data, list):
        print(f"{indent}列表 ({len(data)} 项):")
        if data:
            print(f"{indent}  [0]: ", end="")
            explore_data_structure(data[0], max_depth, current_depth + 1, visited)


def extract_feeds(data):
    """
    从数据中提取feed信息
    """
    feeds = []
    
    def search_feeds(obj):
        nonlocal feeds
        if isinstance(obj, dict):
            # 检查是否是feed数据
            if 'noteCard' in obj or 'note_card' in obj or ('id' in obj and 'type' in obj):
                feeds.append(obj)
            elif 'feed' in obj and isinstance(obj['feed'], dict):
                search_feeds(obj['feed'])
            elif 'home' in obj and isinstance(obj['home'], dict):
                search_feeds(obj['home'])
            elif 'recommend' in obj and isinstance(obj['recommend'], dict):
                search_feeds(obj['recommend'])
            else:
                for value in obj.values():
                    search_feeds(value)
        elif isinstance(obj, list):
            for item in obj:
                search_feeds(item)
    
    search_feeds(data)
    return feeds


def process_feeds(feeds):
    """
    处理feed数据并转换为标准格式
    """
    results = []
    
    for i, feed in enumerate(feeds[:20]):  # 限制最多处理20条
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


def main():
    """
    主函数
    """
    try:
        # 直接读取JSON文件
        with open('/opt/apiserver/xiaohongshu_initial_state.json', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否是有效的JSON
        try:
            # 尝试直接解析JSON
            data = json.loads(content)
            print("直接解析JSON文件成功")
        except json.JSONDecodeError:
            # 如果直接解析失败，尝试修复后再解析
            print("直接解析JSON文件失败，尝试修复后解析")
            # 替换undefined为null
            content = re.sub(r'\bundefined\b', 'null', content)
            # 替换可能的HTML实体
            content = content.replace('\\u002F', '/').replace('\\u003C', '<').replace('\\u003E', '>')
            # 尝试解析修复后的JSON
            data = json.loads(content)
        
        print("开始调试解析小红书JSON数据")
        
        # 探索数据结构
        print("\n探索数据结构:")
        explore_data_structure(data, max_depth=3)
        
        # 尝试提取feed数据
        feeds = extract_feeds(data)
        print(f"\n提取到 {len(feeds)} 条feed数据")
        
        # 处理解析到的数据
        results = process_feeds(feeds)
        
        print(f"\n最终解析结果数量: {len(results)}")
        for i, result in enumerate(results[:10]):
            print(f"  {i+1}. {result['title']} (热度: {result['hot']})")
            print(f"     链接: {result['url']}")
            
    except FileNotFoundError:
        print("错误: 未找到 /opt/apiserver/xiaohongshu_initial_state.json 文件")
    except Exception as e:
        print(f"发生错误: {e}")


if __name__ == "__main__":
    main()