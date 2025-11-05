#!/usr/bin/env python3
"""
调试知乎采集脚本
"""

import asyncio
import sys
import os
import yaml

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.collection.sites.zhihu import ZhihuSite


async def load_site_configs():
    """加载站点配置"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'sites.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


async def debug_zhihu():
    """调试知乎采集"""
    print("开始调试知乎采集...")
    
    # 加载配置
    configs = await load_site_configs()
    zhihu_config = configs['sites']['zhihu']
    
    # 创建知乎站点实例
    zhihu_site = ZhihuSite('zhihu', zhihu_config)
    
    # 尝试采集
    try:
        print("开始采集知乎热榜...")
        results = await zhihu_site.collect({})
        print(f"采集结果数量: {len(results)}")
        
        if results:
            print("前3条数据:")
            for i, item in enumerate(results[:3]):
                if isinstance(item, dict) and 'fields' in item:
                    fields = item['fields']
                    print(f"  {i+1}. {fields['title']} (热度: {fields['hot']})")
                    print(f"     链接: {fields['url']}")
        else:
            print("未获取到数据")
            
    except Exception as e:
        print(f"采集过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await zhihu_site.cleanup()


if __name__ == "__main__":
    asyncio.run(debug_zhihu())