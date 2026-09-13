# -*- coding: utf-8 -*-
"""
正文抓取编排层（需求②）

I/O 与纯逻辑严格分离（离线可测的硬要求）：
  - 纯逻辑（HTML→正文、选择器匹配、URL→站点推断、覆盖策略）在
    ``content_extractor.py`` 与下方的模块级纯函数中；
  - 本模块只做编排：robots 检查 → HTTP 抓取 → 抽取 → 覆盖判定。所有外部
    依赖（``extractor`` / ``robots`` / ``http_getter`` / ``sites_config``）**全部
    注入**，``__init__`` 里**绝不**自行 ``new FeishuService`` / ``RobotsTxtChecker``，
    以便用桩在离线、不联网、不装依赖的情况下测试。

回写策略：本模块**不做**飞书写回（架构 §3.4：回写由端点/服务层注入
``feishu_service.batch_update_records`` 完成），只提供纯函数
``should_write_back`` 供调用方判定覆盖。
"""

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

from .content_extractor import ContentExtractor, ExtractResult


# ---------------------------------------------------------------------------
# 错误码枚举（正文抓取）—— 与架构 §3.7 一致
# ---------------------------------------------------------------------------
FETCH_TIMEOUT = "FETCH_TIMEOUT"
FETCH_HTTP_ERROR = "FETCH_HTTP_ERROR"
FETCH_CONNECT_ERROR = "FETCH_CONNECT_ERROR"
ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
EXTRACT_EMPTY = "EXTRACT_EMPTY"
INVALID_URL = "INVALID_URL"
INTERNAL_ERROR = "INTERNAL_ERROR"

# 逐条状态枚举
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# 默认参数与硬上限
DEFAULT_USER_AGENT = "IntelligentAgentAPI/1.0"
DEFAULT_MAX_CONCURRENCY = 4
HARD_MAX_CONCURRENCY = 8          # 服务端硬上限，超出被截断
DEFAULT_TIMEOUT = 10
HARD_MAX_TIMEOUT = 30             # 单请求超时上限（秒）


@dataclass
class FetchItem:
    """待抓取条目。"""

    url: str
    record_id: Optional[str] = None
    site_code: Optional[str] = None


