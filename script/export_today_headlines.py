#!/usr/bin/env python3
"""
导出今天采集的数据脚本
根据 collected_at 字段筛选出今天采集的数据
"""

import sys
import os
import json
from typing import List, Dict, Any
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
# sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append("..")
from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager
import app.wework.file_push as file_push
import app.wework.notification_push as notification_push

today = datetime.now().strftime("%Y-%m-%d")

async def export_today_headlines_to_json(output_file: str = "today_headlines_data.json"):
    """导出飞书多维表格中今天采集的数据到JSON文件"""
    try:
        # 初始化飞书服务
        feishu_service = FeishuService()
        
        # 获取配置
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            msg = "❌ 错误：请确保 config/credentials.yaml 文件中已正确填写 app_token 和 table_id"
            notification_push.send_message(msg)
            print(msg)
            return False
        
        print(f"📱 正在从飞书多维表格获取数据...")
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        print(f"   筛选日期: {today}")
        
        # 获取所有记录（使用较大的page_size以减少请求次数）
        today_records = []
        page_size = 500  # 飞书API每页最多500条记录
        page_token = None
        total_fetched = 0
        today_date = datetime.strptime(today, "%Y-%m-%d").date()
        
        # 分页获取所有记录
        while True:
            # 获取一页记录
            page_data = await feishu_service.list_records(app_token, table_id, page_size=page_size, page_token=page_token)
            records = page_data.get("items", [])
            
            if not records:
                break
                
            total_fetched += len(records)
            print(f"   已获取 {total_fetched} 条记录...")
            
            # 提取记录数据并筛选今天的数据
            for record in records:
                if "fields" in record and "collected_at" in record["fields"]:
                    # 解析 collected_at 字段，格式为 "YYYY-MM-DD HH:MM:SS"
                    collected_at_str = record["fields"]["collected_at"]
                    try:
                        collected_at = datetime.strptime(collected_at_str, "%Y-%m-%d %H:%M:%S")
                        # 检查是否为今天采集的数据
                        if collected_at.date() == today_date:
                            today_records.append(record["fields"])
                    except ValueError:
                        print(f"⚠️  无效的 collected_at 格式: {collected_at_str}")
            
            # 检查是否有更多页面
            page_token = page_data.get("page_token")
            if not page_token:
                break
        
        print(f"✅ 成功获取今天采集的 {len(today_records)} 条记录")
        
        # 保存到JSON文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(today_records, f, ensure_ascii=False, indent=2)
        msg = f"✅ 数据已保存到 {output_file}"
        notification_push.send_message(msg)
        print(msg)
        file_push.send_file_message(output_file)
        return True
        
    except Exception as e:
        msg = f"❌ 获取数据过程中发生错误: {e}"
        notification_push.send_message(msg)
        print(msg)
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    import asyncio
    
    output_file = f"{today}_headlines_data.json"
    if len(sys.argv) > 1:
        output_file = sys.argv[1]
    
    print("🚀 开始导出今天采集的数据...")
    success = asyncio.run(export_today_headlines_to_json(output_file))
    
    if success:
        print("✅ 导出完成")
    else:
        print("❌ 导出失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
