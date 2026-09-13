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
from collections import defaultdict

# 添加项目根目录到Python路径，使得可以导入项目内的模块
# sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.append("..")

# 导入所需的模块和服务
from app.services.collection.engine import CollectionEngine      # 数据采集引擎
from app.services.selection.engine import SelectionEngine       # 选材引擎
from app.services.feishu.feishu_service import FeishuService, parse_record_time  # 飞书服务
from app.services.feishu.limits import (
    LIST_PAGE_SIZE,
    TABLE_RECORD_LIMIT,
    ERR_RECORD_EXCEED_LIMIT,
    describe,
)
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
        # 目标站点由 config/sites.yaml 的 enabled 字段决定（单一事实来源），
        # 这里**不再**传 site_code 白名单——否则 sites.yaml 的 enabled 形同虚设：
        # 新增/启用站点会静默 0 条入库且不报错
        # （防御见 app/services/collection/engine.py 的 _get_target_sites 告警）。
        # 如需临时收窄，请在调用 CollectionEngine.collect() 时显式传 site_code；
        # 引擎只会在 enabled 集合内**收窄，不会新增**（engine.py:146-164）。
        collection_params = {
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
        # 注意：使用 LIST_PAGE_SIZE(500) 拿到飞书单页上限，20000 条也只需 40 次请求；
        # 旧实现写的是 100，会翻 200 页，既慢又容易在中途被限流。
        while True:
            page_data = await feishu_service.list_records(
                app_token, table_id, page_size=LIST_PAGE_SIZE, page_token=page_token
            )
            items = page_data.get("items", [])
            if not items:
                break
                
            # 筛选今日数据
            for item in items:
                fields = item.get("fields") or {}
                if "collected_at" not in fields:
                    continue
                # 用统一解析器同时兜住 "%Y-%m-%d %H:%M:%S" 与 ISO8601 两种历史写法。
                # 旧实现只认前者，遇到 ISO 格式会静默 pass，导致去重失效、重复记录堆积。
                collected_dt = parse_record_time(fields.get("collected_at"))
                if collected_dt and collected_dt.date().strftime("%Y-%m-%d") == today:
                    all_existing_records.append(item)
            
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
                # 统一走 FeishuService.delete_records：按 500 分片 + 正确的 string[] 请求体。
                # 旧实现自己拼 payload 且一次提交全量 id，一旦超过 500 条就会整批失败。
                deleted = await feishu_service.delete_records(
                    app_token, table_id, records_to_delete
                )
                print(f"   成功删除 {deleted}/{len(records_to_delete)} 条重复记录")
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
                deleted = await feishu_service.delete_records(
                    app_token, table_id, records_to_delete
                )
                print(f"   成功删除 {deleted}/{len(records_to_delete)} 条已存在记录")
            except Exception as e:
                print(f"   删除已存在记录时发生异常: {e}")
        
        # 批量新增记录
        # 对于新记录和需要替换的记录，使用飞书服务的批量添加功能
        if records_to_create:
            # 写前容量预检：飞书单表硬上限 20,000 条（1254103 RecordExceedLimit），
            # 超限后写入会整体失败。这里按「清理后剩余 + 本次待写入」提前腾空间，
            # 让清理从"事后补救"变成"写前保证"。
            print("   写前容量预检...")
            try:
                capacity = await feishu_service.ensure_capacity(
                    app_token, table_id, incoming=len(records_to_create)
                )
                print(f"   容量状态: {describe(capacity['count_after'])} | {capacity['message']}")
                if capacity["deleted_total"] > 0:
                    print(f"   已清理 {capacity['deleted_total']} 条最旧记录"
                          f"（按容量 {capacity['deleted_by_capacity']} 条）")
                if not capacity["ok"]:
                    warn = f"⚠️ 飞书表格容量告警\n{capacity['message']}"
                    notification_push.send_message(warn)
                    print(warn)
            except Exception as exc:
                # 容量预检本身失败不应阻断采集，batch_add_records 内部还有一次超限自愈
                print(f"   ⚠️ 容量预检失败（继续写入，由写入层自愈兜底）: {exc}")

            print("   创建记录...")
            result = await feishu_service.batch_add_records(app_token, table_id, records_to_create)
            
            # 检查插入结果
            if result.get("code") == 0:
                record_count = len(result.get("data", {}).get("records", []))
                # 闭环检测：送出 N vs 写入 M。差额 = 被 FeishuService._align_records_with_fields
                # 丢弃的条数（形状不符）或分片写入失败的条数。历史 bug 正是
                # 「送出 329 / 写入 227 / 差额 102 ≈ thepaper 全部」被当成正常成功。
                sent_count = len(records_to_create)
                diff = sent_count - record_count
                if diff > 0:
                    gap_msg = (f"⚠️ 采集写入差额：送出 {sent_count} 条 / 写入 {record_count} 条 "
                               f"/ 差额 {diff} 条（疑似形状不符被丢弃，见对齐告警日志）")
                    notification_push.send_message(gap_msg)
                    print(gap_msg)
                msg = f"✅ 采集任务执行成功，更新 {record_count} 条记录到飞书多维表格"
                notification_push.send_message(msg)
                print(msg)
            else:
                code = result.get("code")
                hint = ""
                if code == ERR_RECORD_EXCEED_LIMIT:
                    hint = (f"\n原因: 单表记录数已达上限 {TABLE_RECORD_LIMIT} 条，"
                            f"且紧急清理未能腾出足够空间，请人工介入。")
                msg = (f"❌ 采集任务执行失败，创建记录到飞书多维表格异常:\n"
                       f"code={code} {result.get('msg')}{hint}")
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