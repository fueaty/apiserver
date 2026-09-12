#!/usr/bin/env python3
"""
智能飞书表格清理脚本
根据表格当前记录数量自动调整清理策略
"""

import sys
import os
import asyncio
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager
import app.wework.notification_push as notification_push


async def get_table_record_count(app_token: str, table_id: str) -> int:
    """获取表格总记录数"""
    service = FeishuService()
    total_count = 0
    page_token = None
    
    print("正在统计表格记录总数...")
    
    while True:
        result = await service.list_records(app_token, table_id, page_size=500, page_token=page_token)
        records = result.get('items', [])
        total_count += len(records)
        
        if total_count % 5000 == 0:
            print(f"  已统计 {total_count} 条记录...")
        
        page_token = result.get('page_token')
        if not page_token:
            break
    
    return total_count


async def smart_cleanup():
    """智能清理策略"""
    print("=" * 60)
    print("🤖 智能飞书表格清理")
    print("=" * 60)
    
    try:
        # 初始化服务
        print("\n1. 初始化服务...")
        service = FeishuService()
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 配置缺失")
            return False
        
        print("✅ 服务初始化完成")
        
        # 获取表格记录总数
        print("\n2. 检查表格状态...")
        total_records = await get_table_record_count(app_token, table_id)
        print(f"   当前记录总数: {total_records}")
        
        # 根据记录数量制定清理策略
        threshold_warning = 80000  # 警告阈值
        threshold_critical = 95000  # 危险阈值
        limit_max = 100000  # 最大限制
        
        if total_records < threshold_warning:
            print("✅ 表格空间充足，无需清理")
            notification_push.send_message(f"✅ 飞书表格状态正常\n当前记录数: {total_records}/{limit_max}")
            return True
            
        elif total_records < threshold_critical:
            print("⚠️ 表格接近容量限制，执行轻度清理")
            days_to_keep = 60
            msg_prefix = "⚠️"
            
        else:
            print("🚨 表格容量严重不足，执行紧急清理")
            days_to_keep = 30
            msg_prefix = "🚨"
        
        # 执行清理
        print(f"\n3. 执行清理策略 (保留{days_to_keep}天数据)...")
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_date_str = cutoff_date.strftime("%Y-%m-%d")
        
        print(f"   删除截止日期: {cutoff_date_str} 之前的数据")
        
        # 获取需要删除的记录
        records_to_delete = []
        page_token = None
        
        while True:
            result = await service.list_records(app_token, table_id, page_size=500, page_token=page_token)
            records = result.get('items', [])
            
            if not records:
                break
                
            for record in records:
                fields = record.get('fields', {})
                collected_at = fields.get('collected_at', '')
                
                if collected_at:
                    try:
                        record_date = datetime.fromisoformat(collected_at.split('+')[0])
                        if record_date.date() < cutoff_date.date():
                            records_to_delete.append({"record_id": record['record_id']})
                    except:
                        pass
            
            page_token = result.get('page_token')
            if not page_token:
                break
        
        print(f"   发现 {len(records_to_delete)} 条过期记录")
        
        if len(records_to_delete) == 0:
            print("✅ 无过期记录需要清理")
            notification_push.send_message(f"{msg_prefix} 飞书表格检查完成\n当前记录数: {total_records}/{limit_max}\n无过期记录需要清理")
            return True
        
        # 分批删除
        print("\n4. 开始删除过期记录...")
        token = await service.get_tenant_access_token()
        deleted_count = 0
        batch_size = 500  # 每批500条
        
        for i in range(0, len(records_to_delete), batch_size):
            batch = records_to_delete[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(records_to_delete) + batch_size - 1) // batch_size
            
            print(f"   处理第 {batch_num}/{total_batches} 批...")
            
            try:
                import httpx
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                delete_data = {"records": batch}
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=delete_data, timeout=30)
                    response.raise_for_status()
                    result = response.json()
                    
                    if result.get("code") == 0:
                        deleted_count += len(batch)
                        print(f"   ✅ 第 {batch_num} 批删除成功")
                    else:
                        print(f"   ❌ 第 {batch_num} 批删除失败: {result.get('msg')}")
                        
            except Exception as e:
                print(f"   ❌ 第 {batch_num} 批删除异常: {e}")
        
        # 最终状态检查
        final_count = await get_table_record_count(app_token, table_id)
        
        print(f"\n5. 清理结果:")
        print(f"   删除记录数: {deleted_count}")
        print(f"   清理后记录数: {final_count}")
        print(f"   释放空间: {total_records - final_count}")
        
        # 发送通知
        status_msg = "正常" if final_count < threshold_warning else "警告" if final_count < threshold_critical else "危险"
        msg = f"{msg_prefix} 飞书表格清理完成\n状态: {status_msg}\n清理前: {total_records} 条\n清理后: {final_count} 条\n删除: {deleted_count} 条"
        notification_push.send_message(msg)
        
        print("\n" + "=" * 60)
        print("✅ 智能清理完成!")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        error_msg = f"❌ 智能清理过程中发生错误: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        try:
            notification_push.send_message(error_msg)
        except:
            pass
        return False


if __name__ == "__main__":
    result = asyncio.run(smart_cleanup())
    sys.exit(0 if result else 1)

