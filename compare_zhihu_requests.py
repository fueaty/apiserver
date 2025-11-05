#!/usr/bin/env python3
"""
比较curl和Python请求的差异
"""

import asyncio
import aiohttp
import yaml
import os
import json


async def compare_requests():
    """比较curl和Python请求"""
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
    
    print("=" * 50)
    print("Python请求详情:")
    print("=" * 50)
    print("请求URL:", url)
    print("请求头:")
    for key, value in headers.items():
        print(f"  {key}: {value}")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            print(f"Python响应状态码: {response.status}")
            print(f"响应头:")
            for key, value in response.headers.items():
                print(f"  {key}: {value}")
            
            if response.status == 200:
                data = await response.json()
                print(f"Python数据条数: {len(data.get('data', []))}")
            else:
                print("Python响应内容:")
                content = await response.text()
                print(content[:1000])  # 打印前1000个字符
    
    print("\n" + "=" * 50)
    print("生成curl命令进行对比:")
    print("=" * 50)
    
    curl_headers = []
    for key, value in headers.items():
        curl_headers.append(f'-H "{key}: {value}"')
    
    curl_command = f"curl -v { ' '.join(curl_headers) } \"{url}\""
    print(curl_command)


if __name__ == "__main__":
    asyncio.run(compare_requests())