#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正文回填脚本（需求②，P1）

扫描 headlines 中 ``content`` 为空的记录，限量抓取正文并回写 ``headlines.content``。

⚠️ 本脚本**不并入** 08:00/21:00 主采集 cron，仅手动/按需执行（见 PRD §3 取舍 / Q10）。

用法示例：
    python script/fetch_content_backfill.py --site-code thepaper --limit 20 --dry-run
    python script/fetch_content_backfill.py --limit 50
"""

import argparse
import asyncio
import os
import sys

# 允许脚本从仓库根目录直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import config_manager
from app.services.collection.content_fetcher import (
    ContentFetcher,
    FetchItem,
    infer_site_code,
    should_write_back,
    STATUS_SUCCESS,
)
from app.services.collection.robots_checker import robots_checker
from app.services.feishu.feishu_service import FeishuService
from app.services.feishu.limits import LIST_PAGE_SIZE
from app.utils.logger import logger


def _headlines_table():
    cfg = (config_manager.get_credentials() or {}).get("feishu", {}).get("tables", {}).get("headlines", {})
    return cfg.get("app_token"), cfg.get("table_id")


async def _scan_empty(feishu, app_token, table_id, site_code, limit):
    planned = []
    page_token = None
    pages = 0
    while pages < 40 and len(planned) < limit:
        data = await feishu.list_records(
            app_token, table_id, page_size=LIST_PAGE_SIZE, page_token=page_token
        )
        for item in (data or {}).get("items", []) or []:
            fields = item.get("fields") or {}
            if site_code and fields.get("site_code") != site_code:
                continue
            if str(fields.get("content") or "").strip():
                continue
            url = fields.get("url")
            if not url:
                continue
            planned.append({
                "record_id": item.get("record_id"),
                "url": url,
                "site_code": fields.get("site_code"),
            })
            if len(planned) >= limit:
                break
        page_token = (data or {}).get("page_token")
        pages += 1
        if not page_token:
            break
    return planned


async def run(args) -> int:
    feishu = FeishuService()
    app_token, table_id = _headlines_table()
    if not app_token or not table_id:
        logger.error("headlines 飞书配置缺失，无法回填")
        return 2

    planned = await _scan_empty(feishu, app_token, table_id, args.site_code, max(1, args.limit))
    print("[回填] 计划抓取 %d 条（site_code=%s, limit=%d）" % (len(planned), args.site_code, args.limit))

    if args.dry_run:
        for p in planned:
            print("  [DRY-RUN] %s -> %s" % (p["record_id"], p["url"]))
        print("[回填] DRY-RUN 结束，未抓取、未写入")
        return 0

    if not planned:
        print("[回填] 无可回填记录")
        return 0

    sites_config = config_manager.get_sites_config() or {}
    items = [
        FetchItem(
            url=p["url"],
            record_id=p["record_id"],
            site_code=p["site_code"] or infer_site_code(p["url"], sites_config),
        )
        for p in planned
    ]
    fetcher = ContentFetcher(robots=robots_checker, sites_config=sites_config)
    outcomes = await fetcher.fetch_many(items, concurrency=args.concurrency, timeout=args.timeout)

    to_update = []
    for outcome in outcomes:
        print("  [%s] %s (%sms, extractor=%s)"
              % (outcome.status, outcome.url, outcome.elapsed_ms, outcome.extractor))
        if outcome.status != STATUS_SUCCESS or not outcome.record_id:
            continue
        if should_write_back("", outcome.content, args.overwrite):
            to_update.append({"record_id": outcome.record_id, "fields": {"content": outcome.content}})

    written = 0
    if to_update:
        result = await feishu.batch_update_records(app_token, table_id, to_update)
        if result.get("code") == 0:
            written = result.get("data", {}).get("updated", len(to_update))
        else:
            logger.error("回写失败: %s", result.get("msg"))

    print("[回填] 完成：计划 %d / 抓取 %d / 写入 %d"
          % (len(planned), len(outcomes), written))
    return 0


def main():
    parser = argparse.ArgumentParser(description="headlines 正文回填（不并入 cron）")
    parser.add_argument("--site-code", dest="site_code", default=None, help="仅处理指定站点")
    parser.add_argument("--limit", type=int, default=50, help="最多处理条数（默认 50）")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="只列计划，不抓取不写入")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有 content")
    parser.add_argument("--concurrency", type=int, default=None, help="并发（默认服务端上限）")
    parser.add_argument("--timeout", type=int, default=None, help="单请求超时秒（默认 10，上限 30）")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
