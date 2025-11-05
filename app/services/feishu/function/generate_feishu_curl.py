#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成飞书API调用的curl命令示例
用于调试和手动测试飞书API
"""

import sys
import os
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.core.config import config_manager


def generate_curl_commands():
    """生成常用的飞书API调用curl命令"""
    print("🚀 生成飞书API调用的curl命令示例...")
    
    try:
        # 从配置中获取参数
        print("\n1. 从配置文件加载参数...")
        creds = config_manager.get_credentials()
        app_id = creds.get("feishu", {}).get("app_id")
        app_secret = creds.get("feishu", {}).get("app_secret")
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_id or not app_secret:
            print("❌ 错误: 未找到飞书 App ID 或 App Secret，请检查配置文件")
            return False
            
        if not app_token or not table_id:
            print("❌ 错误: 未找到测试用的 app_token 或 table_id，请检查配置文件")
            return False
            
        print(f"   App ID: {app_id}")
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 生成获取tenant_access_token的curl命令
        print("\n2. 生成获取 tenant_access_token 的curl命令:")
        tenant_token_curl = f"""curl --location --request POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \\
--header 'Content-Type: application/json' \\
--data-raw '{{
    "app_id": "{app_id}",
    "app_secret": "{app_secret}"
}}'"""
        print(tenant_token_curl)
        
        # 生成获取表格字段的curl命令
        print("\n3. 生成获取表格字段的curl命令:")
        get_fields_curl = f"""curl --location --request GET 'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields' \\
--header 'Authorization: Bearer {{tenant_access_token}}'"""
        print(get_fields_curl)
        
        # 生成创建字段的curl命令
        print("\n4. 生成创建字段的curl命令:")
        create_field_curl = f"""curl --location --request POST 'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields' \\
--header 'Authorization: Bearer {{tenant_access_token}}' \\
--header 'Content-Type: application/json' \\
--data-raw '{{
    "field_name": "test_field",
    "type": "text"
}}'"""
        print(create_field_curl)
        
        # 生成查询记录的curl命令
        print("\n5. 生成查询记录的curl命令:")
        list_records_curl = f"""curl --location --request GET 'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records' \\
--header 'Authorization: Bearer {{tenant_access_token}}'"""
        print(list_records_curl)
        
        # 生成插入记录的curl命令
        print("\n6. 生成插入记录的curl命令:")
        create_records_curl = f"""curl --location --request POST 'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records' \\
--header 'Authorization: Bearer {{tenant_access_token}}' \\
--header 'Content-Type: application/json' \\
--data-raw '{{
    "fields": {{
        "title": "测试标题",
        "content": "测试内容"
    }}
}}'"""
        print(create_records_curl)
        
        print("\n💡 使用说明:")
        print("   1. 将 {tenant_access_token} 替换为实际获取到的tenant_access_token")
        print("   2. 根据需要修改请求参数")
        print("   3. 在终端中执行生成的curl命令")
        
        print("\n🎉 curl命令生成完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 生成curl命令时发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    result = generate_curl_commands()
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()