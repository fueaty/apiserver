#!/usr/bin/env python3
"""
历史数据管理脚本
用于管理和维护历史数据文件
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime
import argparse

def move_old_files_to_history(root_dir: str = "..", days_threshold: int = 30):
    """将超过指定天数的JSON文件移动到history_data目录"""
    root_path = Path(root_dir).resolve()
    history_dir = root_path / "history_data"
    
    # 创建历史数据目录
    history_dir.mkdir(exist_ok=True)
    
    # 获取当前日期
    current_date = datetime.now()
    
    # 查找根目录下的JSON文件
    json_files = list(root_path.glob("*_headlines_data.json"))
    
    moved_count = 0
    print(f"🔍 查找需要移动的历史文件...")
    print(f"📁 根目录: {root_path}")
    print(f"📁 历史目录: {history_dir}")
    print(f"📅 阈值: {days_threshold} 天前")
    
    for file_path in json_files:
        try:
            # 从文件名提取日期
            date_str = file_path.stem.replace("_headlines_data", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            
            # 计算天数差
            days_diff = (current_date - file_date).days
            
            if days_diff >= days_threshold:
                # 移动文件
                target_path = history_dir / file_path.name
                shutil.move(str(file_path), str(target_path))
                print(f"   ✅ 移动: {file_path.name} ({days_diff} 天前)")
                moved_count += 1
            else:
                print(f"   ℹ️  保留: {file_path.name} ({days_diff} 天前)")
                
        except ValueError as e:
            print(f"   ⚠️  无法解析日期 {file_path.name}: {e}")
        except Exception as e:
            print(f"   ❌ 移动 {file_path.name} 失败: {e}")
    
    print(f"\n📊 移动完成: 共移动 {moved_count} 个文件")

def clean_empty_history_dirs(history_dir: str = "../history_data"):
    """清理空的历史数据目录"""
    history_path = Path(history_dir)
    
    if not history_path.exists():
        print(f"❌ 历史数据目录不存在: {history_dir}")
        return
    
    json_files = list(history_path.glob("*.json"))
    
    if not json_files:
        print(f"🗑️  历史数据目录为空，正在删除目录...")
        try:
            history_path.rmdir()
            print(f"✅ 目录已删除: {history_dir}")
        except Exception as e:
            print(f"❌ 删除目录失败: {e}")
    else:
        print(f"📁 历史数据目录包含 {len(json_files)} 个文件，保持不变")

def backup_history_data(history_dir: str = "../history_data", backup_dir: str = "../backup/history_data"):
    """备份历史数据"""
    history_path = Path(history_dir)
    backup_path = Path(backup_dir)
    
    if not history_path.exists():
        print(f"❌ 历史数据目录不存在: {history_dir}")
        return False
    
    # 创建备份目录
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # 如果备份目录已存在，先删除
        if backup_path.exists():
            shutil.rmtree(backup_path)
        
        # 复制整个目录
        shutil.copytree(history_path, backup_path)
        print(f"✅ 历史数据已备份到: {backup_dir}")
        return True
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return False

def list_history_files(history_dir: str = "../history_data", limit: int = None):
    """列出历史数据文件"""
    history_path = Path(history_dir)
    
    if not history_path.exists():
        print(f"❌ 历史数据目录不存在: {history_dir}")
        return
    
    json_files = list(history_path.glob("*.json"))
    json_files.sort()  # 按文件名排序
    
    if limit:
        json_files = json_files[-limit:]  # 只显示最新的N个文件
    
    print(f"📁 历史数据目录: {history_dir}")
    print(f"📄 找到 {len(json_files)} 个文件")
    
    if json_files:
        print(f"\n📋 文件列表:")
        for file_path in json_files:
            try:
                # 获取文件大小
                size = file_path.stat().st_size
                size_mb = size / (1024 * 1024)
                
                # 获取修改时间
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                
                # 读取记录数
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    record_count = len(data)
                
                print(f"   {file_path.name}")
                print(f"      大小: {size_mb:.2f} MB")
                print(f"      修改时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"      记录数: {record_count}")
                print()
                
            except Exception as e:
                print(f"   {file_path.name} - 读取失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="历史数据管理工具")
    parser.add_argument("action", choices=['move', 'clean', 'backup', 'list'], 
                       help="执行的操作")
    parser.add_argument("--days", type=int, default=30, 
                       help="移动文件的天数阈值 (默认: 30)")
    parser.add_argument("--limit", type=int, 
                       help="列出文件时的数量限制")
    parser.add_argument("--root-dir", default="..", 
                       help="项目根目录 (默认: ..)")
    parser.add_argument("--history-dir", default="../history_data", 
                       help="历史数据目录 (默认: ../history_data)")
    parser.add_argument("--backup-dir", default="../backup/history_data", 
                       help="备份目录 (默认: ../backup/history_data)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔧 历史数据管理工具")
    print("=" * 60)
    
    if args.action == 'move':
        move_old_files_to_history(args.root_dir, args.days)
    elif args.action == 'clean':
        clean_empty_history_dirs(args.history_dir)
    elif args.action == 'backup':
        backup_history_data(args.history_dir, args.backup_dir)
    elif args.action == 'list':
        list_history_files(args.history_dir, args.limit)
    
    print("=" * 60)

if __name__ == "__main__":
    main()

