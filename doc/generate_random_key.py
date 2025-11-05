#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成的内容ID的脚本
"""

import string
import random
from datetime import datetime

def generate_content_id():
    """
    生成内容ID，格式为：时间戳+5位随机字符
    
    Returns:
        str: 生成的内容ID
    """
    # 生成5位随机字符
    all_characters = string.digits + string.ascii_letters
    # 随机选择5个字符
    random_characters = random.sample(all_characters, 5)
    # 将它们组合成一个字符串
    random_string = ''.join(random_characters)
    
    # 获取当前时间戳
    current_date = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # 组合为ID
    content_id = current_date + random_string
    return content_id

if __name__ == "__main__":
    print("生成的内容ID示例:")
    print(generate_content_id())