#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
澎湃新闻热榜采集测试脚本
"""

import asyncio
import json
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.collection.sites.thepaper import ThepaperSite

async def test_thepaper_collection():
    """测试澎湃新闻热榜采集功能"""
    print("开始测试澎湃新闻热榜采集功能...")
    
    # 创建澎湃新闻采集器实例
    thepaper_collector = ThepaperSite()
    
    try:
        # 执行采集
        results = await thepaper_collector.collect({})
        
        print(f"\n采集完成，共获取 {len(results)} 条数据")
        
        # 保存页面内容供分析
        if hasattr(thepaper_collector, 'page_content') and thepaper_collector.page_content:
            with open('thepaper_page.html', 'w', encoding='utf-8') as f:
                f.write(thepaper_collector.page_content)
            print("页面内容已保存到 thepaper_page.html 文件")
        
        # 显示前5条数据预览
        print("\n前5条数据预览:")
        for i, item in enumerate(results[:5]):
            print(f"{i+1}. 标题: {item.get('title', 'N/A')}")
            print(f"   链接: {item.get('url', 'N/A')}")
            print(f"   热度: {item.get('hot', 'N/A')}")
            print(f"   排名: {item.get('rank', 'N/A')}")
            print("-" * 50)
        
        # 数据验证
        print("\n数据验证:")
        if results:
            required_fields = ['title', 'url', 'hot', 'rank']
            valid_count = 0
            for item in results:
                if all(field in item and item[field] for field in required_fields):
                    valid_count += 1
            
            print(f"有效数据: {valid_count}/{len(results)} 条")
            
            # 检查热度值是否正确排序
            hot_values = [int(item['hot']) for item in results if 'hot' in item and item['hot'].isdigit()]
            if hot_values:
                is_sorted = all(hot_values[i] >= hot_values[i+1] for i in range(len(hot_values)-1))
                print(f"热度排序: {'正确' if is_sorted else '错误'}")
            
        # 保存结果到JSON文件
        with open('thepaper_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("结果已保存到 thepaper_results.json 文件")
        
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_thepaper_collection())