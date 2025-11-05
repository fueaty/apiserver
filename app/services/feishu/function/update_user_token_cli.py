#!/usr/bin/env python3
import sys
import os
import argparse

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

import yaml
from app.core.config import config_manager

def update_user_token(new_token):
    """更新用户访问令牌"""
    print("🔄 更新用户访问令牌...")
    
    try:
        # 获取配置文件路径
        config_file_path = "/root/apiserver/config/credentials.yaml"
        
        # 检查配置文件是否存在
        if not os.path.exists(config_file_path):
            print(f"❌ 配置文件不存在: {config_file_path}")
            return False
        
        # 读取现有配置
        with open(config_file_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        print("当前飞书配置:")
        feishu_config = config.get("feishu", {})
        current_token = feishu_config.get("user_access_token", "未设置")
        print(f"  用户访问令牌: {current_token}")
        
        # 更新配置
        if "feishu" not in config:
            config["feishu"] = {}
        config["feishu"]["user_access_token"] = new_token
        
        # 保存配置
        with open(config_file_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, indent=2)
        
        print("✅ 用户访问令牌更新成功!")
        print(f"  新令牌: {new_token}")
        return True
        
    except Exception as e:
        print(f"❌ 更新用户访问令牌时发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description='更新飞书用户访问令牌')
    parser.add_argument('token', nargs='?', help='新的用户访问令牌')
    parser.add_argument('--file', help='从文件读取令牌')
    
    args = parser.parse_args()
    
    if args.file:
        # 从文件读取令牌
        try:
            with open(args.file, 'r') as f:
                token = f.read().strip()
            if not token:
                print("❌ 文件中没有找到令牌")
                return 1
        except Exception as e:
            print(f"❌ 读取文件时出错: {e}")
            return 1
    elif args.token:
        # 直接使用提供的令牌
        token = args.token
    else:
        # 交互式输入
        print("请输入新的用户访问令牌:")
        token = input().strip()
        if not token:
            print("❌ 未提供令牌")
            return 1
    
    if update_user_token(token):
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())