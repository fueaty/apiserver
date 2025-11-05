#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试数据采集模块采集数据同步到飞书多维表格功能
"""

import sys
import os
import asyncio
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager
from app.services.feishu.field_rules import TABLE_PLANS


async def test_collection_sync():
    """测试数据采集同步功能"""
    print("🚀 开始测试数据采集同步到飞书多维表格功能...")
    
    try:
        # 初始化服务
        print("\n1. 初始化飞书服务...")
        service = FeishuService()
        print("✅ 飞书服务初始化成功")
        
        # 从配置中获取测试参数
        print("\n2. 从配置文件加载测试参数...")
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 错误: 未找到测试用的 app_token 或 table_id，请检查配置文件")
            return False
            
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 测试获取tenant_access_token
        print("\n3. 测试获取 tenant_access_token...")
        token = await service.get_tenant_access_token()
        print(f"✅ 成功获取 tenant_access_token: {token[:30]}...")
        
        # 准备测试数据（模拟采集模块采集到的数据）
        print("\n4. 准备测试数据...")
        test_records = [
            {
                "fields": {
                    "id": "weibo_test_001",
                    "title": "测试微博热点标题1",
                    "url": "https://weibo.com/test/001",
                    "content": "这是测试微博热点的内容摘要1",
                    "author": "测试用户1",
                    "category": "科技",
                    "hot": "10000",
                    "rank": "1",
                    "collected_at": "2025-10-31 10:00:00",
                    "site_code": "weibo",
                    "status": "collected"
                }
            },
            {
                "fields": {
                    "id": "weibo_test_002",
                    "title": "测试微博热点标题2",
                    "url": "https://weibo.com/test/002",
                    "content": "这是测试微博热点的内容摘要2",
                    "author": "测试用户2",
                    "category": "娱乐",
                    "hot": "8000",
                    "rank": "2",
                    "collected_at": "2025-10-31 10:05:00",
                    "site_code": "weibo",
                    "status": "collected"
                }
            }
        ]
        
        print(f"   准备了 {len(test_records)} 条测试记录")
        
        # 同步字段
        print("\n5. 同步表格字段...")
        # 获取headlines表所需的字段
        required_fields = TABLE_PLANS["headlines"]["fields"]
        success, message = await service.ensure_table_fields(app_token, table_id, required_fields)
        if success:
            print(f"✅ 字段同步成功: {message}")
        else:
            print(f"⚠️ 字段同步失败: {message}")
        
        # 插入测试记录
        print("\n6. 插入测试记录...")
        result = await service.batch_add_records(app_token, table_id, test_records)
        
        if result.get("code") == 0:
            record_count = len(result.get("data", {}).get("records", []))
            print(f"✅ 成功插入 {record_count} 条测试记录")
        else:
            print(f"❌ 插入记录失败: {result.get('msg')}")
            return False
        
        # 查询记录确认插入成功
        print("\n7. 查询记录确认插入成功...")
        records = await service.list_records(app_token, table_id, page_size=5)
        print(f"✅ 成功查询到 {len(records)} 条记录")
        
        if records:
            print("   最新记录示例:")
            for record in records[:2]:  # 显示前2条记录
                fields = record.get("fields", {})
                print(f"     - 标题: {fields.get('title', 'N/A')}")
                print(f"       ID: {fields.get('id', 'N/A')}")
                print(f"       站点: {fields.get('site_code', 'N/A')}")
                print(f"       采集时间: {fields.get('collected_at', 'N/A')}")
        
        print("\n🎉🎉🎉 数据采集同步测试完成！🎉🎉🎉")
        return True
        
    except Exception as e:
        print("\n❌❌❌ 测试过程中发生错误 ❌❌❌")
        print("错误详情:")
        print(e)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_collection_sync())
    sys.exit(0 if result else 1)