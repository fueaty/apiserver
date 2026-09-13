# -*- coding: utf-8 -*-
"""mock 数据治理（写入路径的**显式**判据 + 采集回退的**显式 opt-in**）。

背景：若某站点采集失败/解析为空，历史上会**回退到 `_get_mock_data()`** 返回演示用的
假数据（xinhua / people_daily / tech_36kr / baidu / cctv / weibo / xiaohongshu）。
这些假数据**绝不允许进入飞书表**。

本模块把保证拆成**两层**，都由**意图**保证、都不靠 bug 兜底：

一、**写集侧**（"就算产生了 mock，也不入库"）：
  · 各站点在 mock 行上打**显式标记** ``is_mock=True``（见 MOCK_FLAG）——不是包装；
  · 写入路径用 `split_real_and_mock()` 按**标记**把 mock 行**排除**出写集，并**单独**上报。
  为什么「将来有人给 mock 包上 {"fields": item}」时仍然成立：`is_mock_record()`
  **同时**检查顶层与 ``fields`` 内层，故 mock 即使被包进
  ``{"fields": {"is_mock": True, ...}}`` 仍会被识别并排除。

二、**采集侧**（"生产默认根本不产生 mock"）—— 根因治理：
  过去「采集失败 → 伪造数据」是**默认行为**，写集侧只能被动兜底。现改为**显式 opt-in**：
  · `fallback_or_empty(site_code, reason, items)` 是**唯一**回退入口；
  · **默认（生产）返回 `[]` 并 warning**（含站点与原因）——不伪造任何数据；
  · 仅当环境变量 `APISERVER_ALLOW_MOCK=1`（见 ALLOW_MOCK_ENV）时才返回**打了标记**的演示数据。
  这样「将来新增站点忘了打标记」不再是唯一防线：**默认路径压根不产出 mock**。

⚠️ 依赖注入：本模块**不在 import 期**导入 `app.utils.logger`（那会拉入 app.core.config）。
日志改为**惰性**获取，保持本模块依赖极轻（仅 os / typing），便于离线测试。
"""

import os
from typing import Any, Dict, List, Optional, Tuple, Union

# mock 行的显式标记键。改此键必须同步所有站点与写入层（有测试锁：tests/test_mock_governance.py）。
MOCK_FLAG = "is_mock"

# 「采集失败是否允许回退到 mock 演示数据」的显式开关。**默认关闭**（生产不伪造）。
ALLOW_MOCK_ENV = "APISERVER_ALLOW_MOCK"

# 视作"开启"的取值（大小写不敏感）。
_TRUTHY = ("1", "true", "yes", "on")


def mock_allowed() -> bool:
    """当前是否允许在采集失败时回退到 mock 演示数据（显式 opt-in，默认关闭）。

    Returns:
        仅当环境变量 ``APISERVER_ALLOW_MOCK`` 取真值时为 True。
    """
    return (os.environ.get(ALLOW_MOCK_ENV) or "").strip().lower() in _TRUTHY


def _warn(msg: str, *args: Any) -> None:
    """惰性获取引擎 logger 记录 warning（避免 import 期强耦合 app.core.config）。

    取不到引擎 logger 时退化到 stdlib logging，保证告警**绝不**因环境而丢。
    """
    try:
        from app.utils.logger import logger
        logger.warning(msg, *args)
    except Exception:
        import logging
        logging.getLogger("apiserver.mock_utils").warning(msg % (args or ()))


def is_mock_record(record: Any) -> bool:
    """判断一条采集记录是否为 mock（演示/备用）数据。

    检查顺序（**刻意两层都查**，以抵御"将来把 mock 也包成 {'fields': item}"）：
      1) 顶层 ``record["is_mock"] is True``        —— mock 当前形态（扁平行）
      2) ``record["fields"]["is_mock"] is True``   —— 若 mock 被包装后的形态
    只有**严格 ``is True``** 才算 mock，避免误伤真实数据里恰好取到真值的同名字段。

    Args:
        record: 单条记录（任意类型；非 dict 一律视为非 mock）。

    Returns:
        是否为 mock 行。
    """
    if not isinstance(record, dict):
        return False
    if record.get(MOCK_FLAG) is True:
        return True
    fields = record.get("fields")
    if isinstance(fields, dict) and fields.get(MOCK_FLAG) is True:
        return True
    return False


