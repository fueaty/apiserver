# -*- coding: utf-8 -*-
"""正文采集 API 端点（需求②）

- ``POST /collection/content/fetch``    ：按 urls 或 headlines record_ids 抓取正文（P0）
- ``POST /collection/content/backfill`` ：扫描 content 为空的记录限量回填（P1）

约定：
  - urls 与 record_ids 均空 → 400；record_ids 全部查不到 → 404；部分成功 → 200；
    单条抓取失败**不得** 500（仅服务端异常才 500）。
  - record_ids 同时接受飞书 record_id 与业务 fields['id']（A1 裁决）。
  - 依赖（FeishuService / robots / fetcher）在使用处延迟构造，便于端点测试注入。
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.endpoints.auth import verify_token
from app.services.collection.content_fetcher import (
    ContentFetcher,
    FetchItem,
    infer_site_code,
    should_write_back,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)
from app.services.feishu.limits import LIST_PAGE_SIZE
from app.core.config import config_manager
from app.utils.logger import logger


router = APIRouter()


# ---------------------------------------------------------------------------
# 请求模型（Pydantic v2）
# ---------------------------------------------------------------------------
class ContentFetchRequest(BaseModel):
    urls: Optional[List[str]] = None          # 与 record_ids 至少一个；同时提供以 urls 为准
    record_ids: Optional[List[str]] = None
    site_code: Optional[str] = None           # 缺省按 URL 推断
    write_back: bool = False                  # True → 回写 headlines.content
    overwrite: bool = False                   # True → 覆盖已有 content
    concurrency: Optional[int] = None         # 超出服务端硬上限(8)被截断
    timeout: Optional[int] = None             # 单请求秒；缺省 10，上限 30


class ContentBackfillRequest(BaseModel):
    site_code: Optional[str] = None
    limit: int = 50
    dry_run: bool = True
    overwrite: bool = False
    concurrency: Optional[int] = None
    timeout: Optional[int] = None


# ---------------------------------------------------------------------------
# 依赖构造（延迟 import / 可被测试替换）
# ---------------------------------------------------------------------------
def _get_feishu_service():
    from app.services.feishu.feishu_service import FeishuService
    return FeishuService()


def _get_fetcher(sites_config: Optional[Dict[str, Any]]):
    from app.services.collection.robots_checker import robots_checker
    return ContentFetcher(robots=robots_checker, sites_config=sites_config)


def _headlines_table() -> Tuple[Optional[str], Optional[str]]:
    cfg = (config_manager.get_credentials() or {}).get("feishu", {}).get("tables", {}).get("headlines", {})
    return cfg.get("app_token"), cfg.get("table_id")


async def _load_headline_index(feishu) -> Dict[str, Dict[str, Any]]:
    """拉取 headlines 并建立 record_id / fields['id'] / url 三键索引。"""
    app_token, table_id = _headlines_table()
    if not app_token or not table_id:
        return {}
    index: Dict[str, Dict[str, Any]] = {}
    page_token = None
    pages = 0
    while pages < 40:  # 上限 40 页（20,000/500）
        data = await feishu.list_records(
            app_token, table_id, page_size=LIST_PAGE_SIZE, page_token=page_token
        )
        for item in (data or {}).get("items", []) or []:
            fields = item.get("fields") or {}
            entry = {"record_id": item.get("record_id"), "fields": fields}
            rid = item.get("record_id")
            if rid:
                index[str(rid)] = entry
            if fields.get("id"):
                index[str(fields["id"])] = entry
            if fields.get("url"):
                index[str(fields["url"])] = entry
        page_token = (data or {}).get("page_token")
        pages += 1
        if not page_token:
            break
    return index


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": 400, "message": message, "data": None})


# ---------------------------------------------------------------------------
# 端点：抓取
# ---------------------------------------------------------------------------
@router.post("/content/fetch", summary="按 URL 或 headlines 记录抓取正文")
async def fetch_content(request: ContentFetchRequest, payload: dict = Depends(verify_token)):
    urls = list(request.urls or [])
    record_ids = list(request.record_ids or [])

    if not urls and not record_ids:
        raise _bad_request("urls 与 record_ids 至少提供一个")
    if request.concurrency is not None and request.concurrency < 1:
        raise _bad_request("concurrency 必须 >= 1")
    if request.timeout is not None and request.timeout < 1:
        raise _bad_request("timeout 必须 >= 1")

    sites_config = config_manager.get_sites_config() or {}

    items: List[FetchItem] = []
    existing: Dict[str, Optional[str]] = {}
    feishu = None

    if urls:
        # 同时提供时以 urls 为准
        for url in urls:
            items.append(FetchItem(url=url, site_code=request.site_code))
    else:
        feishu = _get_feishu_service()
        index = await _load_headline_index(feishu)
        found = 0
        for key in record_ids:
            entry = index.get(str(key))
            if not entry:
                continue
            found += 1
            fields = entry.get("fields") or {}
            url = fields.get("url")
            rid = entry.get("record_id")
            existing[rid] = fields.get("content")
            items.append(FetchItem(
                url=url,
                record_id=rid,
                site_code=request.site_code or infer_site_code(url, sites_config),
            ))
        if found == 0:
            raise HTTPException(
                status_code=404,
                detail={"code": 404, "message": "record_ids 在 headlines 中均查不到", "data": None},
            )

    fetcher = _get_fetcher(sites_config)
    outcomes = await fetcher.fetch_many(
        items, concurrency=request.concurrency, timeout=request.timeout
    )

    # 回写（仅当显式 write_back；且仅对携带 record_id 的成功条目）
    written = 0
    if request.write_back:
        if feishu is None:
            feishu = _get_feishu_service()
        to_update = []
        for outcome in outcomes:
            if outcome.status != STATUS_SUCCESS or not outcome.record_id:
                continue
            if should_write_back(existing.get(outcome.record_id), outcome.content, request.overwrite):
                to_update.append({"record_id": outcome.record_id, "fields": {"content": outcome.content}})
                outcome.written = True
        if to_update:
            app_token, table_id = _headlines_table()
            if app_token and table_id:
                try:
                    await feishu.batch_update_records(app_token, table_id, to_update)
                    written = len(to_update)
                except Exception as exc:  # noqa: BLE001
                    logger.error("正文回写失败: %s", exc)

    results = [o.to_dict() for o in outcomes]
    return {
        "code": 200,
        "message": "success",
        "data": {
            "total": len(outcomes),
            "succeeded": sum(1 for o in outcomes if o.status == STATUS_SUCCESS),
            "failed": sum(1 for o in outcomes if o.status == STATUS_FAILED),
            "skipped": sum(1 for o in outcomes if o.status == STATUS_SKIPPED),
            "written": written,
            "results": results,
        },
    }


# ---------------------------------------------------------------------------
# 端点：回填
# ---------------------------------------------------------------------------
@router.post("/content/backfill", summary="扫描 content 为空的 headlines 记录并限量回填")
async def backfill_content(request: ContentBackfillRequest, payload: dict = Depends(verify_token)):
    try:
        limit = int(request.limit)
    except (TypeError, ValueError):
        raise _bad_request("limit 非法")
    limit = max(1, min(limit, LIST_PAGE_SIZE))

    feishu = _get_feishu_service()
    app_token, table_id = _headlines_table()
    if not app_token or not table_id:
        raise HTTPException(
            status_code=500,
            detail={"code": 500, "message": "headlines 飞书配置缺失", "data": None},
        )

    # 扫描 content 为空的记录（可选 site_code 过滤）
    planned: List[Dict[str, Any]] = []
    page_token = None
    pages = 0
    while pages < 40 and len(planned) < limit:
        data = await feishu.list_records(
            app_token, table_id, page_size=LIST_PAGE_SIZE, page_token=page_token
        )
        for item in (data or {}).get("items", []) or []:
            fields = item.get("fields") or {}
            if request.site_code and fields.get("site_code") != request.site_code:
                continue
            if str(fields.get("content") or "").strip():
                continue
            url = fields.get("url")
            if not url:
                continue
            planned.append({
                "record_id": item.get("record_id"),
                "url": url,
                "site_code": fields.get("site_code"),
            })
            if len(planned) >= limit:
                break
        page_token = (data or {}).get("page_token")
        pages += 1
        if not page_token:
            break

    if request.dry_run:
        return {
            "code": 200,
            "message": "success",
            "data": {
                "planned": len(planned),
                "fetched": 0,
                "written": 0,
                "skipped": 0,
                "results": [dict(p, status="planned") for p in planned],
            },
        }

    sites_config = config_manager.get_sites_config() or {}
    items = [
        FetchItem(
            url=p["url"],
            record_id=p["record_id"],
            site_code=p["site_code"] or infer_site_code(p["url"], sites_config),
        )
        for p in planned
    ]
    fetcher = _get_fetcher(sites_config)
    outcomes = await fetcher.fetch_many(
        items, concurrency=request.concurrency, timeout=request.timeout
    )

    to_update = []
    for outcome in outcomes:
        if outcome.status != STATUS_SUCCESS or not outcome.record_id:
            continue
        # 回填场景：原 content 必为空，默认即写；overwrite 仅作显式确认
        if should_write_back("", outcome.content, request.overwrite):
            to_update.append({"record_id": outcome.record_id, "fields": {"content": outcome.content}})
            outcome.written = True

    written = 0
    if to_update:
        try:
            await feishu.batch_update_records(app_token, table_id, to_update)
            written = len(to_update)
        except Exception as exc:  # noqa: BLE001
            logger.error("正文回填写入失败: %s", exc)

    return {
        "code": 200,
        "message": "success",
        "data": {
            "planned": len(planned),
            "fetched": len(outcomes),
            "written": written,
            "skipped": sum(1 for o in outcomes if o.status == STATUS_SKIPPED),
            "results": [o.to_dict() for o in outcomes],
        },
    }
