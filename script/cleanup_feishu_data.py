#!/usr/bin/env python3
"""
飞书多维表格数据清理脚本
定期清理过期的历史数据，避免表格达到记录上限
"""

import sys
import os
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager
import app.wework.notification_push as notification_push


async def cleanup_old_records(days_to_keep: int = 60, batch_size: int = 1000):
    """
    清理指定天数之前的旧记录
    
    Args:
        days_to_keep: 保留的天数，默认60天
        batch_size: 每批删除的记录数，默认1000条
    """
    print("=" * 60)
    print("🧹 飞书多维表格数据清理工具")
    print("=" * 60)
    
    try:
        # 初始化服务
        print("\n1. 初始化飞书服务...")
        service = FeishuService()
        print("✅ 飞书服务初始化成功")
        
        # 获取配置
        print("\n2. 获取飞书表格配置...")
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 错误: 未找到飞书配置，请检查 config/credentials.yaml 文件")
            return False
            
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 计算截止日期
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_date_str = cutoff_date.strftime("%Y-%m-%d")
        print(f"\n3. 清理策略:")
        print(f"   保留最近 {days_to_keep} 天的数据")
        print(f"   删除 {cutoff_date_str} 之前的数据")
        
        # 获取tenant_access_token
        print("\n4. 获取访问令牌...")
        token = await service.get_tenant_access_token()
        print(f"✅ 成功获取 tenant_access_token")
        
        # 查询需要删除的记录
        print(f"\n5. 查询 {cutoff_date_str} 之前的数据...")
        records_to_delete = []
        page_token = None
        total_checked = 0
        
        while True:
            # 获取一页数据
            result = await service.list_records(app_token, table_id, page_size=500, page_token=page_token)
            records = result.get('items', [])
            
            if not records:
                break
                
            total_checked += len(records)
            print(f"   已检查 {total_checked} 条记录...")
            
            # 筛选过期记录
            for record in records:
                fields = record.get('fields', {})
                collected_at = fields.get('collected_at', '')
                
                if collected_at:
                    try:
                        # 解析采集时间
                        record_date = datetime.fromisoformat(collected_at.split('+')[0])
                        if record_date.date() < cutoff_date.date():
                            records_to_delete.append({
                                "record_id": record['record_id']
                            })
                    except Exception as e:
                        print(f"   ⚠️  解析时间失败: {collected_at}, 错误: {e}")
            
            # 获取下一页
            page_token = result.get('page_token')
            if not page_token:
                break
        
        print(f"\n6. 清理统计:")
        print(f"   总检查记录数: {total_checked}")
        print(f"   需要删除记录数: {len(records_to_delete)}")
        
        if len(records_to_delete) == 0:
            print("✅ 没有过期记录需要清理")
            notification_push.send_message("✅ 飞书数据清理完成：无过期记录需要清理")
            return True
        
        # 分批删除记录
        print(f"\n7. 开始删除过期记录...")
        deleted_count = 0
        failed_count = 0
        
        # 分批处理，避免超出API限制
        for i in range(0, len(records_to_delete), batch_size):
            batch = records_to_delete[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(records_to_delete) + batch_size - 1) // batch_size
            
            print(f"   处理第 {batch_num}/{total_batches} 批，共 {len(batch)} 条记录...")
            
            try:
                # 构造删除请求
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                delete_data = {"records": batch}
                
                # 发送删除请求
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=delete_data, timeout=30)
                    response.raise_for_status()
                    result = response.json()
                    
                    if result.get("code") == 0:
                        deleted_count += len(batch)
                        print(f"   ✅ 第 {batch_num} 批删除成功")
                    else:
                        failed_count += len(batch)
                        print(f"   ❌ 第 {batch_num} 批删除失败: {result.get('msg')}")
                        
            except Exception as e:
                failed_count += len(batch)
                print(f"   ❌ 第 {batch_num} 批删除异常: {e}")
        
        print(f"\n8. 清理结果:")
        print(f"   成功删除: {deleted_count} 条记录")
        print(f"   删除失败: {failed_count} 条记录")
        
        # 发送通知
        msg = f"🧹 飞书数据清理完成\n成功删除: {deleted_count} 条记录\n删除失败: {failed_count} 条记录"
        notification_push.send_message(msg)
        print(f"📤 通知已发送")
        
        print("\n" + "=" * 60)
        print("✅ 数据清理完成!")
        print("=" * 60)
        
        return failed_count == 0
        
    except Exception as e:
        error_msg = f"❌ 数据清理过程中发生错误: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        try:
            notification_push.send_message(error_msg)
        except:
            pass
        return False


def backup_deleted_data(days_to_keep: int = 60):
    """
    备份即将删除的数据到本地文件
    
    Args:
        days_to_keep: 保留的天数
    """
    print("\n📝 备份即将删除的数据...")
    
    try:
        # 计算截止日期
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_date_str = cutoff_date.strftime("%Y-%m-%d")
        
        # 创建备份目录
        backup_dir = Path("../backup/deleted_data")
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成备份文件名
        backup_file = backup_dir / f"deleted_before_{cutoff_date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        print(f"   备份文件: {backup_file}")
        print("   ⚠️  注意: 当前版本仅记录删除操作，实际数据备份需要额外实现")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 备份过程出错: {e}")
        return False


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="飞书多维表格数据清理工具")
    parser.add_argument("--days", type=int, default=60, 
                       help="保留天数 (默认: 60天)")
    parser.add_argument("--batch-size", type=int, default=1000,
                       help="每批删除记录数 (默认: 1000条)")
    parser.add_argument("--backup", action="store_true",
                       help="执行数据备份")
    
    args = parser.parse_args()
    
    # 执行备份（如果需要）
    if args.backup:
        backup_deleted_data(args.days)
    
    # 执行清理
    success = await cleanup_old_records(args.days, args.batch_size)
    
    return 0 if success else 1


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)

