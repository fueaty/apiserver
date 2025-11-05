from fastapi import APIRouter, Depends, Body, HTTPException
from typing import List, Dict, Any
from ....services.feishu.feishu_service import FeishuService
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
