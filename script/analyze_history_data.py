#!/usr/bin/env python3
"""
历史数据统计分析脚本
分析history_data目录下的所有头条数据文件
"""

import json
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict, Counter
import sys

# 添加项目根目录到Python路径
sys.path.append("..")

def get_history_data_files(history_dir: str = "history_data") -> list:
    """获取历史数据目录下的所有JSON文件"""
    history_path = Path(history_dir)
    if not history_path.exists():
        print(f"❌ 历史数据目录不存在: {history_dir}")
        return []
    
    json_files = list(history_path.glob("*_headlines_data.json"))
    json_files.sort()  # 按文件名排序
    return json_files

def load_history_data(history_dir: str = "history_data") -> dict:
    """加载所有历史数据"""
    files = get_history_data_files(history_dir)
    all_data = {}
    
    print(f"📊 正在加载历史数据文件...")
    print(f"📁 历史数据目录: {history_dir}")
    print(f"📄 找到 {len(files)} 个数据文件")
    
    for file_path in files:
        try:
            date_str = file_path.stem.replace("_headlines_data", "")
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                all_data[date_str] = data
                print(f"   ✅ 加载 {file_path.name}: {len(data)} 条记录")
        except Exception as e:
            print(f"   ❌ 加载 {file_path.name} 失败: {e}")
    
    return all_data

def analyze_date_distribution(data_dict: dict):
    """分析日期分布"""
    print(f"\n📅 日期分布统计:")
    dates = sorted(data_dict.keys())
    print(f"   时间范围: {dates[0]} 到 {dates[-1]}")
    print(f"   总天数: {len(dates)} 天")
    
    # 检查连续性
    date_objs = [datetime.strptime(date, "%Y-%m-%d") for date in dates]
    gaps = []
    for i in range(1, len(date_objs)):
        gap = (date_objs[i] - date_objs[i-1]).days
        if gap > 1:
            gaps.append((dates[i-1], dates[i], gap-1))
    
    if gaps:
        print(f"   📉 数据间断:")
        for start, end, gap_days in gaps[:5]:  # 只显示前5个间断
            print(f"      {start} 到 {end}: 缺失 {gap_days} 天")
    else:
        print(f"   ✅ 数据连续性良好")

def analyze_daily_statistics(data_dict: dict):
    """分析每日统计数据"""
    print(f"\n📈 每日数据量统计:")
    
    daily_counts = {}
    total_records = 0
    
    for date, records in data_dict.items():
        count = len(records)
        daily_counts[date] = count
        total_records += count
    
    # 按数量排序
    sorted_dates = sorted(daily_counts.items(), key=lambda x: x[1], reverse=True)
    
    print(f"   总记录数: {total_records}")
    print(f"   平均每日: {total_records/len(daily_counts):.1f} 条")
    print(f"   最大单日: {sorted_dates[0][1]} 条 ({sorted_dates[0][0]})")
    print(f"   最小单日: {sorted_dates[-1][1]} 条 ({sorted_dates[-1][0]})")
    
    # 显示最近几天的情况
    print(f"\n   🔍 最近7天数据量:")
    for date, count in sorted_dates[:7]:
        print(f"      {date}: {count} 条")

def analyze_field_consistency(data_dict: dict):
    """分析字段一致性"""
    print(f"\n📋 字段一致性分析:")
    
    field_stats = defaultdict(int)
    total_records = sum(len(records) for records in data_dict.values())
    
    # 统计所有字段出现次数
    for date, records in data_dict.items():
        for record in records:
            if isinstance(record, dict) and "fields" in record:
                fields = record["fields"]
                for field in fields.keys():
                    field_stats[field] += 1
            elif isinstance(record, dict):
                # 直接字段格式
                for field in record.keys():
                    field_stats[field] += 1
    
    print(f"   发现字段总数: {len(field_stats)}")
    print(f"   字段使用频率:")
    
    # 按频率排序显示
    sorted_fields = sorted(field_stats.items(), key=lambda x: x[1], reverse=True)
    for field, count in sorted_fields:
        percentage = (count / total_records) * 100
        status = "✅" if percentage >= 95 else "⚠️" if percentage >= 80 else "❌"
        print(f"      {status} {field}: {count}/{total_records} ({percentage:.1f}%)")

def analyze_site_distribution(data_dict: dict):
    """分析站点分布"""
    print(f"\n🌐 站点分布分析:")
    
    site_counter = Counter()
    total_records = 0
    
    for date, records in data_dict.items():
        for record in records:
            if isinstance(record, dict):
                # 处理两种格式
                if "fields" in record:
                    site_code = record["fields"].get("site_code", "unknown")
                else:
                    site_code = record.get("site_code", "unknown")
                
                site_counter[site_code] += 1
                total_records += 1
    
    print(f"   总记录数: {total_records}")
    print(f"   站点分布:")
    
    for site, count in site_counter.most_common():
        percentage = (count / total_records) * 100
        print(f"      {site}: {count} 条 ({percentage:.1f}%)")

def analyze_hot_value_distribution(data_dict: dict):
    """分析热度值分布"""
    print(f"\n🔥 热度值分析:")
    
    hot_values = []
    
    for date, records in data_dict.items():
        for record in records:
            if isinstance(record, dict):
                # 处理两种格式
                if "fields" in record:
                    hot_val = record["fields"].get("hot", "0")
                else:
                    hot_val = record.get("hot", "0")
                
                try:
                    # 转换热度值为数字
                    if isinstance(hot_val, str):
                        hot_val = hot_val.replace("万", "0000").replace("K", "000")
                        hot_val = float(hot_val) if hot_val else 0
                    hot_values.append(float(hot_val))
                except (ValueError, TypeError):
                    continue
    
    if hot_values:
        hot_values.sort()
        print(f"   记录总数: {len(hot_values)}")
        print(f"   平均热度: {sum(hot_values)/len(hot_values):.0f}")
        print(f"   最高热度: {max(hot_values):.0f}")
        print(f"   最低热度: {min(hot_values):.0f}")
        
        # 分位数分析
        import statistics
        if len(hot_values) >= 4:
            q1 = statistics.quantiles(hot_values, n=4)[0]
            q3 = statistics.quantiles(hot_values, n=4)[2]
            print(f"   第一四分位数: {q1:.0f}")
            print(f"   第三四分位数: {q3:.0f}")

def main():
    """主函数"""
    print("=" * 60)
    print("📊 头条历史数据统计分析")
    print("=" * 60)
    
    # 加载历史数据
    history_dir = "../history_data"  # 相对于script目录的路径
    data_dict = load_history_data(history_dir)
    
    if not data_dict:
        print("❌ 没有找到历史数据文件")
        return
    
    # 执行各项分析
    analyze_date_distribution(data_dict)
    analyze_daily_statistics(data_dict)
    analyze_field_consistency(data_dict)
    analyze_site_distribution(data_dict)
    analyze_hot_value_distribution(data_dict)
    
    print("\n" + "=" * 60)
    print("✅ 分析完成")
    print("=" * 60)

if __name__ == "__main__":
    main()