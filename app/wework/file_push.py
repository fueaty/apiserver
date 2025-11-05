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

def send_file_message(file_path):
    """发送文件消息"""
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("❌ 企业微信webhook URL未配置或配置文件不存在")
        return
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return
    
    # 获取文件名
    file_name = os.path.basename(file_path)
    
    # 构造文件上传的URL
    upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={webhook_url.split('=')[-1]}&type=file"
    
    # 准备文件数据
    try:
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            response = requests.post(upload_url, files={"media": (file_name, f)})
            response_data = response.json()
            
        if response_data.get("media_id"):
            print(f"✅ 文件上传成功: {file_name}")
            # 获取media_id并发送文件消息
            media_id = response_data.get("media_id")
            return send_file_message_with_media_id(webhook_url, media_id)
        else:
            print(f"❌ 文件上传失败: {response_data.get('errmsg')}")
            return False
    except Exception as e:
        print(f"❌ 文件上传过程中发生错误: {e}")
        return False

def send_file_message_with_media_id(webhook_url, media_id):
    """使用media_id发送文件消息"""
    data = {
        "msgtype": "file",
        "file": {
            "media_id": media_id
        }
    }
    
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_url.split('=')[-1]}"
    
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(send_url, data=json.dumps(data), headers=headers)
        result = response.json()
        
        if result.get("errcode") == 0:
            print("✅ 文件消息发送成功")
            return True
        else:
            print(f"❌ 文件消息发送失败: {result.get('errmsg')}")
            return False
    except Exception as e:
        print(f"❌ 发送文件消息时发生错误: {e}")
        return False

def send_text_message(message):
    """发送文本消息"""
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("❌ 企业微信webhook URL未配置或配置文件不存在")
        return
    
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_url.split('=')[-1]}"
    
    data = {
        "msgtype": "text",
        "text": {
            "content": message,
            "mentioned_list": ["@all"],
        },
    }
    
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(send_url, data=json.dumps(data), headers=headers)
        result = response.json()
        
        if result.get("errcode") == 0:
            print("✅ 文本消息发送成功")
            return True
        else:
            print(f"❌ 文本消息发送失败: {result.get('errmsg')}")
            return False
    except Exception as e:
        print(f"❌ 发送文本消息时发生错误: {e}")
        return False

if __name__ == "__main__":
    # 测试代码
    import sys
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        send_file_message(file_path)
    else:
        print("请提供文件路径作为参数")