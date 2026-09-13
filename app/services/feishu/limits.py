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

⚠️ 本模块在 import 期执行 `_assert_capacity_budget()`。常量一旦不满足容量不变式，
会**直接 raise ValueError 让进程起不来**——这是有意为之：历史上正是常量静默超限，
表格才卡死 3 个月无人察觉。不要把它软化成 warn / logger.error。
"""

# 单个数据表记录数上限（错误码 1254103）
TABLE_RECORD_LIMIT = 20_000

# 单次写接口（batch_create / batch_delete）最多操作的记录数（错误码 1254104）
BATCH_WRITE_LIMIT = 500

# 飞书错误码常量
ERR_RECORD_EXCEED_LIMIT = 1254103          # 单表记录数超限，写入时抛出
ERR_RECORD_ADD_ONCE_EXCEED_LIMIT = 1254104  # 单次写接口操作记录数超限

# 保留窗口（天）——「飞书表保留多久」的唯一事实来源。
# 业务决策：由 35 天收紧为 25 天（配套「启用 thepaper 站点」后日量上升）。
# script/cleanup_feishu_data.py（--days 默认值）与 script/scheduled_cleanup.sh
# 都必须从这里取，不得再写死天数（历史教训：两处数字漂移）。
RETENTION_DAYS = 25

# 日采集预算（条/天）——容量守卫（_assert_capacity_budget）的算术输入。
#
# 算法：
#   现有 8 个已启用站点实测合计 251 条/轮 × 2 轮/天             = 502
#   thepaper 硬上限 100 条/轮（见 sites/thepaper.py: MAX_RESULTS）× 2 = 200
#   朴素上界 502 + 200                                          = 702
#   本常量取 630（不取 702）：
#     · 25 天 × 630 = 15,750 ≤ WATERMARK(17,000) 成立；
#       若取朴素上界 702，则 25 × 702 = 17,550 > WATERMARK，守卫会直接 raise，
#       「保留 25 天」在 20,000 条的表里数学上不成立；
#     · 且与实测相符：9/12 = 253 条/天、9/13 = 427 条/天，计入 thepaper 后约 630。
#
# ⚠️ 该值是**有界近似**，不是精确预测。若 thepaper.py 的 MAX_RESULTS 被抬高，
#    必须同步复核本常量与 WATERMARK，否则 import 期守卫会 raise。
DAILY_BUDGET = 630

# 安全水位线：清理的目标值，压到该值以下即认为安全。
# ⚠️ 余量代价（不粉饰）：TABLE_RECORD_LIMIT=20,000 时，WATERMARK=17,000 只留
#    **15%** 余量（旧值 14,000 留 30%）。这是新增 thepaper 站点的真实代价，
#    安全缓冲已被压缩一半，不要再假设还有 30% 缓冲。
WATERMARK = 17_000

# 警告水位线：超过即告警。
WARNING = 18_500

# 清理时按时间排序读取记录用的分页大小（飞书 list records 上限为 500）
LIST_PAGE_SIZE = 500


def _assert_capacity_budget() -> None:
    """import 期容量预算守卫（与 insights_service._assert_field_consistency 同款）。

    三条不变式，任一不成立即 raise ValueError：

      1. ``RETENTION_DAYS * DAILY_BUDGET <= WATERMARK``
         —— 保留窗口内累积的量必须装得进安全水位线，否则「保留 N 天」名不副实
         （容量段会把 25 天压回更短）。
      2. ``WATERMARK < WARNING`` —— 安全线与告警线顺序不能反。
      3. ``WARNING < TABLE_RECORD_LIMIT`` —— 告警线必须在硬上限之内。

    **故意**硬失败（不 warn、不 logger.error）：让"谁把常量改坏 → 整个 app 起不来"
    立刻暴露，而不是等表格再次卡死。
    """
    budget = RETENTION_DAYS * DAILY_BUDGET
    if budget > WATERMARK:
        raise ValueError(
            "容量预算超限：RETENTION_DAYS(%d) × DAILY_BUDGET(%d) = %d > WATERMARK(%d)。"
            " 保留窗口在硬上限内装不下——请调小 RETENTION_DAYS/DAILY_BUDGET，"
            "或调大 WATERMARK（并复核 WARNING < TABLE_RECORD_LIMIT）。"
            % (RETENTION_DAYS, DAILY_BUDGET, budget, WATERMARK)
        )
    if not WATERMARK < WARNING:
        raise ValueError(
            "水位线顺序错误：要求 WATERMARK(%d) < WARNING(%d)。" % (WATERMARK, WARNING)
        )
    if not WARNING < TABLE_RECORD_LIMIT:
        raise ValueError(
            "水位线顺序错误：要求 WARNING(%d) < TABLE_RECORD_LIMIT(%d)。"
            % (WARNING, TABLE_RECORD_LIMIT)
        )


_assert_capacity_budget()


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
