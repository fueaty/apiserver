#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试删除特定字段的脚本
用于调试删除字段时的权限问题
"""

import sys
import os
import asyncio

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


async def test_delete_field(field_name="scheduled_publish_time"):
    """测试删除特定字段"""
    print(f"🚀 开始测试删除字段: {field_name}")
    
    try:
        # 初始化服务
        print("\n1. 初始化飞书服务...")
        service = FeishuService()
        print("✅ 飞书服务初始化成功")
        
        # 从配置中获取测试参数
        print("\n2. 从配置文件加载测试参数...")
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("content_evaluation", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("content_evaluation", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 错误: 未找到测试用的 app_token 或 table_id，请检查配置文件")
            return False
            
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 获取当前字段列表
        print("\n3. 获取当前字段列表...")
        fields = await service.get_table_fields(app_token, table_id)
        print(f"✅ 成功获取表格字段，共 {len(fields)} 个字段")
        
        # 查找要删除的字段
        target_field = fields.get(field_name)
        if not target_field:
            print(f"⚠️  字段 {field_name} 不存在，无需删除")
            return True
            
        print(f"   找到目标字段: {field_name} (ID: {target_field['id']})")
        
        # 尝试删除字段
        print(f"\n4. 尝试删除字段 {field_name}...")
        try:
            success = await service.delete_field(app_token, table_id, target_field['id'])
            if success:
                print(f"✅ 成功删除字段: {field_name}")
                return True
            else:
                print(f"❌ 删除字段失败: {field_name}")
                return False
        except Exception as e:
            print(f"❌ 删除字段时发生异常: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    field_name = "scheduled_publish_time"
    if len(sys.argv) > 1:
        field_name = sys.argv[1]
        
    result = await test_delete_field(field_name)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    asyncio.run(main())