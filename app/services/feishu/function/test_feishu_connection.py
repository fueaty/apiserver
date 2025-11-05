#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试飞书连接和基本功能
"""

import sys
import os
import asyncio
import traceback

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


async def main():
    """测试飞书连接"""
    print("🚀 开始测试飞书连接...")
    
    try:
        # 初始化服务
        print("\n1. 初始化飞书服务...")
        service = FeishuService()
        print("✅ 飞书服务初始化成功")
        print(f"   App ID: {service.app_id}")
        
        # 测试获取tenant_access_token
        print("\n2. 测试获取 tenant_access_token...")
        token = await service.get_tenant_access_token()
        print(f"✅ 成功获取 tenant_access_token: {token[:30]}...")
        
        # 从配置中获取测试参数
        print("\n3. 从配置文件加载测试参数...")
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 错误: 未找到测试用的 app_token 或 table_id，请检查配置文件")
            return False
            
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 测试获取表格字段
        print("\n4. 测试获取表格字段...")
        fields = await service.get_table_fields(app_token, table_id)
        print(f"✅ 成功获取表格字段，共 {len(fields)} 个字段")
        
        if fields:
            print("   部分字段示例:")
            for i, (name, info) in enumerate(list(fields.items())[:5]):
                print(f"     - {name}: {info['type']}")
        
        print("\n🎉 飞书连接测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)