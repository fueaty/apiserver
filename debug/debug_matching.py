#!/usr/bin/env python3
"""
调试选材引擎匹配逻辑的脚本
"""

import sys
import os
import json

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.selection.engine import SelectionEngine


def debug_matching():
    """调试匹配逻辑"""
    # 创建一个测试热点
    test_hotspot = {
        "title": "江苏省委书记为泰州队颁奖",
        "category": "",
        "keywords": []
    }
    
    # 加载平台配置
    selection_engine = SelectionEngine()
    
    # 测试不同平台的匹配情况
    platforms = ["toutiao", "weibo", "zhihu", "xiaohongshu"]
    
    for platform in platforms:
        print(f"\n📱 平台: {platform}")
        platform_config = selection_engine.platform_profiles.get(platform, {})
        print(f"   平台配置: {platform_config.get('content_preferences', [])}")
        
        # 调用匹配方法
        match_score = selection_engine._calculate_content_match_enhanced(test_hotspot, platform_config)
        print(f"   匹配得分: {match_score}")
        
        # 详细分析
        content_preferences = platform_config.get('content_preferences', [])
        title = test_hotspot["title"].lower()
        
        print(f"   标题: {title}")
        for pref in content_preferences:
            if pref.lower() in title:
                print(f"   匹配偏好: '{pref}' 在标题中找到")


if __name__ == "__main__":
    debug_matching()