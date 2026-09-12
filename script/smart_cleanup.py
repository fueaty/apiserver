#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能飞书表格清理脚本（容量驱动）

背景
----
飞书多维表格单个数据表上限是 **20,000 条**（错误码 1254103 RecordExceedLimit），
不是 10 万条。旧版本这里把上限写成了 100,000，阈值定为 80,000 / 95,000，
结果表格涨到 2 万条时清理永远不会触发，采集任务每次写库都报：

    ❌ 采集任务执行失败，创建记录到飞书多维表格异常: RecordExceedLimit

现在所有阈值统一收敛到 app/services/feishu/limits.py（唯一事实来源），
本脚本只负责调用 FeishuService.cleanup_table()。

清理顺序（固定）
----------------
1. 按时间：删除 collected_at 早于 --days 的记录（不传 --days 则跳过）
2. 按容量：如果「剩余 + 本次待写入」超过水位线，从最旧的记录开始删，腾出空间

今日采集的记录默认最后才删，只有非今日数据不足以腾出空间时才会回退删除，
并在日志里明确告警。

用法
----
    python script/smart_cleanup.py                    # 仅容量清理，压到水位线以下
    python script/smart_cleanup.py --days 90          # 先按时间清理，再按容量兜底
    python script/smart_cleanup.py --incoming 800     # 为即将写入的 800 条预留空间
    python script/smart_cleanup.py --dry-run          # 只统计不删除（上线前预演）
    python script/smart_cleanup.py --table headlines  # 指定表（默认 headlines）
"""

import sys
import os
import asyncio
import argparse

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.feishu.feishu_service import FeishuService
from app.services.feishu.limits import describe, WATERMARK, TABLE_RECORD_LIMIT
from app.core.config import config_manager
import app.wework.notification_push as notification_push


async def smart_cleanup(days_to_keep=None, incoming=0, table_name="headlines",
                        dry_run=False, force=False):
    """
    容量驱动的表格清理。

    Args:
        days_to_keep: 保留最近多少天（None = 不做时间维度清理）
        incoming: 本次准备写入的记录数，用于预留空间
        table_name: 目标表名（对应 credentials.yaml 中 feishu.tables 的键）
        dry_run: 只统计不删除
        force: 解除时间清理的 50% 保护闸
    """
    print("=" * 60)
    print("🤖 智能飞书表格清理（容量驱动）")
    print(f"   目标表: {table_name} | 水位线: {WATERMARK} | 硬上限: {TABLE_RECORD_LIMIT}")
    if dry_run:
        print("   模式: DRY-RUN（只统计，不删除）")
    print("=" * 60)

    try:
        # 初始化服务
        print("\n1. 初始化服务...")
        service = FeishuService()
        creds = config_manager.get_credentials()
        table_conf = creds.get("feishu", {}).get("tables", {}).get(table_name, {})
        app_token = table_conf.get("app_token")
        table_id = table_conf.get("table_id")

        if not app_token or not table_id:
            msg = f"❌ 未找到表 {table_name} 的配置，请检查 config/credentials.yaml"
            print(msg)
            notification_push.send_message(msg)
            return False

        print(f"✅ 服务初始化完成 (app_token={app_token[:8]}...)")

        # 一次全表扫描 + 清理
        print("\n2. 开始清理...")
        stats = await service.cleanup_table(
            app_token,
            table_id,
            keep_days=days_to_keep,
            incoming=incoming,
            watermark=WATERMARK,
            protect_today=True,
            dry_run=dry_run,
            guard_ratio=1.0 if force else 0.5,
        )

        # 输出结果
        print("\n3. 清理结果:")
        print(f"   清理前: {stats['count_before']} 条  ({describe(stats['count_before'])})")
        print(f"   清理后: {stats['count_after']} 条  ({describe(stats['count_after'])})")
        if stats.get("age_cleanup_skipped"):
            print(f"   🚨 时间清理已被保护闸拦截（本次未按 --days 删除）")
        print(f"   计划删除: {stats['delete_planned']} 条"
              f"（按时间 {stats['deleted_by_age']} + 按容量 {stats['deleted_by_capacity']}）")
        if not dry_run:
            print(f"   实际删除: {stats['deleted_total']} 条")

        prefix = "🧪" if dry_run else ("✅" if stats["ok"] else "🚨")
        header = "容量预演" if dry_run else "表格清理完成"
        guard_note = "\n🚨 时间清理被保护闸拦截" if stats.get("age_cleanup_skipped") else ""
        msg = (
            f"{prefix} 飞书表格{header}: {table_name}\n"
            f"清理前: {stats['count_before']} 条\n"
            f"清理后: {stats['count_after']} 条\n"
            f"删除: {stats['deleted_total'] if not dry_run else stats['delete_planned']} 条\n"
            f"状态: {describe(stats['count_after'])}{guard_note}"
        )
        notification_push.send_message(msg)

        print("\n" + "=" * 60)
        print(f"{prefix} {stats['message']}")
        print("=" * 60)

        return stats["ok"]

    except Exception as e:
        error_msg = f"❌ 智能清理过程中发生错误: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        try:
            notification_push.send_message(error_msg)
        except Exception:
            pass
        return False


def main():
    parser = argparse.ArgumentParser(description="智能飞书表格清理（容量驱动）")
    parser.add_argument("--days", type=int, default=None,
                        help="保留天数，例如 90 表示删除 90 天前的数据；不传则只做容量清理")
    parser.add_argument("--incoming", type=int, default=0,
                        help="本次准备写入的记录数，用于预留空间")
    parser.add_argument("--table", type=str, default="headlines",
                        help="目标表名，对应 credentials.yaml 中 feishu.tables 的键")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计不删除")
    parser.add_argument("--force", action="store_true",
                        help="解除时间清理的 50%% 保护闸（确认要按 --days 清空历史数据时才用）")
    args = parser.parse_args()

    result = asyncio.run(smart_cleanup(
        days_to_keep=args.days,
        incoming=args.incoming,
        table_name=args.table,
        dry_run=args.dry_run,
        force=args.force,
    ))
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
