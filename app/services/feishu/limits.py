# -*- coding: utf-8 -*-
"""
飞书多维表格容量限制（唯一事实来源）

这些是飞书开放平台的**硬限制**，不是可调参数。改动前请先核对官方错误码表：
https://open.feishu.cn/document/server-docs/docs/bitable-v1/app/create

- 1254103 RecordExceedLimit      单个数据表记录数超限，限制 20,000 条
- 1254104 RecordAddOnceExceedLimit 单次写接口操作记录数超限

历史上本项目把上限误当成 100,000 条（见 script/smart_cleanup.py 旧阈值
80,000/95,000/100,000），导致清理脚本永远不会触发，表格涨到 2 万条后
每次采集写入都报 RecordExceedLimit。因此这里集中定义一次，全项目复用。
"""

# 单个数据表记录数上限（错误码 1254103）
TABLE_RECORD_LIMIT = 20_000

# 单次写接口（batch_create / batch_delete）最多操作的记录数（错误码 1254104）
BATCH_WRITE_LIMIT = 500

# 飞书错误码常量
ERR_RECORD_EXCEED_LIMIT = 1254103          # 单表记录数超限，写入时抛出
ERR_RECORD_ADD_ONCE_EXCEED_LIMIT = 1254104  # 单次写接口操作记录数超限

# 安全水位线：清理的目标值，压到该值以下即认为安全（留 30% 余量给后续采集）
WATERMARK = 14_000

# 警告水位线：超过即告警
WARNING = 17_000

# 清理时按时间排序读取记录用的分页大小（飞书 list records 上限为 500）
LIST_PAGE_SIZE = 500


def is_safe(count: int) -> bool:
    """记录数是否处于安全水位。"""
    return count < WATERMARK


def describe(count: int) -> str:
    """给出一条人类可读的容量描述，用于日志与通知。"""
    pct = count / TABLE_RECORD_LIMIT * 100 if TABLE_RECORD_LIMIT else 0
    if count >= TABLE_RECORD_LIMIT:
        level = "🚨 已达上限"
    elif count >= WARNING:
        level = "🚨 危险"
    elif count >= WATERMARK:
        level = "⚠️ 偏高"
    else:
        level = "✅ 正常"
    return f"{level} {count}/{TABLE_RECORD_LIMIT} ({pct:.1f}%)"
