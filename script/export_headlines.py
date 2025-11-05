#!/usr/bin/env python3
"""
从飞书多维表格中导出采集数据到JSON文件的脚本
用于分析和调试选材引擎评分逻辑
"""

import sys
import os
import json
from typing import List, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


async def export_headlines_to_json(output_file: str = "headlines_data.json"):
    """导出飞书多维表格中的采集数据到JSON文件"""
    try:
        # 初始化飞书服务
        feishu_service = FeishuService()
        
        # 获取配置
        creds = config_manager.get_credentials()
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        if not app_token or not table_id:
            # 尝试另一种配置结构
            app_token = creds.get("feishu", {}).get("app_token")
            table_id = creds.get("feishu", {}).get("table_id")
            
            if not app_token or not table_id:
                print("❌ 飞书配置缺失，请检查 config/credentials.yaml 文件")
                print(f"   当前配置: {creds}")
                return False
        
        print(f"📱 正在从飞书多维表格获取数据...")
        print(f"   App Token: {app_token}")
        print(f"   Table ID: {table_id}")
        
        # 获取所有记录（增加page_size以获取更多数据）
        records = await feishu_service.list_records(app_token, table_id, page_size=100)
        
        if not records:
            print("❌ 未获取到任何记录")
            return False
        
        # 提取记录数据
        headlines_data = []
        for record in records:
            if "fields" in record:
                headlines_data.append(record["fields"])
        
        print(f"✅ 成功获取 {len(headlines_data)} 条记录")
        
        # 保存到JSON文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(headlines_data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 数据已保存到 {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ 导出过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def analyze_headlines_data(json_file: str = "headlines_data.json"):
    """分析采集数据，查看字段分布情况"""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"\n📊 数据分析报告:")
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
        
        # 显示前几条记录作为示例
        print(f"\n   示例数据 (前5条):")
        for i, record in enumerate(data[:5]):
            print(f"   记录 {i+1}:")
            for key, value in record.items():
                print(f"     {key}: {value}")
            print()
            
        # 统计各站点数据分布
        site_stats = {}
        for record in data:
            site = record.get("site_code", "unknown")
            site_stats[site] = site_stats.get(site, 0) + 1
            
        print(f"   站点分布:")
        for site, count in sorted(site_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(data)) * 100
            print(f"   - {site}: {count} ({percentage:.1f}%)")
            
    except Exception as e:
        print(f"❌ 分析过程中发生错误: {e}")


if __name__ == "__main__":
    import asyncio
    
    # 导出数据
    print("🚀 开始导出飞书多维表格数据...")
    success = asyncio.run(export_headlines_to_json())
    
    if success:
        # 分析数据
        analyze_headlines_data()
        print("\n✅ 数据导出和分析完成")
    else:
        print("\n❌ 数据导出失败")
        sys.exit(1)