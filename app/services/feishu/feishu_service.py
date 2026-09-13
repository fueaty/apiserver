import asyncio
import time
import httpx
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Any, List, Optional, Set, Tuple
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from ...core.config import config_manager
from .field_rules import BASE_FIELD_DEFINITIONS, REQUIRED_FIELDS
from .limits import (
    TABLE_RECORD_LIMIT,
    BATCH_WRITE_LIMIT,
    WATERMARK,
    WARNING,
    LIST_PAGE_SIZE,
    ERR_RECORD_EXCEED_LIMIT,
    describe,
)

# API URL 常量
FEISHU_TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_BITABLE_RECORDS_BATCH_CREATE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
FEISHU_BITABLE_RECORDS_BATCH_UPDATE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
FEISHU_BITABLE_RECORDS_BATCH_DELETE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
FEISHU_BITABLE_FIELDS_LIST_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
FEISHU_BITABLE_FIELD_DELETE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}"


def parse_record_time(value: Any) -> Optional[datetime]:
    """
    尽量把飞书返回的 collected_at 解析成 naive datetime。

    飞书文本字段可能返回 str、list[dict]（富文本）或数字时间戳，历史数据里
    同时存在 "%Y-%m-%d %H:%M:%S" 与 ISO8601（带时区偏移）两种写法，这里统一兜住。
    解析失败返回 None，调用方应按“时间未知”处理。
    """
    if value is None:
        return None

    # 富文本字段：[{"text": "2026-09-12 10:00:00", "type": "text"}]
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            value = first.get("text") or first.get("value") or ""
        else:
            value = first

    # 毫秒 / 秒级时间戳
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError, OverflowError):
            return None

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    # ISO8601（可能带 +08:00 / Z）。与历史实现保持一致：直接去掉时区，不做换算。
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None

