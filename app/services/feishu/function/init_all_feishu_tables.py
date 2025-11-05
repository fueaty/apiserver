import sys
import os
import asyncio

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

from app.services.feishu.feishu_service import FeishuService
from app.services.feishu.field_rules import TABLE_PLANS
from app.core.config import config_manager

async def init_table(table_name, table_config):
    """初始化单个表格"""
    print(f"\n🚀 开始初始化表格: {table_config['name']} ({table_name})")
    
    try:
        # 初始化飞书服务
        feishu_service = FeishuService()
        
        app_token = table_config['app_token']
        table_id = table_config['table_id']
        
        print(f"  表格信息: App Token={app_token}, Table ID={table_id}")
        
        # 获取该表格类型应该具有的字段集
        table_plan = TABLE_PLANS.get(table_name, {})
        required_fields = table_plan.get('fields', set())
        
        # 确保表格字段同步
        success, message = await feishu_service.ensure_table_fields(
            app_token, table_id, required_fields, table_name)
        
        if success:
            print(f"  ✅ 表格 {table_config['name']} 初始化成功: {message}")
        else:
            print(f"  ⚠️ 表格 {table_config['name']} 初始化部分成功: {message}")
            
    except Exception as e:
        print(f"  ❌ 表格 {table_config['name']} 初始化过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """主函数，初始化所有飞表格"""
    print("🚀 开始初始化所有飞表格...")
    
    try:
        # 获取凭证信息
        creds = config_manager.get_credentials()
        feishu_tables = creds.get("feishu", {}).get("tables", {})
        
        if not feishu_tables:
            print("❌ 未找到飞表格配置信息，请检查 config/credentials.yaml 文件")
            return
        
        print(f"📋 找到 {len(feishu_tables)} 个表格需要初始化")
        
        # 初始化所有表格
        for table_name, table_config in feishu_tables.items():
            await init_table(table_name, table_config)
        
        print("\n🎉 所有飞表格初始化完成!")
        
    except Exception as e:
        print(f"\n❌ 初始化过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())