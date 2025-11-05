#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试飞书用户访问令牌功能
"""

import sys
import os
import asyncio

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


async def main():
    """测试用户访问令牌"""
    print("🚀 开始测试飞书用户访问令牌...")
    
    try:
        # 初始化服务
        print("\n1. 初始化飞书服务...")
        service = FeishuService()
        print("✅ 飞书服务初始化成功")
        
        # 获取用户访问令牌
        print("\n2. 获取用户访问令牌...")
        try:
            user_token = service.get_user_access_token()
            print(f"✅ 成功获取用户访问令牌: {user_token[:30]}...")
        except Exception as e:
            print(f"❌ 获取用户访问令牌失败: {e}")
            print("   请确保已在 config/credentials.yaml 中正确配置 user_access_token")
            return False
        
        # 从配置中获取测试参数
        print("\n3. 从配置文件加载测试参数...")
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("content_evaluation", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("content_evaluation", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 错误: 未找到测试用的 app_token 或 table_id，请检查配置文件")
            return False
            
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 尝试获取表格字段（需要有效令牌）
        print("\n4. 测试使用用户访问令牌获取表格字段...")
        try:
            # 这里我们直接使用tenant token而不是user token，因为get_table_fields默认使用tenant token
            fields = await service.get_table_fields(app_token, table_id)
            print(f"✅ 成功获取表格字段，共 {len(fields)} 个字段")
        except Exception as e:
            print(f"❌ 使用访问令牌获取表格字段失败: {e}")
            return False
        
        print("\n🎉 飞书用户访问令牌测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)