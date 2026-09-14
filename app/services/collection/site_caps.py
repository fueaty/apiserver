# -*- coding: utf-8 -*-
"""站点「单轮产出上限」的唯一事实来源 + 容量守卫。

语义边界（**务必遵守**，防止把【预筛/阈值】误搬进来）
----------------------------------------------------
本名录只登记「站点 ``collect()`` 对外返回的**最终**条数上界」——即设计文档
``.workbuddy/_next/站点上限守卫设计.md`` §1 标【终】者。

**不属于**容量模型、**不得**登记于此的字面量：
  ·【预】预筛上限（只限制候选池 / 遍历规模，后续还有截断）；
  ·【阈】阈值 / 早停（``>= N``、``< N`` 这类控制流，含字段长度阈值）；
  ·【分】分页 / 页大小。

误登记会**改变采集行为**（分页 / 回退 / 去重 / 内容占比），不只是"条数"——
详见设计 §6.1。

导入方向（单向、无环、无第三方依赖）
------------------------------------
``sites/* → collection.site_caps → feishu.limits``

⚠️ ``app/services/feishu/limits.py`` 的「零 import」是**承重属性**：
``tests/test_capacity_budget.py`` 依赖"把 ``limits.py`` 复制到临时目录、子进程
``import limits`` 做文本变异"的隔离技巧。因此本模块**只**单向 import ``limits``
的容量常量，``limits.py`` **不得**反向 import 本模块（否则破坏该隔离前提）。

守卫时机
--------
本模块在 import 期执行 ``_assert_registry_sane()`` + ``_assert_capacity_guards()``。
任何加载站点模块的路径（``collection_pipeline`` / ``engine`` / 测试导入站点）都会
经过这里。常量一旦破坏不变式，**直接 raise ValueError 让进程起不来**——与
``limits._assert_capacity_budget()`` 同款"故意硬失败、不 warn"。
"""

from app.services.feishu import limits

# 每个站点「单轮最终产出上界」（条/轮）。**只登记【终】字面量**（设计 §1.3）。
SITE_ROUND_CAPS = {
    "people_daily": 50,
    "xinhua": 30,
    "cctv": 50,
    "thepaper": 100,
    "weibo": 50,
    "baidu": 50,
    "zhihu": 50,
    "tech_36kr": 50,
    "xiaohongshu": 30,
}

# 每日轮次：与 ``script/run_daily_task.sh`` 头部两条 cron（08:00 / 21:00）对应。
#
# ⚠️ 该「2 轮/天」假设**已被实际打破**：任何**手动多跑一轮**（``verify_run.sh``、
#    ``collection_pipeline.py`` 手动重放、回归重跑）都**不在**这 2 轮之内，会让当日
#    实际量**超过** ``Σ(上界) × 2``。⇒ 真正的安全底线是 **G1（单轮）**；
#    G2/G3 只是"防漂移"，**不是**"保证总账不超"。这一点刻意写进注释，避免又一次
#    "假安心"。
ROUNDS_PER_DAY = 2

PER_ROUND_CAP_TOTAL = sum(SITE_ROUND_CAPS.values())        # 460
WORST_CASE_DAILY = PER_ROUND_CAP_TOTAL * ROUNDS_PER_DAY    # 920

# 已裁定的「最坏日上界」基线（``Σ(上界) × 轮次`` = 920）。
# 任何站点上界被调大都必须同步改这里——这是 G2 棘轮的核心（见 ``_assert_capacity_guards``）。
#
# ⚠️ 已知的**数学事实**（不粉饰）：``WORST_CASE_DAILY × RETENTION_DAYS = 920 × 25 = 23000``
#    **大于** ``TABLE_RECORD_LIMIT = 20000``。即"最坏情况下 25 天装不下"本就为真——
#    本模块**不**假装它成立，只把当前最坏上界**冻结**下来、让任何漂移 fail-loud
#    （真正的账目裁定见设计 §5 第三步，依赖在飞的 P3 净日增量复测）。
ACKNOWLEDGED_WORST_CASE_DAILY = 920


def cap_for(site_code: str) -> int:
    """返回站点「单轮最终产出上界」。

    Args:
        site_code: 站点代码（必须已登记在 :data:`SITE_ROUND_CAPS`）。

    Returns:
        该站点的单轮产出上界（条/轮）。

    Raises:
        KeyError: 站点未登记（名录闭包被打破）。
    """
    return SITE_ROUND_CAPS[site_code]


# ---------------------------------------------------------------------------
# 守卫（import 期硬失败）
# ---------------------------------------------------------------------------
def _assert_registry_sane() -> None:
    """名录自身完整性：键为非空字符串、值为正整数。

    防手滑写成 ``0`` / 负数 / 浮点 / 布尔（``bool`` 是 ``int`` 的子类，需显式排除）。
    """
    if not SITE_ROUND_CAPS:
        raise ValueError("site_caps: SITE_ROUND_CAPS 为空——名录不得为空。")
    for code, cap in SITE_ROUND_CAPS.items():
        if not isinstance(code, str) or not code:
            raise ValueError(f"site_caps: 非法站点代码键：{code!r}")
        if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
            raise ValueError(
                f"site_caps: 站点 {code!r} 的单轮上界必须为**正整数**，得到 {cap!r}"
            )


def _assert_capacity_guards() -> None:
    """G1（单轮可写性，真·硬约束）+ G2（最坏日上界棘轮，防漂移）。

    与 ``limits._assert_capacity_budget()`` 同款"故意硬失败"。
    """
    # G1 —— 单轮 Σ(上界) 必须 ≤ WATERMARK。
    # 语义：单次 run 的 incoming = Σ(上界) = 460，写前预检 ensure_capacity(incoming)
    # 会把表压到 WATERMARK - incoming ≥ 0，⇒ 单轮**必然**写得下。这条**现在成立**，
    # 且任何站点上界被抬到使 Σ > WATERMARK 时**立即 raise**。
    if PER_ROUND_CAP_TOTAL > limits.WATERMARK:
        raise ValueError(
            f"G1 违反：单轮产出上界之和 PER_ROUND_CAP_TOTAL = {PER_ROUND_CAP_TOTAL} "
            f"> WATERMARK = {limits.WATERMARK}"
            f"（app/services/feishu/limits.py）。"
            f" 请下调某些站点的 SITE_ROUND_CAPS 上界，或复核 limits.WATERMARK。"
        )

    # G2 —— 最坏日上界「棘轮」：不再假装"上界能装进 25 天"（那是假的），而是**冻结**当前
    # 最坏日上界。任何站点上界**调大**都会把 WORST_CASE_DAILY 顶过 920 → 这里 raise，
    # 开发者被迫回来复算 retention / WATERMARK，并**显式**改 ACKNOWLEDGED_WORST_CASE_DAILY。
    # ⇒「调大某站上限 = 一次静默的容量预算突破」到此终结。
    if WORST_CASE_DAILY > ACKNOWLEDGED_WORST_CASE_DAILY:
        raise ValueError(
            f"G2 违反：最坏日上界 WORST_CASE_DAILY = {WORST_CASE_DAILY} "
            f"> 已裁定基线 ACKNOWLEDGED_WORST_CASE_DAILY = {ACKNOWLEDGED_WORST_CASE_DAILY}。"
            f" 你刚调大了某个站点的单轮上界——请**手工**复算保留窗口（RETENTION_DAYS）"
            f"与 WATERMARK，再显式更新 ACKNOWLEDGED_WORST_CASE_DAILY。"
        )


_assert_registry_sane()
_assert_capacity_guards()
