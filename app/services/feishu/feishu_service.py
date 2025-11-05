import time
import httpx
from functools import lru_cache
from typing import Dict, Any, Optional, Set, Tuple
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from ...core.config import config_manager
from .field_rules import FIELD_DEFINITIONS, REQUIRED_FIELDS

# API URL 常量
FEISHU_TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_BITABLE_RECORDS_BATCH_CREATE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
FEISHU_BITABLE_FIELDS_LIST_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
FEISHU_BITABLE_FIELD_DELETE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}"

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
                    field_def = FIELD_DEFINITIONS.get(field_name, {})
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

    async def batch_add_records(self, app_token: str, table_id: str, records: list) -> dict:
        """批量向飞书多维表格添加记录，并预先检查和对齐字段"""
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
        url = FEISHU_BITABLE_RECORDS_BATCH_CREATE_URL.format(app_token=app_token, table_id=table_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json={"records": aligned_records}, timeout=30)
            response.raise_for_status()
            return response.json()