class FeishuService:
    def __init__(self):
        creds = config_manager.get_credentials()
        self.app_id = creds.get("feishu", {}).get("app_id")
        self.app_secret = creds.get("feishu", {}).get("app_secret")
        self._tenant_access_token = None
        self._token_expires_at = 0
        
        if not self.app_id or not self.app_secret or "YOUR_APP" in self.app_id:
            raise ValueError("飞书 App ID 或 App Secret 未配置或无效，请检查 config/credentials.yaml 文件")
        
        # 初始化飞书SDK客户端
        self.client = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .enable_set_token(True) \
            .log_level(lark.LogLevel.INFO) \
            .build()

    async def get_tenant_access_token(self) -> str:
        """通过原生HTTP请求获取并缓存tenant_access_token"""
        # 检查token是否过期
        if self._tenant_access_token and time.time() < self._token_expires_at:
            return self._tenant_access_token

        # 使用HTTP请求获取tenant_access_token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                FEISHU_TENANT_ACCESS_TOKEN_URL,
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    self._tenant_access_token = result["tenant_access_token"]
                    self._token_expires_at = time.time() + result["expire"] - 60  # 提前60秒过期
                    return self._tenant_access_token
                else:
                    raise Exception(f"获取tenant_access_token失败: code={result.get('code')}, msg={result.get('msg')}")
            else:
                raise Exception(f"获取tenant_access_token网络请求失败: status_code={response.status_code}")

    async def delete_field(self, app_token: str, table_id: str, field_id: str) -> bool:
        """删除字段"""
        try:
            # 获取租户访问令牌
            tenant_access_token = await self.get_tenant_access_token()
            
            # 创建删除字段请求
            request: DeleteAppTableFieldRequest = DeleteAppTableFieldRequest.builder() \
                .app_token(app_token) \
                .table_id(table_id) \
                .field_id(field_id) \
                .build()

            # 设置租户访问令牌
            option = lark.RequestOption.builder().tenant_access_token(tenant_access_token).build()
            
            # 执行删除操作
            response: DeleteAppTableFieldResponse = self.client.bitable.v1.app_table_field.delete(
                request, option
            )

            if response.success():
                return True
            else:
                # 检查具体的错误代码
                error_code = response.code
                error_msg = response.msg
                
                # 特殊处理权限不足的情况
                if error_code == 99991663:  # 权限不足
                    raise Exception(f"权限不足，无法删除字段: {error_msg}")
                else:
                    # 显示更详细的错误信息
                    raise Exception(f"删除字段失败: code={error_code}, msg={error_msg}")
                    
        except Exception as e:
            raise Exception(f"删除字段时发生异常: {str(e)}")

    @lru_cache(maxsize=32)
    def _get_table_fields_sync(self, app_token: str, table_id: str, token: str) -> Dict[str, Dict[str, Any]]:
        """获取多维表格的字段列表的同步方法，用于缓存"""
        # 使用SDK获取字段列表
        request: ListAppTableFieldRequest = ListAppTableFieldRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .build()
        
        option = lark.RequestOption.builder().tenant_access_token(token).build()
        response: ListAppTableFieldResponse = self.client.bitable.v1.app_table_field.list(request, option)
        
        if response.code == 0:
            return {
                field.field_name: {
                    'id': field.field_id,
                    'type': field.type,
                    'property': field.property if field.property else {}
                }
                for field in response.data.items
            }
        else:
            raise Exception(f"获取飞书表格字段失败: {response.msg}")

    async def get_table_fields(self, app_token: str, table_id: str) -> Dict[str, Dict[str, Any]]:
        """获取多维表格的字段列表，返回字段名到字段详情的映射"""
        token = await self.get_tenant_access_token()
        # 调用同步方法并传入token以避免缓存已await的协程
        return self._get_table_fields_sync(app_token, table_id, token)

    async def create_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        field_type: str,
        field_option: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """在多维表格中创建新字段"""
        token = await self.get_tenant_access_token()
        
        # 使用HTTP请求创建字段
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        # 严格按照飞书API要求的格式构造请求体
        payload = {
            "field_name": field_name,
            "type": 1  # 1 表示文本类型
        }
        
        # 如果提供了字段选项，则添加到请求体中
        if field_option:
            payload["property"] = field_option
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30)
            try:
                response.raise_for_status()
                result = response.json()
                
                if result.get("code") == 0:
                    return {
                        "code": 0,
                        "data": {
                            "field": {
                                "field_id": result["data"]["field"]["field_id"],
                                "field_name": result["data"]["field"]["field_name"],
                                "type": result["data"]["field"]["type"]
                            }
                        }
                    }
                else:
                    # 根据错误信息提供更具体的错误提示
                    error_msg = result.get('msg', '')
                    if "field_name is required" in error_msg or "type is required" in error_msg:
                        raise Exception(f"创建字段失败，请求参数格式错误，请检查字段名和类型。字段名: {field_name}，状态码: {response.status_code}，响应: {error_msg}")
                    else:
                        raise Exception(f"创建字段失败，字段名: {field_name}，错误: {error_msg}")
            except httpx.HTTPStatusError as exc:
                error_detail = exc.response.text
                # 根据错误信息提供更具体的错误提示
                if "field_name is required" in error_detail or "type is required" in error_detail:
                    raise httpx.HTTPStatusError(
                        f"创建字段失败，请求参数格式错误，请检查字段名和类型。字段名: {field_name}，类型: {field_type}，状态码: {exc.response.status_code}，响应: {error_detail}",
                        request=exc.request,
                        response=exc.response
                    ) from exc
                else:
                    raise httpx.HTTPStatusError(
                        f"创建字段失败，字段名: {field_name}，状态码: {exc.response.status_code}，响应: {error_detail}",
                        request=exc.request,
                        response=exc.response
                    ) from exc

    async def list_records(self, app_token: str, table_id: str, page_size: int = 10, page_token: str = None) -> dict:
        """查询多维表格记录"""
        token = await self.get_tenant_access_token()
        
        # 使用HTTP请求查询记录
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        params = {
            "page_size": page_size
        }
        
        # 如果有page_token，则添加到参数中
        if page_token:
            params["page_token"] = page_token
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") == 0:
                # 返回完整的响应数据，包括分页信息
                return result.get("data", {})
            else:
                raise Exception(f"查询飞书表格记录失败: {result.get('msg')}")

    def _align_records_with_fields(self, records: list, table_fields_set: Set[str]) -> list:
        """
        对齐记录字段与表格字段
        
        Args:
            records: 要对齐的记录列表
            table_fields_set: 表格字段集合
            
        Returns:
            对齐后的记录列表
        """
        aligned_records = []
        
        for record in records:
            if "fields" not in record:
                # 如果记录没有fields字段，跳过该记录
                continue
                
            # 只保留表格中存在的字段
            aligned_fields = {
                field_name: field_value 
                for field_name, field_value in record["fields"].items() 
                if field_name in table_fields_set
            }
            
            # 添加对齐后的记录
            aligned_records.append({
                "fields": aligned_fields
            })
            
        return aligned_records

    async def ensure_table_fields(self, app_token: str, table_id: str, required_fields: Optional[Set[str]] = None, table_name: str = "") -> Tuple[bool, str]:
        """
        确保表格字段与要求一致（删除多余字段，添加缺失字段）
        
        Args:
            app_token: 多维表格应用token
            table_id: 表格ID
            required_fields: 要求的字段集合
            table_name: 表格名称（用于日志和错误信息）
            
        Returns:
            (是否成功, 消息)
        """
        try:
            if required_fields is None:
                required_fields = REQUIRED_FIELDS
                
            # 获取当前表格字段
            online_fields = await self.get_table_fields(app_token, table_id)
            online_field_names = set(online_fields.keys())
            
            # 系统自动生成的字段不应该被删除
            system_fields = {'_id', '_creator', '_createTime', '_lastModifier', '_lastModifiedTime', 'parentRecordIds'}
            online_field_names = online_field_names - system_fields
            
            # 计算需要删除和添加的字段
            fields_to_delete = online_field_names - required_fields
            fields_to_add = required_fields - online_field_names
            
            # 如果没有需要变更的字段，直接返回
            if not fields_to_delete and not fields_to_add:
                message = "字段已同步"
                if table_name:
                    message = f"表格 {table_name} 字段已同步"
                return True, message
            
            deleted_count = 0
            added_count = 0
            failed_delete_count = 0
            failed_add_count = 0
            
            # 存储详细的错误信息
            add_errors = []
            delete_errors = []
            
            # 删除多余字段
            for field_name in fields_to_delete:
                try:
                    field_info = online_fields.get(field_name)
                    if not field_info:
                        error_msg = f"字段 '{field_name}' 不存在于线上字段中"
                        delete_errors.append(error_msg)
                        failed_delete_count += 1
                        continue
                    
                    field_id = field_info['id']
                    success = await self.delete_field(app_token, table_id, field_id)
                    if success:
                        deleted_count += 1
                    else:
                        error_msg = f"删除字段 '{field_name}' 失败"
                        delete_errors.append(error_msg)
                        failed_delete_count += 1
                        
                except Exception as e:
                    error_msg = f"删除字段 '{field_name}' 异常: {str(e)}"
                    delete_errors.append(error_msg)
                    failed_delete_count += 1
                    print(f"[FeishuService] {error_msg}")
            
            # 添加缺失字段
            for field_name in fields_to_add:
                try:
                    # ⚠️ 必须查 BASE_FIELD_DEFINITIONS（键=字段名）。
                    # 历史上这里查的是 FIELD_DEFINITIONS（键=表类型：headlines/…），
                    # 永远取不到值 → 退化成 field_type='text'。当前所有定义恰好都是
                    # text 才没暴露问题，属于潜伏 bug（一旦新增 number/date 字段就失效）。
                    field_def = BASE_FIELD_DEFINITIONS.get(field_name, {})
                    field_type = field_def.get('type', 'text')
                    property_config = field_def.get('property', {})
                    
                    result = await self.create_field(app_token, table_id, field_name, field_type, property_config)
                    if result and isinstance(result, dict) and result.get("code") == 0:
                        added_count += 1
                    else:
                        error_msg = f"创建字段 '{field_name}' 失败"
                        add_errors.append(error_msg)
                        failed_add_count += 1
                        
                except Exception as e:
                    error_msg = f"创建字段 '{field_name}' 异常: {str(e)}"
                    add_errors.append(error_msg)
                    failed_add_count += 1
                    print(f"[FeishuService] {error_msg}")
            
            # 构建详细的消息
            message_parts = [f"字段同步完成"]
            if table_name:
                message_parts.append(f"表格: {table_name}")
                
            message_parts.append(f"删除 {deleted_count}/{len(fields_to_delete)} 个字段(失败{failed_delete_count}个)")
            message_parts.append(f"添加 {added_count}/{len(fields_to_add)} 个字段(失败{failed_add_count}个)")
            
            # 添加详细的错误信息
            if delete_errors:
                message_parts.append(f"删除错误: {'; '.join(delete_errors[:3])}")
            if add_errors:
                message_parts.append(f"添加错误: {'; '.join(add_errors[:3])}")
            
            return True, ", ".join(message_parts)
            
        except Exception as e:
            error_msg = f"字段同步失败: {str(e)}"
            print(f"[FeishuService] {error_msg}")
            return False, error_msg

    async def get_table_fields_uncached(self, app_token: str, table_id: str) -> Dict[str, Dict[str, Any]]:
        """获取多维表格的字段列表，不使用缓存"""
        token = await self.get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = FEISHU_BITABLE_FIELDS_LIST_URL.format(app_token=app_token, table_id=table_id)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0:
                return {
                    field['field_name']: {
                        'id': field['field_id'],
                        'type': field['type'],
                        'property': field.get('property', {})
                    }
                    for field in data.get("data", {}).get("items", [])
                }
            else:
                raise Exception(f"获取飞书表格字段失败: {data.get('msg')}")

    async def batch_add_records(self, app_token: str, table_id: str, records: list,
                                _retry_on_full: bool = True) -> dict:
        """
        批量向飞书多维表格添加记录，并预先检查和对齐字段。

        飞书单表有 20,000 条硬上限（错误码 1254103 RecordExceedLimit），写满后
        任何写入都会整体失败。本方法是项目内所有批量写入的唯一收口，因此在这里
        内置**超限自愈**：一旦命中 1254103，先做一次容量清理，再把剩余记录重试
        一遍，避免采集任务/发布流程直接报错中断。

        Args:
            _retry_on_full: 内部使用，防止自愈重试无限递归
        """
        token = await self.get_tenant_access_token()
        
        # 使用不带缓存的方法获取表格字段
        table_fields_info = await self.get_table_fields_uncached(app_token, table_id)
        table_fields_set = set(table_fields_info.keys())
        aligned_records = self._align_records_with_fields(records, table_fields_set)
        
        print(f"[DEBUG] 表格字段: {table_fields_set}")
        print(f"[DEBUG] 原始记录数: {len(records)}")
        print(f"[DEBUG] 对齐后记录数: {len(aligned_records)}")
        if records:
            print(f"[DEBUG] 第一条原始记录字段: {list(records[0].get('fields', {}).keys())}")
        if aligned_records:
            print(f"[DEBUG] 第一条对齐记录字段: {list(aligned_records[0].get('fields', {}).keys())}")
        
        if not aligned_records:
            raise ValueError("数据字段与目标表格完全不匹配，没有可写入的数据。")

        # 使用HTTP请求批量添加记录
        # 飞书单次写接口最多操作 500 条（错误码 1254104），必须分片提交；
        # 分片之间留 0.3s 间隔，规避同一张表并发写触发的 1254291 Write conflict。
        url = FEISHU_BITABLE_RECORDS_BATCH_CREATE_URL.format(app_token=app_token, table_id=table_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        total = len(aligned_records)
        created_records: List[dict] = []

        async with httpx.AsyncClient() as client:
            for start in range(0, total, BATCH_WRITE_LIMIT):
                chunk = aligned_records[start:start + BATCH_WRITE_LIMIT]
                chunk_no = start // BATCH_WRITE_LIMIT + 1
                response = await client.post(url, headers=headers, json={"records": chunk}, timeout=30)
                response.raise_for_status()
                result = response.json()

                if result.get("code") != 0:
                    code = result.get("code")

                    # ---- 超限自愈：清理 -> 重试剩余 ----
                    if code == ERR_RECORD_EXCEED_LIMIT and _retry_on_full:
                        pending = aligned_records[start:]
                        print(f"[WARN] 第 {chunk_no} 批命中 RecordExceedLimit(1254103)，"
                              f"表格已达 {TABLE_RECORD_LIMIT} 条上限。"
                              f"执行紧急清理后将重试剩余 {len(pending)} 条...")
                        try:
                            stats = await self.ensure_capacity(
                                app_token, table_id, incoming=len(pending)
                            )
                            print(f"[WARN] 紧急清理结果: {stats['message']}")
                        except Exception as exc:
                            print(f"[ERROR] 紧急清理失败，仍尝试重试写入: {exc}")

                        retry = await self.batch_add_records(
                            app_token, table_id, pending, _retry_on_full=False
                        )
                        if retry.get("code") == 0:
                            created_records.extend(
                                retry.get("data", {}).get("records", [])
                            )
                            print(f"[WARN] 自愈重试成功，本次共写入 "
                                  f"{len(created_records)} 条")
                            break

                        # 自愈仍失败：回传失败信息
                        retry["data"] = {"records": created_records}
                        retry["failed_chunk"] = chunk_no
                        retry["failed_count"] = len(pending)
                        return retry

                    # 其他错误：把已成功写入的记录一并回传，避免调用方误判为"全部失败"
                    print(f"[ERROR] 第 {chunk_no} 批写入失败: "
                          f"code={code} msg={result.get('msg')}")
                    result["data"] = {"records": created_records}
                    result["failed_chunk"] = chunk_no
                    result["failed_count"] = len(chunk)
                    return result

                created_records.extend(result.get("data", {}).get("records", []))
                if start + BATCH_WRITE_LIMIT < total:
                    await asyncio.sleep(0.3)

        return {
            "code": 0,
            "msg": "success",
            "data": {"records": created_records},
        }

    async def batch_update_records(self, app_token: str, table_id: str,
                                   records: list, align: bool = False) -> dict:
        """
        按 record_id 更新飞书记录（唯一收口，需求②回写 / 幂等更新用）。

        ⚠️ 三种同族接口的请求体形状【极易搞混，禁止照抄】：
          - batch_add_records   : {"records": [{"fields": {...}}]}                    # 无 record_id
          - batch_update_records: {"records": [{"record_id":"rec1","fields":{...}}]}  # 本方法（对象数组）
          - batch_delete        : {"records": ["rec1","rec2"]}                        # 纯字符串数组
            历史教训：曾把 batch_delete 写成对象数组 → HTTP 400（且无明确报错）
            → “计划删 19823 条、实际 0 条”，表被卡在 20,000 上限数月。

        与 batch_add_records 的差异：本方法**只更新、不新增**（因此不会产生重复行），
        每条记录必须携带 ``record_id``。

        Args:
            app_token: 多维表格应用 token
            table_id: 数据表 id
            records: 对象数组 ``[{"record_id": "recXXXX", "fields": {...}}, ...]``
            align: True 时先按线上字段过滤 fields（语义同 batch_add_records）

        Returns:
            {"code": 0, "msg": "success",
             "data": {"records": [...], "updated": <实际成功条数>}}
            全部分片失败时 code 非 0，但仍回传 data.updated 供调用方精确判断。

        分片：按 limits.BATCH_WRITE_LIMIT(500) 切片，片间 ``await asyncio.sleep(0.3)``
              规避 1254291 Write conflict。**单分片失败不中断后续分片**。
        令牌：``await self.get_tenant_access_token()``（与既有方法一致）。
        """
        # 规范化：仅保留携带 record_id 的对象
        normalized: List[Dict[str, Any]] = []
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            record_id = rec.get("record_id")
            if not record_id:
                continue
            fields = rec.get("fields") or {}
            normalized.append({"record_id": record_id, "fields": fields})

        if not normalized:
            return {"code": 0, "msg": "success", "data": {"records": [], "updated": 0}}

        token = await self.get_tenant_access_token()

        # 可选：按线上字段过滤（与 batch_add_records 的 align 语义一致）
        if align:
            table_fields_info = await self.get_table_fields_uncached(app_token, table_id)
            table_fields_set = set(table_fields_info.keys())
            normalized = [
                {
                    "record_id": rec["record_id"],
                    "fields": {
                        name: value
                        for name, value in rec["fields"].items()
                        if name in table_fields_set
                    },
                }
                for rec in normalized
            ]

        url = FEISHU_BITABLE_RECORDS_BATCH_UPDATE_URL.format(
            app_token=app_token, table_id=table_id
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        total = len(normalized)
        updated_records: List[dict] = []
        updated = 0
        ok_chunks = 0
        failed_chunks = 0
        last_code = 0
        last_msg = "success"

        async with httpx.AsyncClient() as client:
            for start in range(0, total, BATCH_WRITE_LIMIT):
                chunk = normalized[start:start + BATCH_WRITE_LIMIT]
                chunk_no = start // BATCH_WRITE_LIMIT + 1
                # 对象数组（含 record_id）—— 不要改成纯字符串数组（那是 batch_delete）
                payload = {"records": chunk}

                try:
                    response = await client.post(url, headers=headers, json=payload, timeout=30)
                    response.raise_for_status()
                    result = response.json()
                except Exception as exc:
                    failed_chunks += 1
                    last_code = -1
                    last_msg = f"第 {chunk_no} 批更新异常: {exc}"
                    print(f"[ERROR] {last_msg}")
                    if start + BATCH_WRITE_LIMIT < total:
                        await asyncio.sleep(0.3)
                    continue

                if result.get("code") == 0:
                    ok_chunks += 1
                    chunk_records = result.get("data", {}).get("records", []) or []
                    updated_records.extend(chunk_records)
                    updated += len(chunk_records) if chunk_records else len(chunk)
                else:
                    failed_chunks += 1
                    last_code = result.get("code")
                    last_msg = result.get("msg")
                    print(f"[ERROR] 第 {chunk_no} 批更新失败: "
                          f"code={last_code} msg={last_msg}")

                if start + BATCH_WRITE_LIMIT < total:
                    await asyncio.sleep(0.3)

        # 全部分片都失败：code 非 0（但仍回传 data.updated 供精确判断）
        if failed_chunks and not ok_chunks:
            return {
                "code": last_code if last_code else -1,
                "msg": last_msg,
                "data": {"records": updated_records, "updated": updated},
            }

        return {
            "code": 0,
            "msg": "success",
            "data": {"records": updated_records, "updated": updated},
        }

    # ------------------------------------------------------------------
    # 容量管理：飞书单表上限 20,000 条（错误码 1254103），超限后任何写入都会
    # 直接失败。飞书没有 count 接口，只能全表分页累加，因此下面的方法都基于
    # 一次全表扫描，尽量只扫一遍。
    # ------------------------------------------------------------------

    async def scan_records(self, app_token: str, table_id: str,
                           page_size: int = LIST_PAGE_SIZE) -> List[Tuple[str, Any]]:
        """
        全表分页扫描，返回 [(record_id, collected_at 原始值), ...]。

        一次扫描同时拿到总条数和排序所需的采集时间，避免清理时反复翻页。
        """
        rows: List[Tuple[str, Any]] = []
        page_token = None

        while True:
            data = await self.list_records(
                app_token, table_id, page_size=page_size, page_token=page_token
            )
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                fields = item.get("fields") or {}
                rows.append((item.get("record_id"), fields.get("collected_at")))

            page_token = data.get("page_token")
            if not page_token:
                break

        return rows

    async def get_record_count(self, app_token: str, table_id: str) -> int:
        """获取表格当前记录总数。"""
        rows = await self.scan_records(app_token, table_id)
        return len(rows)

    async def delete_records(self, app_token: str, table_id: str,
                             record_ids: List[str]) -> int:
        """
        分批删除记录，返回**实际删除成功**的条数。

        单次 batch_delete 最多 500 条（错误码 1254104），因此按 BATCH_WRITE_LIMIT
        分片；分片之间留 0.3s 间隔，规避 Write conflict（1254291，删除也属于写接口）。
        单个分片失败不影响后续分片，避免一条脏数据导致整轮清理中断。

        ⚠️ 请求体格式**必须是纯字符串数组**：{"records": ["rec1", "rec2"]}。
        官方文档中 records 的类型是 string[]；若传 [{"record_id": "rec1"}] 这种
        对象数组，接口会直接返回 HTTP 400 Bad Request。历史版本正是踩了这个坑，
        导致清理脚本"计划删除 19823 条、实际成功 0 条"。
        参考: https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_delete
        """
        if not record_ids:
            return 0

        token = await self.get_tenant_access_token()
        url = FEISHU_BITABLE_RECORDS_BATCH_DELETE_URL.format(
            app_token=app_token, table_id=table_id
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        total = len(record_ids)
        deleted = 0

        async with httpx.AsyncClient() as client:
            for start in range(0, total, BATCH_WRITE_LIMIT):
                chunk = record_ids[start:start + BATCH_WRITE_LIMIT]
                chunk_no = start // BATCH_WRITE_LIMIT + 1
                # string[] —— 不要改成 [{"record_id": ...}]
                payload = {"records": [str(rid) for rid in chunk]}

                try:
                    response = await client.post(
                        url, headers=headers, json=payload, timeout=30
                    )
                    response.raise_for_status()
                    result = response.json()
                except Exception as exc:
                    print(f"[ERROR] 第 {chunk_no} 批删除异常: {exc}")
                    continue

                if result.get("code") == 0:
                    deleted += len(chunk)
                else:
                    print(f"[ERROR] 第 {chunk_no} 批删除失败: "
                          f"code={result.get('code')} msg={result.get('msg')}")

                if start + BATCH_WRITE_LIMIT < total:
                    await asyncio.sleep(0.3)

        return deleted

    async def cleanup_table(
        self,
        app_token: str,
        table_id: str,
        keep_days: Optional[int] = None,
        incoming: int = 0,
        watermark: int = WATERMARK,
        protect_today: bool = True,
        dry_run: bool = False,
        guard_ratio: float = 0.5,
    ) -> Dict[str, Any]:
        """
        一次全表扫描完成两件事（顺序固定：先按时间、再按容量）：

        1. 按时间清理：删掉 collected_at 早于 keep_days 的记录（keep_days=None 跳过）
        2. 按容量清理：保证「清理后剩余 + incoming」不超过 watermark，
           从最旧的记录开始删，腾出空间。

        Args:
            keep_days: 保留最近多少天；None 表示不做时间维度的清理
            incoming: 本次准备写入的记录数（写前调用时传入，用于预留空间）
            watermark: 目标水位线，默认取模块常量 WATERMARK（见 app/services/feishu/limits.py，
                       不在此写死具体数字，避免与 limits 漂移）
            protect_today: 今日采集的数据最后才删。仅当非今日数据不足以腾出空间时，
                           才会回退删除今日最旧的记录（会在日志中明确告警）。
            dry_run: 只统计不删除，用于上线前验证清理规模
            guard_ratio: 时间规则单次删除比例的安全上限（默认 0.5 = 一半）。
                当 keep_days 规则要删掉的记录超过该比例时，判定为异常
                （典型场景：采集长期失败 → 全表数据都"过期" → 执行就等于清空历史），
                此时**跳过时间清理**，只做容量清理。确需执行请显式传 1.0。

        Returns:
            {
              "count_before", "count_after", "incoming", "watermark", "limit",
              "delete_planned", "deleted_by_age", "deleted_by_capacity",
              "deleted_total", "unparsed", "age_cleanup_skipped",
              "dry_run", "ok", "message"
            }
        """
        incoming = max(int(incoming or 0), 0)

        rows = await self.scan_records(app_token, table_id)
        count_before = len(rows)

        # 无采集时间的记录视为最旧（排在最前面），保证任何情况下都能腾出空间。
        # 但若解析失败率很高，排序就不再可信，必须显著告警，避免误删新数据。
        parsed = [(parse_record_time(raw), rid) for rid, raw in rows]
        unparsed = sum(1 for dt, _ in parsed if dt is None)
        if unparsed:
            ratio = unparsed / count_before if count_before else 0
            flag = "🚨" if ratio > 0.1 else "⚠️"
            print(f"[清理] {flag} {unparsed}/{count_before} 条记录的 collected_at 无法解析"
                  f"（{ratio:.1%}），这些记录会被当作最旧优先删除。"
                  f"请确认 collected_at 字段格式是否变更。")

        ordered = sorted(parsed, key=lambda x: x[0] or datetime.min)

        stats: Dict[str, Any] = {
            "count_before": count_before,
            "count_after": count_before,
            "incoming": incoming,
            "limit": TABLE_RECORD_LIMIT,
            "watermark": watermark,
            "deleted_by_age": 0,
            "deleted_by_capacity": 0,
            "deleted_total": 0,
            "delete_planned": 0,
            "unparsed": unparsed,
            "age_cleanup_skipped": False,
            "dry_run": dry_run,
            "ok": True,
            "message": "",
        }

        print(f"[清理] 当前容量: {describe(count_before)}")
        if count_before >= WARNING:
            print(f"[清理] ⚠️ 记录数已超过告警水位 {WARNING}，"
                  f"距硬上限 {TABLE_RECORD_LIMIT} 仅剩 "
                  f"{TABLE_RECORD_LIMIT - count_before} 条余量")

        to_delete: List[str] = []

        # ---------- 1. 按时间清理 ----------
        if keep_days is not None:
            cutoff = datetime.now() - timedelta(days=keep_days)
            stale = [rid for dt, rid in ordered if dt is not None and dt < cutoff]
            ratio = len(stale) / count_before if count_before else 0

            if ratio > guard_ratio:
                # 时间规则要删掉大半张表，几乎总是"采集长期失败、数据整体过期"造成的，
                # 直接执行等于清空历史。这里拒绝执行，退化为只做容量清理。
                print(f"[清理] 🚨 按时间规则将删除 {len(stale)}/{count_before} 条"
                      f"（{ratio:.1%}），超过安全阈值 {guard_ratio:.0%}。"
                      f"已跳过时间清理，仅执行容量清理。"
                      f"若确认要清空这些历史数据，请显式传 guard_ratio=1.0（--force）。")
                stats["age_cleanup_skipped"] = True
                stale = []

            to_delete.extend(stale)
            stats["deleted_by_age"] = len(stale)
            print(f"[清理] 保留最近 {keep_days} 天（截止 {cutoff:%Y-%m-%d %H:%M:%S}），"
                  f"命中过期记录 {len(stale)} 条")

        # ---------- 2. 按容量清理 ----------
        remaining_after_age = count_before - len(to_delete)
        projected = remaining_after_age + incoming
        # 清理目标：即便算上本次要写入的记录，也不超过水位线
        keep_target = max(watermark - incoming, 0)
        excess = remaining_after_age - keep_target

        if excess > 0:
            already = set(to_delete)
            pool = [(dt, rid) for dt, rid in ordered if rid not in already]

            if protect_today:
                today = datetime.now().date()
                fresh = [rid for dt, rid in pool if dt is not None and dt.date() == today]
                fresh_set = set(fresh)
                # 非今日数据（旧→新）优先删除，今日数据（旧→新）兜底
                delete_order = [rid for _, rid in pool if rid not in fresh_set] + fresh
            else:
                fresh_set = set()
                delete_order = [rid for _, rid in pool]

            extra = delete_order[:excess]
            to_delete.extend(extra)
            stats["deleted_by_capacity"] = len(extra)

            spill_today = sum(1 for rid in extra if rid in fresh_set)
            if spill_today > 0:
                print(f"[清理] ⚠️ 非今日数据不足以腾出空间，已回退删除 "
                      f"{spill_today} 条今日记录")

            print(f"[清理] 预计写入 {incoming} 条后共 {projected} 条，超出水位 {watermark}，"
                  f"追加清理最旧 {len(extra)} 条")
        else:
            print(f"[清理] 容量充足（预计 {projected} ≤ 水位 {watermark}），跳过容量清理")

        # ---------- 3. 执行删除 ----------
        stats["delete_planned"] = len(to_delete)
        deleted = 0

        if to_delete and dry_run:
            print(f"[清理] DRY-RUN：计划删除 {len(to_delete)} 条，本次未实际执行")
            stats["count_after"] = count_before - len(to_delete)
        elif to_delete:
            print(f"[清理] 开始删除 {len(to_delete)} 条记录"
                  f"（每批 {BATCH_WRITE_LIMIT} 条）...")
            deleted = await self.delete_records(app_token, table_id, to_delete)
            stats["deleted_total"] = deleted
            stats["count_after"] = count_before - deleted
        else:
            print("[清理] 无需删除任何记录")

        # ---------- 4. 结果判定 ----------
        if stats["count_after"] + incoming > TABLE_RECORD_LIMIT:
            stats["ok"] = False
            stats["message"] = (
                f"🚨 清理后仍会超限: {stats['count_after']} + {incoming} > "
                f"{TABLE_RECORD_LIMIT}，需人工介入"
            )
        elif dry_run and to_delete:
            stats["message"] = (
                f"DRY-RUN 预演: {count_before} → {stats['count_after']} 条"
                f"（按时间 {stats['deleted_by_age']} 条 + "
                f"按容量 {stats['deleted_by_capacity']} 条），未实际删除"
            )
        else:
            stats["message"] = (
                f"清理完成: {count_before} → {stats['count_after']} 条"
                f"（按时间 {stats['deleted_by_age']} 条 + "
                f"按容量 {stats['deleted_by_capacity']} 条）"
            )

        print(f"[清理] {describe(stats['count_after'])} | {stats['message']}")
        return stats

    async def ensure_capacity(self, app_token: str, table_id: str,
                              incoming: int = 0,
                              watermark: int = WATERMARK) -> Dict[str, Any]:
        """
        写前容量保障：确保写入 incoming 条记录后表格不超过水位线。

        与 cleanup_table 的区别是只做容量维度、不做时间维度清理，
        专供采集写入前调用，避免采集任务因 RecordExceedLimit 整体失败。
        """
        return await self.cleanup_table(
            app_token, table_id, keep_days=None, incoming=incoming, watermark=watermark
        )