import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))
import asyncio
from typing import Dict, Any, Set
from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager

# --- 配置区 ---
# 定义所有采集和发布任务可能用到的字段，作为"黄金标准"
# 如果不同字段需要特定类型或属性，可以在 FIELD_DEFINITIONS 中配置
FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # 通用字段（文本）
    'id': {'type': 'text'},
    'title': {'type': 'text'},
    'url': {'type': 'text'},
    'content': {'type': 'text'},
    'author': {'type': 'text'},
    'category': {'type': 'text'},
    'summary': {'type': 'text'},
    'tags': {'type': 'text'},
    'seo_title': {'type': 'text'},
    'seo_description': {'type': 'text'},
    'seo_keywords': {'type': 'text'},

    # 数值字段
    'hot': {'type': 'number'},
    'rank': {'type': 'number'},

    # 日期字段
    'published_at': {'type': 'date'},
    'collected_at': {'type': 'datetime'},

    # 状态、平台相关字段
    'site_code': {'type': 'text'},
    'platform_code': {'type': 'text'},
    'published_url': {'type': 'text'},
    'status': {'type': 'single_select', 'property': {'options': [{'name': '待发布'}, {'name': '已发布'}, {'name': '失败'}]}},
    'error_message': {'type': 'text'},

    # AI 分析字段
    'sentiment': {'type': 'single_select', 'property': {'options': [{'name': '正面'}, {'name': '中性'}, {'name': '负面'}]}},
}

REQUIRED_FIELDS: Set[str] = set(FIELD_DEFINITIONS.keys())

# --- 主逻辑 ---
async def main():
    """主函数：同步飞书多维表格字段"""

    print("🚀 开始执行飞书多维表格初始化脚本...")

    # 1. 加载配置
    print("\nStep 1: 加载 credentials.yaml 中的凭证...")
    try:
        creds = config_manager.get_credentials(force_reload=True)
        feishu_creds = creds.get("feishu", {})
        app_token = feishu_creds.get("app_token")
        table_id = feishu_creds.get("table_id")
        if not app_token or not table_id or "YOUR_" in app_token:
            print("❌ 错误：请在 config/credentials.yaml 中正确填写 app_token 和 table_id")
            return
        print(f"✅ 凭证加载成功，将操作表格: [App: {app_token}, Table: {table_id}]")
    except Exception as e:
        print(f"❌ 加载配置失败: {e}")
        return

    # 2. 初始化服务并获取线上字段
    print("\nStep 2: 初始化飞书服务并获取线上表格字段...")
    try:
        feishu_service = FeishuService()
        online_fields_info = await feishu_service.get_table_fields(app_token, table_id)
        online_field_names = set(online_fields_info.keys())
        print(f"✅ 成功获取到 {len(online_field_names)} 个线上字段: {online_field_names}")
    except Exception as e:
        print(f"❌ 获取线上字段失败: {e}")
        print("✋ 请检查：1. 凭证是否正确；2. 应用是否发布；3. 机器人是否已添加为表格协作者并拥有足够权限。")
        return

    # 3. 比对并计算差异
    print("\nStep 3: 比对线上字段与规则字段...")
    fields_to_add = REQUIRED_FIELDS - online_field_names
    fields_to_delete = online_field_names - REQUIRED_FIELDS
    # 排除飞书默认字段，不进行删除
    default_feishu_fields = {'创建时间', '最后更新时间', '创建人', '修改人'}
    fields_to_delete -= default_feishu_fields

    if not fields_to_add and not fields_to_delete:
        print("🎉 恭喜！线上表格字段与规则完全一致，无需调整。")
        return

    print(f"🔍 待新增字段 ({len(fields_to_add)}): {fields_to_add if fields_to_add else '无'}")
    print(f"🔍 待删除字段 ({len(fields_to_delete)}): {fields_to_delete if fields_to_delete else '无'}")

    # 4. 执行删除操作
    if fields_to_delete:
        print("\nStep 4: 执行删除操作...")
        for field_name in fields_to_delete:
            field_info = online_fields_info.get(field_name)
            if not field_info:
                print(f"    ⚠️ 未找到字段 '{field_name}' 的 ID，跳过删除。")
                continue
            field_id = field_info['id']
            
            try:
                success = await feishu_service.delete_field(app_token, table_id, field_id)
                if success:
                    print(f"    ✅ 成功删除字段: {field_name}")
                else:
                    print(f"    ❌ 删除字段失败: {field_name}")
            except Exception as e:
                print(f"    ❌ 删除字段 {field_name} 时发生异常: {e}")

    # 5. 执行新增操作
    if fields_to_add:
        print("\nStep 5: 执行新增操作...")
        for field_name in fields_to_add:
            field_def = FIELD_DEFINITIONS.get(field_name, {})
            field_type = field_def.get('type', 'text')
            property_config = field_def.get('property', {})
            
            try:
                field_id = await feishu_service.create_field(app_token, table_id, field_name, field_type, property_config)
                if field_id:
                    print(f"    ✅ 成功创建字段: {field_name} (ID: {field_id})")
                else:
                    print(f"    ❌ 创建字段失败: {field_name}")
            except Exception as e:
                print(f"    ❌ 创建字段 {field_name} 时发生异常: {e}")

    print("\n🎉 飞书多维表格字段同步完成!")

if __name__ == "__main__":
    asyncio.run(main())