def split_real_and_mock(records: List[Any]) -> Tuple[List[Any], List[Any]]:
    """把一批记录按 mock 标记拆成 (真实, mock)。

    写入层只用「真实」这批构造写集；「mock」这批**不入库**，
    仅用于**单独**上报（与「形状差额」分开，避免差额告警被 mock 回退刷屏）。

    Args:
        records: 记录列表（元素可为扁平行或 ``{"fields": item}`` 形态）。

    Returns:
        (real_records, mock_records)，均保持原顺序。
    """
    real: List[Any] = []
    mock: List[Any] = []
    for rec in records or []:
        (mock if is_mock_record(rec) else real).append(rec)
    return real, mock


def tag_mock(items: List[Any]) -> List[Any]:
    """给一批 mock 行打显式 MOCK_FLAG 标记（幂等，返回**新**对象，不改动入参）。

    · 扁平行          → 顶层打标记；
    · ``{"fields": {...}}`` 包装体 → 打在内层（`is_mock_record` 两层都查）。

    Args:
        items: 待打标记的 mock 行列表。

    Returns:
        打上标记的**新**列表（元素为新 dict；非 dict 元素原样保留）。
    """
    tagged: List[Any] = []
    for it in items or []:
        if isinstance(it, dict):
            new = dict(it)
            inner = new.get("fields")
            if isinstance(inner, dict):
                inner = dict(inner)
                inner[MOCK_FLAG] = True
                new["fields"] = inner
            else:
                new[MOCK_FLAG] = True
            tagged.append(new)
        else:
            tagged.append(it)
    return tagged


def fallback_or_empty(
    site_code: Optional[str],
    reason: str,
    items: Union[List[Any], Any, None] = None,
) -> List[Any]:
    """采集失败/解析为空时的**唯一**回退入口（显式 opt-in）。

    默认（生产）行为：**不伪造**——返回 ``[]`` 并 `logger.warning`（含站点与原因）。
    仅当 ``APISERVER_ALLOW_MOCK=1`` 时，才返回**打了 MOCK_FLAG 标记**的演示数据。

    为什么把回退收敛到一个入口：过去每个站点各自 ``results = self._get_mock_data()``，
    「是否伪造」散落在 7 处、且**默认就是伪造**；只要有一处漏改/新站点照抄，就又回到
    「静默造假」。集中一处后，治理对象从「N 个站点」收敛为「1 个函数」，且默认安全。

    Args:
        site_code: 站点编码（仅用于告警归因，可为 None）。
        reason:    回退原因（仅用于告警，例如 "HTTP 状态码 403" / "解析结果为空"）。
        items:     mock 数据来源。可为 **list**（eager），也可为返回 list 的
                   **零参 callable**（如 ``self._get_mock_data``，惰性——默认路径
                   根本不会构造假数据，`_get_mock_data()` 不会被调用）。

    Returns:
        默认：``[]``；opt-in 开启且 items 非空：打了 MOCK_FLAG 的 mock 行列表。
    """
    site = site_code or "?"
    if not mock_allowed():
        _warn(
            "采集回退：站点=%s 原因=%s → 返回空（生产禁止伪造数据；如需演示数据请设 %s=1）",
            site, reason, ALLOW_MOCK_ENV,
        )
        return []

    # 仅在显式 opt-in 时**才**构造 mock（惰性 callable 天然满足"默认不产出"）。
    data = items() if callable(items) else items
    tagged = tag_mock(list(data or []))
    _warn(
        "采集回退：站点=%s 原因=%s → 返回 %d 条 **mock 演示数据**"
        "（%s 已开启；仍会被写入层按 %s 标记排除）",
        site, reason, len(tagged), ALLOW_MOCK_ENV, MOCK_FLAG,
    )
    return tagged
