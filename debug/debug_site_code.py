#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试site_code参数处理的脚本
"""

import sys
import os
import asyncio

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.services.collection.engine import CollectionEngine


async def test_site_code_parsing():
    """测试site_code参数解析"""
    print("测试site_code参数解析...")
    
    # 创建采集引擎实例
    collection_engine = CollectionEngine()
    
    # 测试不同的输入格式
    test_cases = [
        None,  # 无参数
        "weibo",  # 单个站点字符串
        "weibo,zhihu",  # 多个站点字符串
        ["weibo", "zhihu"],  # 列表格式
        ["weibo"],  # 单个元素列表
    ]
    
    for i, site_code_input in enumerate(test_cases):
        print(f"\n测试用例 {i+1}: {site_code_input} (类型: {type(site_code_input)})")
        try:
            target_sites = collection_engine._get_target_sites(site_code_input)
            print(f"  解析结果: {target_sites}")
        except Exception as e:
            print(f"  错误: {e}")


if __name__ == "__main__":
    asyncio.run(test_site_code_parsing())