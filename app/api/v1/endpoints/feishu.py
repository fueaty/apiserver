from fastapi import APIRouter, Depends, Body, HTTPException
from typing import List, Dict, Any
from ....services.feishu.feishu_service import FeishuService
# mock 治理（N3）：本接口的记录来自**请求体**，可能夹带带 is_mock 标记的演示数据，
# 必须在写入前按标记剔除，否则演示数据会经此口子静默入库（同为直写 headlines 的路径）。
from ....services.collection.mock_utils import split_real_and_mock
from ....utils.logger import logger
from .auth import verify_token

router = APIRouter()

@router.post("/sync", summary="同步数据到飞书多维表格")
async def sync_to_feishu(
    app_token: str = Body(..., embed=True, description="多维表格的App Token"),
    table_id: str = Body(..., embed=True, description="多维表格的Table ID"),
    records: List[Dict[str, Any]] = Body(..., embed=True, description="要同步的记录列表"),
    current_user: Any = Depends(verify_token) # 保护接口
):
    """
    接收采集到的数据，并将其批量同步到指定的飞书多维表格中。
    """
    feishu_service = FeishuService()

    # —— mock 治理（N3）——
    # 请求体可携带带 is_mock 标记的 mock 回退数据；这里与 pipeline / enhanced_collection
    # 同源：按标记把它剔除出写集并单独告警，绝不入库（与「形状差额」无关）。
    records, mock_records = split_real_and_mock(records)
    if mock_records:
        logger.warning(
            "feishu/sync：请求含 %d 条 mock 演示数据，已按 '%s' 标记排除出写集（未入库）。",
            len(mock_records), "is_mock",
        )

    success, message = await feishu_service.ensure_table_fields(app_token, table_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    result = await feishu_service.batch_add_records(
        app_token=app_token,
        table_id=table_id,
        records=records
    )
    
    if result.get("code") == 0:
        return {
            "code": 0,
            "message": "数据已成功同步到飞书多维表格",
            "data": result.get("data")
        }
    else:
        return {
            "code": result.get("code"),
            "message": f"飞书API返回错误: {result.get('msg')}",
            "data": result
        }
