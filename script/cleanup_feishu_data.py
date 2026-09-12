#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书多维表格数据清理脚本

被 script/scheduled_cleanup.sh（每日 02:00 cron）调用，因此 CLI 参数保持向后兼容：
    python script/cleanup_feishu_data.py --days 90 --batch-size 500

与历史版本的区别
----------------
旧版本**只按时间清理**（删掉 N 天前的数据）。当表格已经涨到 20,000 条上限时，
如果这 2 万条都落在保留窗口内，清理一条也删不掉，采集任务继续报：

    RecordExceedLimit（错误码 1254103，单表上限 20,000 条）

现在改为两段式：
    1. 按时间清理  —— 删除 collected_at 早于 --days 的记录
    2. 按容量兜底  —— 若清理后仍高于安全水位线，从最旧的记录开始删，压到水位线以内

清理逻辑复用 FeishuService.cleanup_table()，阈值统一来自
app/services/feishu/limits.py，不再在脚本里写死数字。
"""

import sys
import os
import asyncio
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.feishu.feishu_service import FeishuService
from app.services.feishu.limits import describe, WATERMARK, TABLE_RECORD_LIMIT
from app.core.config import config_manager
import app.wework.notification_push as notification_push


async def cleanup_old_records(days_to_keep=None,
                              batch_size: int = 500,
                              table_name: str = "headlines",
                              dry_run: bool = False,
                              force: bool = False):
    """
    清理过期数据，并保证表格回到安全水位以内。

    Args:
        days_to_keep: 保留的天数；None（默认）= 不做时间清理，只按容量清理。
            ⚠️ 注意：单表上限 20,000 条，按当前约 400 条/天 的采集速率，
            90 天数据需要约 36,000 条，**在 20,000 条的表里装不下**。
            因此日常维护应依赖容量清理，慎用大跨度的 --days。
        batch_size: 保留参数以兼容旧 cron 调用；实际分片大小由飞书接口上限
                    （BATCH_WRITE_LIMIT = 500，错误码 1254104）决定，此处仅记录。
        table_name: 目标表名
        dry_run: 只统计不删除
        force: 解除时间清理 50% 保护闸（cleanup_table guard_ratio）
    """
    print("=" * 60)
    print("🧹 飞书多维表格数据清理工具")
    retain = f"{days_to_keep} 天" if days_to_keep is not None else "不限（仅按容量）"
    print(f"   目标表: {table_name} | 保留: {retain} | "
          f"水位线: {WATERMARK} | 硬上限: {TABLE_RECORD_LIMIT}")
    if dry_run:
        print("   模式: DRY-RUN（只统计，不删除）")
    print("=" * 60)

    try:
        # 初始化服务
        print("\n1. 初始化飞书服务...")
        service = FeishuService()
        print("✅ 飞书服务初始化成功")

        # 获取配置
        print("\n2. 获取飞书表格配置...")
        creds = config_manager.get_credentials()
        table_conf = creds.get("feishu", {}).get("tables", {}).get(table_name, {})
        app_token = table_conf.get("app_token")
        table_id = table_conf.get("table_id")

        if not app_token or not table_id:
            msg = f"❌ 未找到表 {table_name} 的配置，请检查 config/credentials.yaml"
            print(msg)
            notification_push.send_message(msg)
            return False

        print(f"   App Token: {app_token[:8]}...")
        print(f"   Table ID:  {table_id}")

        print(f"\n3. 清理策略:")
        if days_to_keep is not None:
            cutoff = datetime.now() - timedelta(days=days_to_keep)
            guard = "已解除(force)" if force else "50%"
            print(f"   ① 按时间：删除 {days_to_keep} 天前（早于 {cutoff:%Y-%m-%d}）的数据"
                  f"（保护闸: {guard}）")
        else:
            print(f"   ① 按时间：跳过（未指定 --days）")
        print(f"   ② 按容量：若高于水位线 {WATERMARK}，从最旧的记录开始删到水位线以内")
        print(f"   （每批 {batch_size} 条，飞书单次写上限 500 条）")

        # 全表扫描 + 两段式清理（一次扫描搞定，避免反复翻页）
        print(f"\n4. 开始清理...")
        stats = await service.cleanup_table(
            app_token,
            table_id,
            keep_days=days_to_keep,
            incoming=0,
            watermark=WATERMARK,
            protect_today=True,
            dry_run=dry_run,
            guard_ratio=1.0 if force else 0.5,
        )

        # 输出统计
        print(f"\n5. 清理统计:")
        print(f"   清理前: {stats['count_before']} 条  ({describe(stats['count_before'])})")
        print(f"   清理后: {stats['count_after']} 条  ({describe(stats['count_after'])})")
        if stats.get("age_cleanup_skipped"):
            print(f"   🚨 时间清理已被保护闸拦截（本次未按 --days 删除）")
        print(f"   按时间删除: {stats['deleted_by_age']} 条")
        print(f"   按容量删除: {stats['deleted_by_capacity']} 条")
        print(f"   计划删除合计: {stats['delete_planned']} 条")
        if not dry_run:
            print(f"   实际删除: {stats['deleted_total']} 条")
            failed = stats['delete_planned'] - stats['deleted_total']
            if failed:
                print(f"   ⚠️ 删除失败: {failed} 条（详见上方 [ERROR] 日志）")

        # 发送通知
        prefix = "🧪" if dry_run else ("✅" if stats["ok"] else "🚨")
        header = "容量预演" if dry_run else "数据清理完成"
        guard_note = "\n🚨 时间清理被保护闸拦截" if stats.get("age_cleanup_skipped") else ""
        msg = (
            f"{prefix} 飞书{header}: {table_name}\n"
            f"清理前: {stats['count_before']} 条\n"
            f"清理后: {stats['count_after']} 条\n"
            f"删除: {stats['deleted_total'] if not dry_run else stats['delete_planned']} 条\n"
            f"状态: {describe(stats['count_after'])}{guard_note}"
        )
        notification_push.send_message(msg)
        print("📤 通知已发送")

        print("\n" + "=" * 60)
        print(f"{prefix} {stats['message']}")
        print("=" * 60)

        return stats["ok"]

    except Exception as e:
        error_msg = f"❌ 数据清理过程中发生错误: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        try:
            notification_push.send_message(error_msg)
        except Exception:
            pass
        return False


def backup_deleted_data(days_to_keep: int = 60):
    """
    备份即将删除的数据到本地文件

    注意：当前版本仅记录删除操作，实际数据备份需要额外实现。
    """
    print("\n📝 备份即将删除的数据...")

    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_date_str = cutoff_date.strftime("%Y-%m-%d")

        backup_dir = Path("../backup/deleted_data")
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_file = backup_dir / (
            f"deleted_before_{cutoff_date_str}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        print(f"   备份文件: {backup_file}")
        print("   ⚠️  注意: 当前版本仅记录删除操作，实际数据备份需要额外实现")

        return True

    except Exception as e:
        print(f"   ❌ 备份过程出错: {e}")
        return False


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="飞书多维表格数据清理工具")
    parser.add_argument("--days", type=int, default=None,
                        help="保留天数。不传（默认）= 不做时间清理，只按容量清理。"
                             "注意：单表上限 20000 条，按约 400 条/天 的速率，"
                             "90 天数据需约 36000 条，装不下，慎用大跨度 --days")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="每批删除记录数 (默认: 500，飞书单次写上限 500，传更大值无效)")
    parser.add_argument("--table", type=str, default="headlines",
                        help="目标表名，对应 credentials.yaml 中 feishu.tables 的键")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计不删除")
    parser.add_argument("--force", action="store_true",
                        help="解除时间清理的 50%% 保护闸（确认要按 --days 清空历史数据时才用）")
    parser.add_argument("--backup", action="store_true",
                        help="执行数据备份")

    args = parser.parse_args()

    if args.backup:
        backup_deleted_data(args.days or 90)

    success = await cleanup_old_records(
        days_to_keep=args.days,
        batch_size=args.batch_size,
        table_name=args.table,
        dry_run=args.dry_run,
        force=args.force,
    )

    return 0 if success else 1


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)
