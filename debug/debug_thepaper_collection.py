"""
澎湃新闻采集器测试脚本
用于验证澎湃新闻采集功能是否正常工作
"""

import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.collection.sites.thepaper import ThepaperSite
from app.core.config import settings
from app.utils.logger import logger

def setup_logger():
    """设置日志"""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

async def test_thepaper_collection():
    """测试澎湃新闻采集"""
    print("开始测试澎湃新闻采集器...")
    
    # 创建配置
    site_config = {
        "name": "澎湃新闻",
        "enabled": True,
        "rate_limit": 3,
        "timeout": 15,
        "request": {
            "url": "https://www.thepaper.cn/"
        }
    }
    
    # 创建采集器实例
    thepaper_site = ThepaperSite("thepaper", site_config)
    
    try:
        # 执行采集
        print("正在执行采集...")
        results = await thepaper_site.collect({"format": "raw"})
        
        # 打印结果统计
        print(f"采集完成！获取到 {len(results)} 条新闻")
        
        # 打印前5条结果详情
        print("\n前5条新闻详情：")
        for i, news in enumerate(results[:5]):
            print(f"\n--- 新闻 {i+1} ---")
            print(f"ID: {news.get('id')}")
            print(f"标题: {news.get('title')}")
            print(f"URL: {news.get('url')}")
            print(f"热度: {news.get('hot')}")
            print(f"排名: {news.get('rank')}")
            print(f"发布时间: {news.get('published_at')}")
            print(f"采集时间: {news.get('collected_at')}")
            print(f"站点: {news.get('site_code')}")
            print(f"分类: {news.get('category')}")
            print(f"状态: {news.get('status')}")
        
        # 验证结果格式
        if results:
            required_fields = ['id', 'title', 'url', 'hot', 'rank', 'published_at', 'collected_at', 'site_code']
            all_valid = True
            for news in results:
                for field in required_fields:
                    if field not in news:
                        print(f"警告：结果缺少必要字段 {field}")
                        all_valid = False
            
            if all_valid:
                print("\n✅ 所有结果格式验证通过")
            else:
                print("\n❌ 部分结果格式验证失败")
        
        print("\n测试完成！")
        return results
        
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        # 清理资源
        await thepaper_site.cleanup()

if __name__ == "__main__":
    setup_logger()
    
    # 运行异步测试
    try:
        asyncio.run(test_thepaper_collection())
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试运行出错: {str(e)}")