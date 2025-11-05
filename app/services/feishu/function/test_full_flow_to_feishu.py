#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试完整的飞书操作流程
包括：获取访问令牌、创建字段、插入记录、查询记录、删除字段
"""

import sys
import os
import asyncio
import time
import random

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


async def main():
    """测试完整流程"""
    print("🚀 开始测试完整的飞书操作流程...")
    
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
        
        # 创建测试字段
        print("\n4. 创建测试字段...")
        test_field_name = f"test_full_flow_field_{int(time.time()) % 10000}_{random.randint(100, 999)}"
        field_id = await service.create_field(app_token, table_id, test_field_name, "text")
        if not field_id:
            print("❌ 创建测试字段失败")
            return False
        print(f"✅ 成功创建测试字段: {test_field_name} (ID: {field_id})")
        
        # 插入测试记录
        print("\n5. 插入测试记录...")
        test_record = {
            "fields": {
                test_field_name: "测试数据",
                "title": "测试标题",
                "content": "这是一条测试记录"
            }
        }
        
        record_ids = await service.batch_create_records(app_token, table_id, [test_record])
        if not record_ids:
            print("❌ 插入测试记录失败")
            # 清理已创建的字段
            await service.delete_field(app_token, table_id, field_id)
            return False
        print(f"✅ 成功插入 {len(record_ids)} 条测试记录")
        
        # 查询记录
        print("\n6. 查询记录...")
        records = await service.list_records(app_token, table_id, page_size=10)
        print(f"✅ 成功查询到 {len(records)} 条记录")
        
        # 清理测试字段
        print("\n7. 清理测试字段...")
        success = await service.delete_field(app_token, table_id, field_id)
        if not success:
            print("❌ 清理测试字段失败")
            return False
        print(f"✅ 成功清理测试字段: {test_field_name}")
        
        print("\n🎉 完整飞书操作流程测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)