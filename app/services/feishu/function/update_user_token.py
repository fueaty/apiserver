#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新飞书用户访问令牌
"""

import sys
import os
import yaml

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

def update_user_token(new_token):
    """更新用户访问令牌
    
    Args:
        new_token (str): 新的用户访问令牌
        
    Returns:
        bool: 更新成功返回True，否则返回False
    """
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
    """主函数"""
    print("🔄 飞书用户访问令牌更新工具")
    print("=" * 40)
    
    if len(sys.argv) < 2:
        print("用法: python update_user_token.py <新的用户访问令牌>")
        print("示例: python update_user_token.py u-xxxxxx")
        return 1
    
    new_token = sys.argv[1]
    if update_user_token(new_token):
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())