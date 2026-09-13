# -*- coding: utf-8 -*-
"""ai_insights 深度内容服务（需求③）

职责：从 headlines 读记录 → 调 LLM 生成深度内容 → 纯函数 ``build_insight_fields``
映射为 ai_insights 的 14 字段 → 经 ``feishu_service.batch_add_records``（唯一收口）写入。

设计要点：
  - 字段映射（``build_insight_fields``）与 I/O 分离，为**纯函数**，便于离线测试；
  - LLM 客户端通过工厂（``build_llm_client``）构建，可注入替换；无 Key 自动降级 Mock；
  - **写入前强制 schema 校验**：ai_insights 线上字段若缺少规划字段，则逐条返回
    ``TABLE_SCHEMA_UNCONFIRMED`` 且**不写入**，避免字段不匹配被静默丢弃。

兼容性：Python 3.9（一律 ``typing.*``；Pydantic v2 由端点层 ``model_dump()`` 处理）。
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.feishu.feishu_service import FeishuService
from app.services.feishu.field_rules import TABLE_PLANS
from app.services.feishu.limits import LIST_PAGE_SIZE
from app.core.config import config_manager
from app.utils.id_generator import generate_content_id
from .feature_analysis.llm_clients import build_llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 字段规划（必须与 TABLE_PLANS['ai_insights'] 一致）
# ---------------------------------------------------------------------------
AI_INSIGHT_FIELDS: List[str] = [
    'id', 'title', 'url', 'content', 'author', 'category', 'summary',
    'tags', 'sentiment', 'seo_title', 'seo_description', 'seo_keywords',
    'published_at', 'status',
]

# 可由 LLM 生成的字段子集
GENERATABLE: Set[str] = {
    'summary', 'tags', 'sentiment', 'seo_title', 'seo_description', 'seo_keywords', 'category',
}


def _assert_field_consistency() -> None:
    """import 期守卫：AI_INSIGHT_FIELDS 必须与 TABLE_PLANS['ai_insights'] 完全一致。"""
    plan = set(TABLE_PLANS.get('ai_insights', {}).get('fields', set()))
    mine = set(AI_INSIGHT_FIELDS)
    if plan != mine:
        raise ValueError(
            "AI_INSIGHT_FIELDS 与 TABLE_PLANS['ai_insights'] 不一致："
            "缺=%s 多=%s" % (sorted(plan - mine), sorted(mine - plan))
        )


_assert_field_consistency()


# ---------------------------------------------------------------------------
# 错误码枚举（与架构 §3.7 一致）
# ---------------------------------------------------------------------------
LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"
LLM_TIMEOUT = "LLM_TIMEOUT"
LLM_RESPONSE_PARSE_ERROR = "LLM_RESPONSE_PARSE_ERROR"
HEADLINE_NOT_FOUND = "HEADLINE_NOT_FOUND"
TABLE_SCHEMA_UNCONFIRMED = "TABLE_SCHEMA_UNCONFIRMED"
FEISHU_WRITE_FAILED = "FEISHU_WRITE_FAILED"
INTERNAL_ERROR = "INTERNAL_ERROR"

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# 纯函数：字段映射
# ---------------------------------------------------------------------------
def _as_text(value: Any) -> str:
    """把任意值规范成文本：list → 逗号连接；dict → JSON；其余 → strip 字符串。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_as_text(v) for v in value]
        return ", ".join(p for p in parts if p.strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def build_insight_fields(headline: Dict[str, Any],
                         llm_out: Dict[str, Any],
                         generate_set: Set[str],
                         insight_id: str) -> Dict[str, Any]:
    """把 headlines 记录 + LLM 输出映射为 **恰好 14 个键** 的 ai_insights.fields。

    Args:
        headline: headlines.fields（含 title/url/content/author/category/published_at）
        llm_out: LLM 解析结果 dict（可能缺字段）
        generate_set: 本次需要 LLM 生成的字段集合
        insight_id: 新生成的 ai_insights 记录 id

    Returns:
        14 个键的 dict（键集 == TABLE_PLANS['ai_insights']）
    """
    headline = headline or {}
    llm_out = llm_out or {}
    generate_set = set(generate_set or [])

    title = _as_text(headline.get('title'))
    url = _as_text(headline.get('url'))
    author = _as_text(headline.get('author'))
    published_at = _as_text(headline.get('published_at'))

    summary = _as_text(llm_out.get('summary'))

    # content：优先用 headline.content；**仅在 summary 非空时**退化为 title + '\n' + summary。
    # 若 summary 也为空则明确置空——否则 content 会恰好等于 title（非空字符串），
    # 下游将无法区分“有正文”与“没正文”，等于用兜底掩盖了数据缺失。
    content = _as_text(headline.get('content'))
    if not content and summary:
        content = (title + '\n' + summary).strip()

    # category：LLM 生成优先（仅当在 generate_set 且非空），否则回退 headline.category
    if 'category' in generate_set and _as_text(llm_out.get('category')):
        category = _as_text(llm_out.get('category'))
    else:
        category = _as_text(headline.get('category'))

    fields: Dict[str, Any] = {
        'id': _as_text(insight_id),
        'title': title,
        'url': url,
        'content': content,
        'author': author,
        'category': category,
        'summary': summary,
        'tags': _as_text(llm_out.get('tags')),
        'sentiment': _as_text(llm_out.get('sentiment')),
        'seo_title': _as_text(llm_out.get('seo_title')),
        'seo_description': _as_text(llm_out.get('seo_description')),
        'seo_keywords': _as_text(llm_out.get('seo_keywords')),
        'published_at': published_at,
        'status': 'generated',
    }
    return fields


def _build_insight_prompt(headline: Dict[str, Any], generate_set: Set[str]) -> str:
    """构造 ai_insights 生成提示（含标识 token，便于 Mock 返回结构化 JSON）。"""
    title = _as_text(headline.get('title'))
    url = _as_text(headline.get('url'))
    content = _as_text(headline.get('content'))[:2000]
    wanted = ", ".join(sorted(generate_set))
    return (
        "AI_INSIGHTS_JSON\n"
        "请根据以下新闻内容生成深度内容，并仅以 JSON 返回。\n"
        "标题: %s\n"
        "链接: %s\n"
        "正文: %s\n"
        "需要生成的字段: %s\n"
        '示例: {"summary":"...","tags":["a","b"],"sentiment":"中性",'
        '"seo_title":"...","seo_description":"...","seo_keywords":"...","category":"..."}'
    ) % (title, url, content, wanted)


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """从 LLM 文本中解析 JSON；失败抛 ValueError。"""
    if not text or not str(text).strip():
        raise ValueError("LLM 返回为空")
    text = str(text).strip()

    # 去掉 ```json ... ``` 代码围栏
    fence = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            raise ValueError("LLM 响应解析失败: 未找到 JSON")
        try:
            data = json.loads(match.group())
        except Exception:
            raise ValueError("LLM 响应解析失败: JSON 非法")

    if not isinstance(data, dict):
        raise ValueError("LLM 响应解析失败: 顶层不是对象")
    return data


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------
class InsightsService:
    """ai_insights 生成与写入服务。"""

    def __init__(self, feishu_service: Optional[FeishuService] = None, llm_factory=None):
        # 依赖注入：测试可传桩；默认自行构造（生产 credentials.yaml 已配置）
        self.feishu_service = feishu_service if feishu_service is not None else FeishuService()
        self._llm_factory = llm_factory or build_llm_client

    # -- 配置解析 ---------------------------------------------------------
    def _llm_settings(self, override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = (config_manager.get_config() or {}).get('feature_analysis', {}).get('llm', {}) or {}
        creds = (config_manager.get_credentials() or {}).get('llm', {}) or {}
        override = override or {}

        provider = override.get('provider') or cfg.get('provider') or creds.get('provider') or 'openai'
        model_name = override.get('model_name') or cfg.get('model_name') or creds.get('model_name') or 'gpt-4-turbo'
        base_url = cfg.get('base_url') or creds.get('base_url')
        api_key = creds.get('api_key')
        timeout = cfg.get('timeout', 30)
        temperature = override.get('temperature')
        if temperature is None:
            temperature = cfg.get('temperature', 0.3)
        max_tokens = override.get('max_tokens')
        if max_tokens is None:
            max_tokens = cfg.get('max_tokens', 2000)

        return {
            'provider': provider,
            'model_name': model_name,
            'base_url': base_url,
            'api_key': api_key,
            'timeout': timeout,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }

    def _build_client(self, override: Optional[Dict[str, Any]] = None) -> Tuple[Any, str, Dict[str, Any]]:
        settings = self._llm_settings(override)
        client, mode = self._llm_factory(
            settings['provider'], settings['model_name'], settings['base_url'],
            settings['api_key'], settings['timeout'],
        )
        return client, mode, settings

    def _headlines_table(self) -> Tuple[Optional[str], Optional[str]]:
        cfg = (config_manager.get_credentials() or {}).get('feishu', {}).get('tables', {}).get('headlines', {})
        return cfg.get('app_token'), cfg.get('table_id')

    def _insights_table(self) -> Tuple[Optional[str], Optional[str]]:
        cfg = (config_manager.get_credentials() or {}).get('feishu', {}).get('tables', {}).get('ai_insights', {})
        return cfg.get('app_token'), cfg.get('table_id')

    # -- 数据加载 ---------------------------------------------------------
    async def _load_headlines(self) -> List[Dict[str, Any]]:
        app_token, table_id = self._headlines_table()
        if not app_token or not table_id:
            return []
        items: List[Dict[str, Any]] = []
        page_token = None
        pages = 0
        # 上限 40 页（20,000/500），避免异常情况下无限翻页
        while pages < 40:
            data = await self.feishu_service.list_records(
                app_token, table_id, page_size=LIST_PAGE_SIZE, page_token=page_token
            )
            page_items = (data or {}).get('items', []) or []
            items.extend(page_items)
            page_token = (data or {}).get('page_token')
            pages += 1
            if not page_token:
                break
        return items

    @staticmethod
    def _index_headlines(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """建立三键索引：record_id / fields['id']（业务 id）/ fields['url'] → {record_id, fields}。"""
        index: Dict[str, Dict[str, Any]] = {}
        for item in items or []:
            record_id = item.get('record_id')
            fields = item.get('fields') or {}
            entry = {'record_id': record_id, 'fields': fields}
            if record_id:
                index[record_id] = entry
            business_id = fields.get('id')
            if business_id:
                index[str(business_id)] = entry
            url = fields.get('url')
            if url:
                index[str(url)] = entry
        return index

    async def _ensure_schema_confirmed(self, app_token: Optional[str],
                                       table_id: Optional[str]) -> Tuple[bool, List[str]]:
        required = set(TABLE_PLANS['ai_insights']['fields'])
        if not app_token or not table_id:
            return False, sorted(required)
        try:
            online = await self.feishu_service.get_table_fields_uncached(app_token, table_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 ai_insights 线上字段失败: %s", exc)
            return False, sorted(required)
        online_names = set((online or {}).keys())
        missing = sorted(required - online_names)
        return (len(missing) == 0), missing

    # -- 预检 -------------------------------------------------------------
    async def preflight(self) -> Dict[str, Any]:
        settings = self._llm_settings(None)
        _, mode = self._llm_factory(
            settings['provider'], settings['model_name'], settings['base_url'],
            settings['api_key'], settings['timeout'],
        )
        app_token, table_id = self._insights_table()
        schema_confirmed, missing = await self._ensure_schema_confirmed(app_token, table_id)
        return {
            'llm': {
                'provider_configured': bool(settings['provider']),
                'has_api_key': bool(settings['api_key']),
                'client': mode,
            },
            'table': {
                'name': 'ai_insights',
                'schema_confirmed': schema_confirmed,
                'missing_fields': missing,
            },
        }

    # -- 生成 -------------------------------------------------------------
    async def generate(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """生成并（可选）写入 ai_insights。返回对齐 PRD §4.2 的 dict。"""
        req = req or {}
        record_ids = list(req.get('record_ids') or [])
        urls = list(req.get('urls') or [])
        generate_list = req.get('generate')
        generate_set = set(generate_list) if generate_list else set(GENERATABLE)
        override = req.get('llm') or {}
        dry_run = bool(req.get('dry_run', False))
        write = bool(req.get('write', True))

        items = await self._load_headlines()
        index = self._index_headlines(items)

        selected: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        seen = set()

        def _collect(key: Any) -> None:
            entry = index.get(str(key))
            if not entry:
                results.append({
                    'record_id': None,
                    'url': None,
                    'source_key': key,
                    'status': STATUS_FAILED,
                    'error_code': HEADLINE_NOT_FOUND,
                    'error_message': 'headline 不存在: %s' % key,
                })
                return
            rid = entry['record_id']
            if rid in seen:
                return
            seen.add(rid)
            selected.append(entry)

        # A1 裁决：record_ids 同时接受飞书 record_id 与业务 fields['id']；urls 亦接受
        for key in record_ids:
            _collect(key)
        for key in urls:
            _collect(key)

        # 写入前 schema 校验（仅当需要真正写入时）
        ins_app, ins_table = self._insights_table()
        schema_confirmed = True
        missing_fields: List[str] = []
        need_write = write and not dry_run
        if need_write:
            schema_confirmed, missing_fields = await self._ensure_schema_confirmed(ins_app, ins_table)

        client, mode, settings = self._build_client(override)

        generated = 0
        to_write: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        for entry in selected:
            fields = entry['fields']
            record_id = entry['record_id']
            result: Dict[str, Any] = {
                'record_id': record_id,
                'url': fields.get('url'),
                'status': STATUS_FAILED,
            }
            try:
                prompt = _build_insight_prompt(fields, generate_set)
                raw = await client.generate(prompt, settings['temperature'], settings['max_tokens'])
                llm_out = _parse_llm_json(raw)
            except (asyncio.TimeoutError, TimeoutError):
                result['error_code'] = LLM_TIMEOUT
                result['error_message'] = 'LLM 调用超时'
                results.append(result)
                continue
            except ValueError as exc:
                result['error_code'] = LLM_RESPONSE_PARSE_ERROR
                result['error_message'] = str(exc)
                results.append(result)
                continue
            except Exception as exc:  # noqa: BLE001
                result['error_code'] = INTERNAL_ERROR
                result['error_message'] = str(exc)
                results.append(result)
                continue

            insight_id = generate_content_id()
            mapped = build_insight_fields(fields, llm_out, generate_set, insight_id)
            result['insight_id'] = insight_id
            result['fields'] = mapped
            generated += 1

            if need_write and not schema_confirmed:
                result['status'] = STATUS_FAILED
                result['error_code'] = TABLE_SCHEMA_UNCONFIRMED
                result['error_message'] = 'ai_insights 线上缺字段: %s' % missing_fields
            else:
                result['status'] = STATUS_SUCCESS
                if need_write:
                    to_write.append((mapped, result))
            results.append(result)

        written = 0
        if to_write and need_write and schema_confirmed:
            records = [{'fields': mapped} for mapped, _ in to_write]
            try:
                resp = await self.feishu_service.batch_add_records(ins_app, ins_table, records)
                if resp and resp.get('code') == 0:
                    written = len(resp.get('data', {}).get('records', records))
                    logger.info("ai_insights 写入成功: %d 条", written)
                else:
                    err = (resp or {}).get('msg', '写入失败')
                    for _, result in to_write:
                        result['status'] = STATUS_FAILED
                        result['error_code'] = FEISHU_WRITE_FAILED
                        result['error_message'] = err
            except Exception as exc:  # noqa: BLE001
                for _, result in to_write:
                    result['status'] = STATUS_FAILED
                    result['error_code'] = FEISHU_WRITE_FAILED
                    result['error_message'] = str(exc)

        failed = sum(1 for r in results if r.get('status') == STATUS_FAILED)
        return {
            'total': len(results),
            'generated': generated,
            'written': written,
            'failed': failed,
            'llm_provider': settings['provider'],
            'llm_client': mode,
            'results': results,
        }


__all__ = [
    "AI_INSIGHT_FIELDS",
    "GENERATABLE",
    "build_insight_fields",
    "InsightsService",
    "LLM_NOT_CONFIGURED",
    "LLM_TIMEOUT",
    "LLM_RESPONSE_PARSE_ERROR",
    "HEADLINE_NOT_FOUND",
    "TABLE_SCHEMA_UNCONFIRMED",
    "FEISHU_WRITE_FAILED",
    "INTERNAL_ERROR",
]
