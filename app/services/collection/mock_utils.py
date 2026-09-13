# -*- coding: utf-8 -*-
"""mock 数据治理（写入路径的**显式**判据）。

背景：若某站点采集失败/解析为空，会**回退到 `_get_mock_data()`** 返回演示用的假数据
（xinhua / people_daily / tech_36kr 等）。这些假数据**绝不允许进入飞书表**。

历史形态（危险）：这些站点的 mock 行是**扁平 dict**，恰好因写入层
`FeishuService._align_records_with_fields` 要求 ``{"fields": item}`` 形状而被**顺带丢弃**。
—— 这是「**靠 bug 兜底**」：一旦有人给 mock 也包上 ``{"fields": item}``（看起来是"修好了
形状不一致"），mock 就会**静默入库**，污染生产表。

本模块把这条保证改成**由意图保证**：
  · 各站点在 mock 行上打**显式标记** ``is_mock=True``（见 MOCK_FLAG）——不是包装；
  · 写入路径（script/collection_pipeline.py）用 `split_real_and_mock()` 按**标记**把
    mock 行**排除**出写集，并**单独**上报（不计入「形状差额」）。

为什么「将来有人给 mock 包上 {"fields": item}」时仍然成立：
`is_mock_record()` **同时**检查顶层与 ``fields`` 内层，故 mock 即使被包进
``{"fields": {"is_mock": True, ...}}`` 仍会被识别并排除。
"""

from typing import Any, Dict, List, Tuple

# mock 行的显式标记键。改此键必须同步所有站点与写入层（有测试锁：tests/test_mock_governance.py）。
MOCK_FLAG = "is_mock"


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

    写入层只用「真实」这批构造 `feishu_records`；「mock」这批**不入库**，
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
