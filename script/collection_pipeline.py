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
        
        # 第三步：将采集结果存储到飞书表格（原始数据表）
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
        
        # 批量将记录插入飞书表格
        result = await feishu_service.batch_add_records(app_token, table_id, feishu_records)
        
        # 检查插入结果
        if result.get("code") == 0:
            record_count = len(result.get("data", {}).get("records", []))
            msg = f"✅ 采集任务执行成功，插入 {record_count} 条记录到飞书多维表格"
            notification_push.send_message(msg)
            print(msg)
        else:
            msg = f"❌ 采集任务执行失败，插入记录到飞书多维表格异常:\n{result.get('msg')}"
            notification_push.send_message(msg)
            print(msg)
            return False
        
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