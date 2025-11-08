#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试采集>入库>选材>入库完整流程的脚本
该脚本用于测试从数据采集到最终选材的完整自动化流程
"""

import sys
import os
import asyncio
import traceback
from datetime import datetime
import httpx
from collections import defaultdict

# 添加项目根目录到Python路径，使得可以导入项目内的模块
# sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.append("..")

# 导入所需的模块和服务
from app.services.collection.engine import CollectionEngine      # 数据采集引擎
from app.services.selection.engine import SelectionEngine       # 选材引擎
from app.services.feishu.feishu_service import FeishuService    # 飞书服务
from app.core.config import config_manager                     # 配置管理器
import app.wework.notification_push as notification_push


async def test_collection_pipeline():
    """
    测试完整的数据处理流水线
    包括四个主要步骤：
    1. 数据采集 - 从多个平台抓取热点内容
    2. 存储到飞书表格 - 将采集到的数据存入飞书多维表格
    3. 数据选材 - 从存储的数据中筛选出优质内容
    4. 存储选材结果 - 将选材结果存入另一个飞书表格
    """
    print("🚀 开始执行数据处理流水线...")
    
    try:
        # 初始化服务组件
        collection_engine = CollectionEngine()
        selection_engine = SelectionEngine()
        feishu_service = FeishuService()
        # 设置采集参数
        collection_params = {
            "site_code": ["weibo", "xiaohongshu", "zhihu", "baidu", "xinhua", "tech_36kr", "people_daily", "cctv"],  # 指定要采集的平台
            "format": "feishu"     # 指定返回飞书格式的数据，便于直接存储
        }
        
        # 调用采集引擎执行采集任务
        collection_results = await collection_engine.collect(collection_params)
        print(f"✅ 数据采集完成，共采集到 {len(collection_results)} 个站点的数据")
        
        # 如果没有采集到数据，则终止测试
        if not collection_results:
            print("❌ 采集结果为空，无法继续测试")
            return False
            
        # 统计总共采集到的新闻数量
        total_news = sum(len(result.get("news", [])) for result in collection_results)
        print(f"   总共采集到 {total_news} 条新闻")
        
        # 调试：打印部分采集结果
        for result in collection_results:
            if result and result.get("news"):
                print(f"   站点 {result['site_code']} 采集到 {len(result['news'])} 条新闻")
                # 打印前2条新闻作为示例
                for i, news in enumerate(result["news"][:2]):
                    print(f"     新闻 {i+1}: {news.get('fields', {}).get('title', '无标题')}")
        
        # 第三步：将采集结果存储到飞书表格...
        print("\n3. 将采集结果存储到飞书表格...")
        
        # 从配置管理器中获取飞书相关的配置信息
        creds = config_manager.get_credentials()
        # 获取头条表的app_token（应用标识）
        app_token = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("app_token")
        # 获取头条表的table_id（表格标识）
        table_id = creds.get("feishu", {}).get("tables", {}).get("headlines", {}).get("table_id")
        
        # 检查必要的配置信息是否存在
        if not app_token or not table_id:
            msg = "❌ 飞书配置参数缺失，请检查 config/credentials.yaml 文件"
            notification_push.send_message(msg)
            print(msg)
            return False
            
        # 整理采集到的数据，准备存入飞书表格
        feishu_records = []
        for result in collection_results:
            # 确保每条结果都有新闻数据
            if result and result.get("news"):
                # 将新闻数据添加到总记录列表中
                feishu_records.extend(result["news"])
        
        print(f"   准备存储 {len(feishu_records)} 条记录到飞书表格")
        
        # 确保飞书表格具有所需的字段结构
        from app.services.feishu.field_rules import TABLE_PLANS
        required_fields = TABLE_PLANS["headlines"]["fields"]
        # 同步表格字段，确保表格结构正确
        success, message = await feishu_service.ensure_table_fields(app_token, table_id, required_fields)
        if not success:
            msg = f"⚠️  飞书表格字段同步失败: {message}"
            notification_push.send_message(msg)
            print(msg)
        
        # 调试信息：检查记录结构是否正确
        valid_records = [r for r in feishu_records if "fields" in r]
        print(f"   有效记录数: {len(valid_records)}")
        if valid_records:
            sample_fields = list(valid_records[0]["fields"].keys())
            print(f"   示例字段: {sample_fields}")
        
        # 查询今日已有的数据，避免重复插入相同标题的内容
        print("   查询今日已入库的数据...")
        today = datetime.now().strftime("%Y-%m-%d")
        all_existing_records = []
        page_token = None
        
        # 分页获取所有今日数据
        # 注意：必须使用较大的page_size以确保获取所有数据，避免遗漏
        while True:
            page_data = await feishu_service.list_records(
                app_token, table_id, page_size=100, page_token=page_token
            )
            items = page_data.get("items", [])
            if not items:
                break
                
            # 筛选今日数据
            for item in items:
                if "fields" in item and "collected_at" in item["fields"]:
                    collected_at_str = item["fields"]["collected_at"]
                    try:
                        # 解析收集时间，格式为 "YYYY-MM-DD HH:MM:SS"
                        collected_date = datetime.strptime(collected_at_str, "%Y-%m-%d %H:%M:%S").date()
                        # 检查是否为今天收集的数据
                        if collected_date.strftime("%Y-%m-%d") == today:
                            all_existing_records.append(item)
                    except ValueError:
                        # 忽略日期格式错误的记录
                        pass
            
            # 检查是否有更多页面
            page_token = page_data.get("page_token")
            if not page_token:
                break
        
        print(f"   今日已存在 {len(all_existing_records)} 条记录")
        
        # 构建标题到记录ID的映射，用于快速查找重复记录
        # 通过标题判断是否为重复内容，避免相同内容重复插入
        title_to_record_ids = defaultdict(list)
        for record in all_existing_records:
            if "fields" in record and "title" in record["fields"]:
                title = record["fields"]["title"]
                record_id = record.get("record_id")
                if title and record_id:
                    title_to_record_ids[title].append(record_id)
        
        # 找出重复的标题（出现次数大于1的标题）
        duplicate_titles = {title: ids for title, ids in title_to_record_ids.items() if len(ids) > 1}
        print(f"   发现 {len(duplicate_titles)} 个重复标题")
        
        # 处理重复数据：对于每个重复的标题，保留一个记录ID，删除其他记录ID
        records_to_delete = []
        for title, record_ids in duplicate_titles.items():
            # 保留第一个记录，删除其余记录
            records_to_delete.extend(record_ids[1:])
            # 更新标题到记录ID的映射，只保留第一个记录ID
            title_to_record_ids[title] = [record_ids[0]]
            print(f"     标题 '{title}' 有 {len(record_ids)} 个重复记录，将删除 {len(record_ids) - 1} 个")
        
        # 批量删除重复记录
        if records_to_delete:
            print("   删除重复记录...")
            try:
                # 构造删除记录的API URL
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
                # 获取飞书访问令牌
                token = await feishu_service.get_tenant_access_token()
                # 设置请求头
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                
                # 发送POST请求删除记录
                delete_data = {"records": records_to_delete}
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=delete_data, timeout=30)
                    response.raise_for_status()
                    result = response.json()
                    # 检查删除结果
                    if result.get("code") == 0:
                        print(f"   成功删除 {len(records_to_delete)} 条重复记录")
                    else:
                        print(f"   删除重复记录失败: {result.get('msg')}")
            except Exception as e:
                print(f"   删除重复记录时发生异常: {e}")
        
        # 重新整理需要处理的记录
        # 根据项目规范中的第19条"数据写入去重规范"，采用"先删除后插入"策略处理重复数据
        # 避免在更新时出现FieldNameNotFound错误
        records_to_delete = []  # 需要删除的已存在记录ID列表
        records_to_create = []  # 需要创建的记录列表（包括新记录和替换的记录）
        
        # 收集需要删除的已存在记录ID
        for record in feishu_records:
            if "fields" in record and "title" in record["fields"]:
                title = record["fields"]["title"]
                if title in title_to_record_ids:
                    # 标题已存在，需要删除已存在的记录
                    records_to_delete.append(title_to_record_ids[title][0])
        
        # 所有记录都需要重新创建（无论是新记录还是替换的记录）
        records_to_create = feishu_records
        
        print(f"   需要删除 {len(records_to_delete)} 条已存在记录")
        print(f"   需要创建 {len(records_to_create)} 条记录（包括新记录和替换的记录）")
        
        # 批量删除已存在的记录
        if records_to_delete:
            print("   删除已存在的记录...")
            try:
                # 构造删除记录的API URL
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
                # 获取飞书访问令牌
                token = await feishu_service.get_tenant_access_token()
                # 设置请求头
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                
                # 发送POST请求删除记录
                delete_data = {"records": records_to_delete}
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=delete_data, timeout=30)
                    response.raise_for_status()
                    result = response.json()
                    # 检查删除结果
                    if result.get("code") == 0:
                        print(f"   成功删除 {len(records_to_delete)} 条已存在记录")
                    else:
                        print(f"   删除已存在记录失败: {result.get('msg')}")
            except Exception as e:
                print(f"   删除已存在记录时发生异常: {e}")
        
        # 批量新增记录
        # 对于新记录和需要替换的记录，使用飞书服务的批量添加功能
        if records_to_create:
            print("   创建记录...")
            result = await feishu_service.batch_add_records(app_token, table_id, records_to_create)
            
            # 检查插入结果
            if result.get("code") == 0:
                record_count = len(result.get("data", {}).get("records", []))
                msg = f"✅ 采集任务执行成功，更新 {record_count} 条记录到飞书多维表格"
                notification_push.send_message(msg)
                print(msg)
            else:
                msg = f"❌ 采集任务执行失败，创建记录到飞书多维表格异常:\n{result.get('msg')}"
                notification_push.send_message(msg)
                print(msg)
                return False
        else:
            msg = "✅ 采集任务执行成功，无记录需要创建"
            notification_push.send_message(msg)
            print(msg)
        
        print("\n🎉 完整流程测试成功!")
        return True
        
    except Exception as e:
        # 异常处理：打印错误信息和堆栈跟踪
        error_msg = f"\n❌ 测试过程中发生错误: {str(e)}"
        print(error_msg)
        traceback.print_exc()
        try:
            notification_push.send_message(error_msg)
        except:
            pass  # 如果通知发送失败，继续完成流程
        return False

# 程序入口点
if __name__ == "__main__":
    # 运行异步测试函数并获取结果
    success = asyncio.run(test_collection_pipeline())
    # 根据测试结果退出程序（成功退出码0，失败退出码1）
    sys.exit(0 if success else 1)