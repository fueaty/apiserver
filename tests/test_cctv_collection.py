#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试CCTV站点采集情况的脚本
只测试采集功能，不进行入库操作
"""

import sys
import os
import asyncio
import json

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.collection.sites.cctv import CctvSite


async def test_cctv_collection():
    """
    测试CCTV站点的采集功能
    """
    print("🚀 开始测试CCTV站点采集...")
    
    # 创建CCTV站点采集实例
    cctv_site = CctvSite("cctv", {})  # site_code为"cctv"，config为空字典
    
    try:
        # 设置采集参数
        params = {
            "format": "raw"  # 使用原始格式
        }
        
        print("\n1. 执行CCTV站点数据采集...")
        # 执行采集
        results = await cctv_site.collect(params)
        
        # 检查采集结果
        if not results:
            print("❌ 采集结果为空")
            return False
        
        print(f"✅ 采集完成，共获取到 {len(results)} 条数据")
        
        # 显示部分采集结果
        print("\n2. 采集结果示例:")
        for i, item in enumerate(results[:5]):  # 显示前5条
            print(f"   {i+1}. {item.get('title', '无标题')}")
            print(f"      链接: {item.get('url', '无链接')}")
            print(f"      热度: {item.get('hot', '无热度')}")
            print(f"      排名: {item.get('rank', '无排名')}")
            print(f"      发布时间: {item.get('published_at', '无发布时间')}")
            print()
        
        # 验证数据结构完整性
        print("3. 验证数据结构完整性:")
        required_fields = ['id', 'title', 'url', 'hot', 'rank', 'published_at', 'collected_at', 'site_code', 'category', 'content', 'author', 'status']
        missing_fields = []
        
        for field in required_fields:
            if not all(field in item for item in results):
                missing_fields.append(field)
        
        if missing_fields:
            print(f"⚠️  发现缺失字段: {missing_fields}")
        else:
            print("✅ 所有必需字段都存在")
        
        # 验证标题不为空
        empty_titles = [item for item in results if not item.get('title')]
        if empty_titles:
            print(f"⚠️  发现 {len(empty_titles)} 条标题为空的记录")
        else:
            print("✅ 所有记录都有标题")
        
        # 验证ID唯一性
        ids = [item['id'] for item in results]
        unique_ids = set(ids)
        if len(ids) == len(unique_ids):
            print("✅ 所有ID都是唯一的")
        else:
            print("⚠️  发现重复的ID")
        
        print("\n🎉 CCTV站点采集测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理资源
        await cctv_site.cleanup()


async def test_cctv_collection_feishu_format():
    """
    测试CCTV站点的飞书格式采集功能
    """
    print("🚀 开始测试CCTV站点飞书格式采集...")
    
    # 创建CCTV站点采集实例
    cctv_site = CctvSite("cctv", {})  # site_code为"cctv"，config为空字典
    
    try:
        # 设置采集参数为飞书格式
        params = {
            "format": "feishu"  # 使用飞书格式
        }
        
        print("\n1. 执行CCTV站点数据采集（飞书格式）...")
        # 执行采集
        results = await cctv_site.collect(params)
        
        # 检查采集结果
        if not results:
            print("❌ 采集结果为空")
            return False
        
        print(f"✅ 采集完成，共获取到 {len(results)} 条数据")
        
        # 显示部分采集结果
        print("\n2. 采集结果示例:")
        for i, item in enumerate(results[:3]):  # 显示前3条
            fields = item.get("fields", {})
            print(f"   {i+1}. {fields.get('title', '无标题')}")
            print(f"      链接: {fields.get('url', '无链接')}")
            print(f"      热度: {fields.get('hot', '无热度')}")
            print(f"      排名: {fields.get('rank', '无排名')}")
            print()
        
        # 验证飞书格式结构
        print("3. 验证飞书格式结构:")
        valid_format = all("fields" in item for item in results)
        if valid_format:
            print("✅ 所有记录都符合飞书格式要求")
        else:
            print("⚠️  部分记录不符合飞书格式要求")
        
        print("\n🎉 CCTV站点飞书格式采集测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理资源
        await cctv_site.cleanup()


if __name__ == "__main__":
    # 运行测试
    print("选择测试类型:")
    print("1. 原始格式测试")
    print("2. 飞书格式测试")
    print("3. 两种格式都测试")
    
    choice = input("请输入选择 (1/2/3): ").strip()
    
    if choice == "1":
        success = asyncio.run(test_cctv_collection())
    elif choice == "2":
        success = asyncio.run(test_cctv_collection_feishu_format())
    elif choice == "3":
        success1 = asyncio.run(test_cctv_collection())
        print("\n" + "="*50 + "\n")
        success2 = asyncio.run(test_cctv_collection_feishu_format())
        success = success1 and success2
    else:
        print("无效选择，运行默认测试")
        success = asyncio.run(test_cctv_collection())
    
    # 根据测试结果退出程序
    sys.exit(0 if success else 1)