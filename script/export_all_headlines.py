#!/usr/bin/env python3
"""
导出全量采集库数据的脚本
用于分析智能选材引擎需求
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

async def export_all_headlines_to_json(output_file: str = "all_headlines_data.json"):
    """导出飞书多维表格中的全量采集数据到JSON文件"""
    try:
        # 初始化飞书服务
        feishu_service = FeishuService()
        
        # 获取配置
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            print("❌ 飞书配置缺失，请检查 config/credentials.yaml 文件")
            return False
        
        print(f"📱 正在从飞书多维表格获取全量数据...")
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 获取所有记录（使用较大的page_size以减少请求次数）
        all_records = []
        page_size = 10000  # 每页获取100条记录
        
        # 先获取第一页
        records = await feishu_service.list_records(app_token, table_id, page_size=page_size)
        
        if not records:
            msg = "❌ 未获取到任何记录"
            notification_push.send_message(f"❌ 未获取到任何记录")
            print(msg)
            return False

        today_str = today + " 00:00:00"
        print(f"   筛选今天数据（今天为 {today_str}）")
        # 提取记录数据
        for record in records:
            if "fields" in record:
                time_info = record["fields"]["collected_at"]
                data = datetime.fromisoformat(time_info).time()
                if data >= datetime.strptime(today_str, "%Y-%m-%d %H:%M:%S").time():
                    all_records.append(record["fields"])
        
        print(f"   已获取 {len(all_records)} 条记录")
        
        msg = f"✅ 已获取 {len(all_records)} 条记录"
        print(msg)
        
        # 保存到JSON文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)
        
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


def analyze_data_for_selection_engine(json_file: str = "all_headlines_data.json"):
    """分析数据以总结智能选材引擎的核心需求"""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"\n📊 智能选材引擎需求分析报告:")
        print(f"   总记录数: {len(data)}")
        
        # 统计各字段出现频率
        field_stats = {}
        for record in data:
            for field in record.keys():
                field_stats[field] = field_stats.get(field, 0) + 1
        
        print(f"\n   字段分布:")
        for field, count in sorted(field_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(data)) * 100
            print(f"   - {field}: {count} ({percentage:.1f}%)")
        
        # 统计各站点数据分布
        site_stats = {}
        for record in data:
            site = record.get("site_code", "unknown")
            site_stats[site] = site_stats.get(site, 0) + 1
            
        print(f"\n   站点分布:")
        for site, count in sorted(site_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(data)) * 100
            print(f"   - {site}: {count} ({percentage:.1f}%)")
        
        # 热度值分析
        hot_values = []
        for record in data:
            hot = record.get("hot")
            if hot is not None:
                try:
                    hot_values.append(int(hot))
                except (ValueError, TypeError):
                    pass
        
        if hot_values:
            avg_hot = sum(hot_values) / len(hot_values)
            max_hot = max(hot_values)
            min_hot = min(hot_values)
            print(f"\n   热度值分析:")
            print(f"   - 平均热度: {avg_hot:.0f}")
            print(f"   - 最高热度: {max_hot}")
            print(f"   - 最低热度: {min_hot}")
        
        # 排名分析
        rank_values = []
        for record in data:
            rank = record.get("rank")
            if rank is not None:
                try:
                    rank_values.append(int(rank))
                except (ValueError, TypeError):
                    pass
        
        if rank_values:
            avg_rank = sum(rank_values) / len(rank_values)
            max_rank = max(rank_values)
            min_rank = min(rank_values)
            print(f"\n   排名分析:")
            print(f"   - 平均排名: {avg_rank:.1f}")
            print(f"   - 最高排名: {max_rank}")
            print(f"   - 最低排名: {min_rank}")
        
        # 显示示例数据
        print(f"\n   示例数据 (前5条):")
        for i, record in enumerate(data[:5]):
            print(f"   记录 {i+1}:")
            for key, value in record.items():
                print(f"     {key}: {value}")
            print()
        
    except Exception as e:
        print(f"❌ 分析过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import asyncio
    
    # 导出数据
    print("🚀 开始导出飞书多维表格全量数据...")
    success = asyncio.run(export_all_headlines_to_json())
    
    if success:
        # 分析数据
        analyze_data_for_selection_engine()
        print("\n✅ 数据导出和分析完成")
    else:
        print("\n❌ 数据导出失败")
        sys.exit(1)