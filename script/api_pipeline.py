#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试通过API调用实现采集>入库>选材>入库完整流程的脚本
"""

import sys
import os
import asyncio
import httpx
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# 从auth_key.json读取认证令牌
def get_auth_token():
    try:
        with open('/root/apiserver/secret/auth_key.json', 'r') as f:
            auth_data = json.load(f)
            if auth_data.get('token_list'):
                # 使用第一个有效的令牌
                for token_info in auth_data['token_list']:
                    if token_info.get('status') == 'active':
                        return token_info.get('token')
    except Exception as e:
        print(f"读取认证令牌失败: {e}")
    return None

async def test_api_pipeline():
    """测试通过API调用实现采集>入库>选材>入库完整流程"""
    print("🚀 开始测试通过API调用实现采集>入库>选材>入库完整流程...")
    
    # 获取认证令牌
    auth_token = get_auth_token()
    if not auth_token:
        print("❌ 无法获取认证令牌")
        return False
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    base_url = "http://localhost:8000/api/v1"
    
    try:
        # 第一步：调用采集并存储接口，不指定site_code采集所有平台
        print("\n1. 调用采集并存储接口...")
        async with httpx.AsyncClient(timeout=300.0) as client:  # 增加超时时间到300秒(5分钟)
            collect_response = await client.get(
                f"{base_url}/enhanced/collect-and-store",
                headers=headers,
                params = {"site_code": ["weibo", "baidu", "zhihu"]}
            )
            
            if collect_response.status_code == 200:
                collect_data = collect_response.json()
                print(f"✅ 采集并存储成功: {collect_data.get('message')}")
                collected_count = collect_data.get('data', {}).get('stored_records', 0)
                print(f"   共存储 {collected_count} 条采集记录")
            else:
                print(f"❌ 采集并存储失败: {collect_response.status_code} - {collect_response.text}")
                return False
        
        # 等待一段时间确保数据写入完成
        await asyncio.sleep(5)
        
        # 第二步：调用选材并存储接口
        print("\n2. 调用选材并存储接口...")
        async with httpx.AsyncClient(timeout=120.0) as client:  # 增加超时时间到120秒
            select_response = await client.post(
                f"{base_url}/enhanced/select-and-store",
                headers=headers,
                json=["toutiao"]
            )
            
            if select_response.status_code == 200:
                select_data = select_response.json()
                print(f"✅ 选材并存储成功: {select_data.get('message')}")
                selected_count = select_data.get('data', {}).get('stored_records', 0)
                print(f"   共存储 {selected_count} 条选材记录")
            else:
                print(f"❌ 选材并存储失败: {select_response.status_code} - {select_response.text}")
                return False
        
        print("\n🎉 通过API调用实现采集>入库>选材>入库完整流程测试完成!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_api_pipeline())
    sys.exit(0 if result else 1)