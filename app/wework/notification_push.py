import asyncio
import aiohttp
import yaml
import os
import json
import requests

def get_webhook_url():
    """获取企业微信webhook URL"""
    # 从配置文件加载cookie
    # 构建相对于项目根目录的路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "..", "..", "config", "credentials.yaml")
    config_path = os.path.normpath(config_path)
    
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return ""
        
    with open(config_path, 'r', encoding='utf-8') as f:
        credentials = yaml.safe_load(f)
    webhook_url = credentials.get('wework', {}).get('webhook', "")
    return webhook_url

def send_message(message):
    """发送企业微信消息（同步版本）"""
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("❌ 企业微信webhook URL未配置或配置文件不存在")
        return
    
    data = {
        "msgtype": "text",
        "text": {
            "content": message,
            "mentioned_list": ["@all"],
        },
    }
    
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(webhook_url, data=json.dumps(data), headers=headers)
        print(f"📤 消息发送结果: {response.text}")
    except Exception as e:
        print(f"❌ 发送消息时出错: {e}")

async def send_message_async(message):
    """发送企业微信消息（异步版本）"""
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("❌ 企业微信webhook URL未配置或配置文件不存在")
        return
    
    data = {
        "msgtype": "text",
        "text": {
            "content": message,
            "mentioned_list": ["@all"],
        },
    }
    
    headers = {"Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=data, headers=headers) as response:
                result = await response.text()
                print(f"📤 消息发送结果: {result}")
    except Exception as e:
        print(f"❌ 发送消息时出错: {e}")

if __name__ == "__main__":
    message = "测试消息"
    send_message(message)