#!/usr/bin/env python3
"""
调试知乎请求差异
"""

import asyncio
import aiohttp
import yaml
import os


async def test_zhihu_request():
    """测试知乎请求"""
    # 从配置文件加载cookie
    config_path = "/root/apiserver/config/zhihu.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        zhihu_config = yaml.safe_load(f)
    
    cookie_auth = zhihu_config.get('cookie', {}).get('auth')
    
    url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://www.zhihu.com/hot',
        'Cookie': cookie_auth
    }
    
    print("请求URL:", url)
    print("请求头:")
    for key, value in headers.items():
        print(f"  {key}: {value}")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            print(f"响应状态码: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"数据条数: {len(data.get('data', []))}")
            else:
                print("响应内容:")
                content = await response.text()
                print(content[:500])  # 打印前500个字符


if __name__ == "__main__":
    asyncio.run(test_zhihu_request())