@dataclass
class FetchOutcome:
    """单条抓取结果（逐条状态，对齐 PRD §4.1）。"""

    url: str
    record_id: Optional[str] = None
    status: str = STATUS_FAILED
    title: Optional[str] = None
    content: Optional[str] = None
    content_length: int = 0
    extractor: Optional[str] = None
    elapsed_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    written: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的 dict。"""
        return {
            "url": self.url,
            "record_id": self.record_id,
            "status": self.status,
            "title": self.title,
            "content": self.content,
            "content_length": self.content_length,
            "extractor": self.extractor,
            "elapsed_ms": self.elapsed_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "written": self.written,
        }


# ---------------------------------------------------------------------------
# 模块级纯函数（独立可测）
# ---------------------------------------------------------------------------
def should_write_back(existing: Optional[str], new: Optional[str], overwrite: bool) -> bool:
    """判定是否应把抓取到的新正文回写。

    规则（架构 §3.4 / PRD §5.2）：
      - ``new`` 为空/空白 → False（没有可写内容）；
      - ``overwrite`` 为 True → True（显式允许覆盖已有值）；
      - 否则仅当 ``existing`` 为空/空白 → True（默认只补空，避免摘要被冲掉）。
    """
    if new is None or not str(new).strip():
        return False
    if overwrite:
        return True
    if existing is None or not str(existing).strip():
        return True
    return False


def _site_entries(sites_config: Any) -> Dict[str, Any]:
    """从站点配置中取出 {site_code: cfg} 映射（兼容带/不带 'sites' 根键）。"""
    if not isinstance(sites_config, dict):
        return {}
    inner = sites_config.get("sites")
    if isinstance(inner, dict):
        return inner
    return sites_config


def _host_of(url: Any) -> str:
    """取 URL 的 host（去掉端口、小写）；无法解析返回 ''。"""
    if not url:
        return ""
    try:
        netloc = urlparse(str(url)).netloc.lower()
    except Exception:
        return ""
    return netloc.split(":")[0]


def infer_site_code(url: str, sites_config: Dict[str, Any]) -> Optional[str]:
    """按域名/URL 推断站点码；未知返回 None。

    优先级：
      1. 站点配置中的显式 ``domains`` 列表（子串匹配 host）；
      2. 站点 ``request.url`` / ``url`` 的 host 与目标 host 互相包含；
      3. 站点码本身出现在 host 中（如 ``zhihu`` → www.zhihu.com）。
    """
    host = _host_of(url)
    if not host:
        return None

    entries = _site_entries(sites_config)
    for code, cfg in entries.items():
        if not isinstance(cfg, dict):
            continue

        # 1) 显式 domains
        domains = cfg.get("domains")
        if isinstance(domains, list):
            for domain in domains:
                d = str(domain).lower().strip()
                if d and d in host:
                    return code

        # 2) 配置里的示例 URL host
        candidates: List[Any] = []
        request_cfg = cfg.get("request")
        if isinstance(request_cfg, dict) and request_cfg.get("url"):
            candidates.append(request_cfg["url"])
        if cfg.get("url"):
            candidates.append(cfg["url"])
        for candidate in candidates:
            c_host = _host_of(candidate)
            if c_host and (c_host == host or c_host in host or host in c_host):
                return code

        # 3) 站点码即域名关键字
        if code and str(code).lower() in host:
            return code

    return None


class ContentFetcher:
    """正文抓取编排器（依赖全部注入，便于离线测试）。"""

    def __init__(
        self,
        extractor: Optional[ContentExtractor] = None,
        robots: Any = None,
        http_getter: Optional[Callable[[str, int, str], Awaitable[str]]] = None,
        sites_config: Optional[Dict[str, Any]] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        default_timeout: int = DEFAULT_TIMEOUT,
    ):
        self.extractor = extractor or ContentExtractor()
        self.robots = robots
        self.sites_config = sites_config or {}
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.max_concurrency = self._clamp_concurrency(max_concurrency)
        self.default_timeout = self._clamp_timeout(default_timeout)
        # 默认 http_getter 使用 aiohttp（与 robots_checker/BaseSite 一致）；
        # 延迟 import 以保证本模块在缺少 aiohttp 时仍可被 import（离线测试）。
        self.http_getter = http_getter or self._default_http_getter

    # -- 参数收敛 ---------------------------------------------------------
    @staticmethod
    def _clamp_concurrency(value: Any) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = DEFAULT_MAX_CONCURRENCY
        return max(1, min(n, HARD_MAX_CONCURRENCY))

    @staticmethod
    def _clamp_timeout(value: Any) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = DEFAULT_TIMEOUT
        return max(1, min(n, HARD_MAX_TIMEOUT))

    def _resolve_concurrency(self, concurrency: Optional[int]) -> int:
        if concurrency is None:
            return self.max_concurrency
        return self._clamp_concurrency(concurrency)

    def _resolve_timeout(self, timeout: Optional[int]) -> int:
        if timeout is None:
            return self.default_timeout
        return self._clamp_timeout(timeout)

    # -- 站点选择器 -------------------------------------------------------
    def _selector_for(self, site_code: Optional[str]) -> Optional[str]:
        if not site_code:
            return None
        cfg = _site_entries(self.sites_config).get(site_code)
        if isinstance(cfg, dict):
            selector = cfg.get("content_selector")
            if selector:
                return str(selector)
        return None

    def infer_site_code(self, url: str) -> Optional[str]:
        """按 URL 推断站点码（实例方法，复用注入的 sites_config）。"""
        return infer_site_code(url, self.sites_config)

    # -- 默认 HTTP getter -------------------------------------------------
    @staticmethod
    async def _default_http_getter(url: str, timeout: int, user_agent: str) -> str:
        """默认 HTTP 抓取实现（aiohttp，与 robots_checker 一致）。"""
        import aiohttp  # 延迟 import：缺少 aiohttp 也不影响本模块被 import

        client_timeout = aiohttp.ClientTimeout(total=timeout)
        headers = {"User-Agent": user_agent}
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.text()

    # -- 单条抓取 ---------------------------------------------------------
    async def fetch_one(self, item: FetchItem, timeout: Optional[int] = None) -> FetchOutcome:
        """抓取单条：robots 检查 → HTTP → 抽取。任何失败都转成 FetchOutcome，不抛异常。"""
        start = time.monotonic()
        eff_timeout = self._resolve_timeout(timeout)
        outcome = FetchOutcome(url=item.url, record_id=item.record_id)

        # 0) URL 合法性
        parsed = urlparse(item.url or "")
        if not item.url or parsed.scheme not in ("http", "https") or not parsed.netloc:
            outcome.status = STATUS_FAILED
            outcome.error_code = INVALID_URL
            outcome.error_message = "URL 非法或缺失"
            outcome.retryable = False
            outcome.elapsed_ms = self._elapsed_ms(start)
            return outcome

        site_code = item.site_code or self.infer_site_code(item.url)

        # 1) robots 检查
        if self.robots is not None:
            try:
                allowed = await self.robots.can_fetch(item.url, self.user_agent)
            except Exception:
                # robots 检查异常默认放行（与 RobotsTxtChecker 语义一致）
                allowed = True
            if not allowed:
                outcome.status = STATUS_SKIPPED
                outcome.error_code = ROBOTS_DISALLOWED
                outcome.error_message = "robots.txt 禁止抓取"
                outcome.retryable = False
                outcome.elapsed_ms = self._elapsed_ms(start)
                return outcome

        # 2) HTTP 抓取
        try:
            html = await asyncio.wait_for(
                self.http_getter(item.url, eff_timeout, self.user_agent),
                timeout=eff_timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            outcome.status = STATUS_FAILED
            outcome.error_code = FETCH_TIMEOUT
            outcome.error_message = "抓取超时（%ss）" % eff_timeout
            outcome.retryable = True
            outcome.elapsed_ms = self._elapsed_ms(start)
            return outcome
        except Exception as exc:  # noqa: BLE001 —— 分类后转错误码
            code = self._classify_http_error(exc)
            outcome.status = STATUS_FAILED
            outcome.error_code = code
            outcome.error_message = str(exc) or type(exc).__name__
            outcome.retryable = True
            outcome.elapsed_ms = self._elapsed_ms(start)
            return outcome

        # 3) 抽取
        if not isinstance(html, str):
            html = "" if html is None else str(html)
        result: ExtractResult = self.extractor.extract(html, self._selector_for(site_code))
        if not result.text:
            outcome.status = STATUS_FAILED
            outcome.error_code = EXTRACT_EMPTY
            outcome.error_message = "正文抽取为空"
            outcome.extractor = result.extractor
            outcome.retryable = False
            outcome.elapsed_ms = self._elapsed_ms(start)
            return outcome

        outcome.status = STATUS_SUCCESS
        outcome.title = self._extract_title(html)
        outcome.content = result.text
        outcome.content_length = len(result.text)
        outcome.extractor = result.extractor
        outcome.elapsed_ms = self._elapsed_ms(start)
        return outcome

    # -- 批量抓取 ---------------------------------------------------------
    async def fetch_many(
        self,
        items: List[FetchItem],
        concurrency: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> List[FetchOutcome]:
        """按 Semaphore 限并发抓取多条，返回与输入等长的结果列表。

        单条失败/超时**不影响**其余条目（每条独立转 FetchOutcome，且并发壳里
        再兜一层异常）。
        """
        items = list(items or [])
        if not items:
            return []

        limit = self._resolve_concurrency(concurrency)
        semaphore = asyncio.Semaphore(limit)
        results: List[Optional[FetchOutcome]] = [None] * len(items)

        async def _run(index: int, item: FetchItem) -> None:
            async with semaphore:
                try:
                    results[index] = await self.fetch_one(item, timeout=timeout)
                except Exception as exc:  # 兜底：任何异常都不得拖垮整批
                    results[index] = FetchOutcome(
                        url=item.url,
                        record_id=item.record_id,
                        status=STATUS_FAILED,
                        error_code=INTERNAL_ERROR,
                        error_message=str(exc) or type(exc).__name__,
                        retryable=True,
                    )

        await asyncio.gather(*[_run(i, it) for i, it in enumerate(items)])
        return [r for r in results if r is not None]

    # -- 内部工具 ---------------------------------------------------------
    @staticmethod
    def _classify_http_error(exc: Exception) -> str:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if "timeout" in name or "timeout" in msg or "timed out" in msg:
            return FETCH_TIMEOUT
        if (
            "connect" in name
            or "connect" in msg
            or "clienterror" in name
            or "clientconnector" in name
            or "connection" in msg
        ):
            return FETCH_CONNECT_ERROR
        return FETCH_HTTP_ERROR

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        if not html:
            return None
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        title = ContentExtractor.normalize_text(match.group(1))
        return title or None


__all__ = [
    "ContentFetcher",
    "FetchItem",
    "FetchOutcome",
    "should_write_back",
    "infer_site_code",
    "FETCH_TIMEOUT",
    "FETCH_HTTP_ERROR",
    "FETCH_CONNECT_ERROR",
    "ROBOTS_DISALLOWED",
    "EXTRACT_EMPTY",
    "INVALID_URL",
    "INTERNAL_ERROR",
    "STATUS_SUCCESS",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
]
