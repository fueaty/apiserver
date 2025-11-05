#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试删除飞书多维表格字段功能
"""

import sys
import os
import asyncio

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


async def main():
    """测试删除字段功能"""
    print("🚀 开始测试删除飞书多维表格字段功能...")
    
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
        
        # 创建一个测试字段
        print("\n3. 创建测试字段...")
        test_field_name = "test_delete_field"
        field_id = await service.create_field(app_token, table_id, test_field_name, "text")
        if not field_id:
            print("❌ 创建测试字段失败")
            return False
        print(f"✅ 成功创建测试字段: {test_field_name} (ID: {field_id})")
        
        # 删除测试字段
        print("\n4. 删除测试字段...")
        success = await service.delete_field(app_token, table_id, field_id)
        if not success:
            print("❌ 删除测试字段失败")
            return False
        print(f"✅ 成功删除测试字段: {test_field_name}")
        
        print("\n🎉 删除字段功能测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)