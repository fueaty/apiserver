#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试创建飞书多维表格字段功能
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
    """测试创建字段功能"""
    print("🚀 开始测试创建飞书多维表格字段功能...")
    
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
        
        # 创建测试字段
        print("\n3. 创建测试字段...")
        # 生成唯一字段名避免冲突
        test_field_name = f"test_field_{int(time.time())}_{random.randint(1000, 9999)}"
        field_id = await service.create_field(app_token, table_id, test_field_name, "text")
        if not field_id:
            print("❌ 创建测试字段失败")
            return False
        print(f"✅ 成功创建测试字段: {test_field_name} (ID: {field_id})")
        
        # 验证字段是否存在
        print("\n4. 验证字段是否存在...")
        fields = await service.get_table_fields(app_token, table_id)
        if test_field_name in fields:
            print(f"✅ 字段验证成功，字段 {test_field_name} 存在于表格中")
        else:
            print(f"❌ 字段验证失败，字段 {test_field_name} 未在表格中找到")
            return False
            
        # 清理测试字段（删除）
        print("\n5. 清理测试字段...")
        success = await service.delete_field(app_token, table_id, field_id)
        if not success:
            print("❌ 清理测试字段失败")
            return False
        print(f"✅ 成功清理测试字段: {test_field_name}")
        
        print("\n🎉 创建字段功能测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)