#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知乎 Cookie 运维工具：`--check` / `--login` / `--refresh`

为什么存在
----------
知乎热榜接口 GET /api/v3/feed/topstory/hot-lists/total **必须带登录态**，没有任何匿名通道：
  · 完全无凭证 → HTTP 401 {"code":101,"name":"AuthenticationError","message":"身份未经过验证"}
  · cookie 过期 → HTTP 401 {"code":100,"name":"AuthenticationInvalidRequest",
                             "message":"ERR_LOGIN_TICKET_EXPIRED"}
`zhihu.py` 只读一个认证通道：`config/zhihu.yaml` 的 `cookie.auth`（→ headers['Cookie']）。
本工具把「人工开浏览器、复制 cookie、手改 yaml」这条链替换为：
  · `--login`   人工扫一次码（有头浏览器，持久化 profile）
  · `--refresh` 无头复用同一 profile 定期续期（cookie 真的变了才写回）
  · `--check`   纯 HTTP 判定可用性 + 仅在**状态变化**时告警（无需浏览器，可在任意机器跑）

退出码
------
  0 = 凭证可用     2 = 认证失败（需要人工 --login）     3 = 传输/解析/配置错误

依赖约束
--------
playwright **只在 --login / --refresh 内部延迟导入**，因此本文件可在没有 playwright
的机器上导入并跑 `--check`。HTTP 层走 stdlib urllib，且 `check()` 的 fetcher 可注入，
测试无需联网。
"""

import argparse
import fnmatch
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.services.collection import cookie_store  # noqa: E402  （仅 stdlib + PyYAML，无副作用）

LOG = logging.getLogger("zhihu_cookie")

# --- 常量 -------------------------------------------------------------------
DEFAULT_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

DEFAULT_CONFIG = os.path.join(REPO_ROOT, "config", "zhihu.yaml")
DEFAULT_STATE = os.path.join(REPO_ROOT, "logs", "zhihu_cookie_state.json")
FALLBACK_STATE = os.path.join(REPO_ROOT, "tmp", "zhihu_cookie_state.json")
PROFILE_DIR = os.path.join(REPO_ROOT, "runtime", "zhihu_profile")

# 有效 z_c0 形如 2|1:0|10:<发证时间戳>|4:z_c0|92:<base64>|<签名>（示例见 tests 里的合成值）
Z_C0_RE = re.compile(r"^2\|1:0\|10:\d+\|")

LOGIN_TIMEOUT_S = 300
REFRESH_SETTLE_MS = 12000
POLL_INTERVAL_MS = 5000

EXIT_OK = 0
EXIT_AUTH = 2
EXIT_ERROR = 3

EXIT_BY_STATE = {"ok": EXIT_OK, "auth_failed": EXIT_AUTH, "error": EXIT_ERROR}

AUTH_LABELS = {101: "无凭证/未识别", 100: "凭证过期"}


class TransportError(Exception):
    """传输层失败（连不上、超时、TLS 等），与「认证失败」严格区分。"""


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------
def redact(value):
    """Cookie 值只以长度 + 摘要出现，绝不落明文到日志/状态文件。"""
    if not value:
        return "<empty>"
    return "<%d chars sha256:%s>" % (len(value), hashlib.sha256(value.encode("utf-8")).hexdigest()[:8])


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# HTTP 层（stdlib，可注入替身）
# ---------------------------------------------------------------------------
def default_fetcher(url, cookie, timeout=10):
    """GET url 带 Cookie 头，返回 (status, body_text)。传输失败抛 TransportError。

    注意：401 由 urllib 抛 HTTPError，但其响应体带 code 101/100 —— 必须读出来才能区分
    「无凭证」与「凭证过期」，所以 HTTPError 要当成正常结果返回而不是当成传输失败。
    """
    request = urllib.request.Request(url, headers={
        "Cookie": cookie,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.zhihu.com/hot",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.getcode() or 0), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return int(e.code), body
    except Exception as e:  # URLError / socket.timeout / ssl.SSLError ...
        raise TransportError("%s: %s" % (type(e).__name__, e))


def classify(status, body):
    """把 (status, body) 判成 (state, code, detail)。

    state ∈ {"ok", "auth_failed", "error"}；code 为接口 code（无则回落 HTTP status）。
    """
    payload = None
    parse_error = ""
    if body:
        try:
            payload = json.loads(body)
        except Exception as e:
            parse_error = "%s: %s" % (type(e).__name__, e)

    api_code = None
    api_name = ""
    api_message = ""
    if isinstance(payload, dict):
        if isinstance(payload.get("code"), int):
            api_code = payload["code"]
        api_name = str(payload.get("name") or "")
        api_message = str(payload.get("message") or "")

    if status == 200:
        if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload["data"]:
            return "ok", 200, ""
        if payload is None:
            detail = "HTTP 200 但响应体无法解析为 JSON（%s）" % (parse_error or "空响应体")
        else:
            detail = "HTTP 200 但 data 不是非空列表（data=%r）" % (payload.get("data"),)
        return "error", status, detail

    if status == 401 or api_code in (100, 101):
        if api_code == 101:
            label = AUTH_LABELS[101]
        elif api_code == 100 or "ERR_LOGIN_TICKET_EXPIRED" in api_message:
            label = AUTH_LABELS[100]
        else:
            label = "认证失败"
        detail = "code=%s %s name=%s message=%s" % (api_code, label, api_name, api_message)
        return "auth_failed", api_code if api_code is not None else status, detail.strip()

    return "error", status, "HTTP %s name=%s message=%s %s" % (
        status, api_name, api_message, parse_error).strip()


def top_titles(body, limit=3):
    """从热榜响应里取前 limit 个标题（活体证明，非敏感信息）。"""
    try:
        data = json.loads(body).get("data") or []
    except Exception:
        return []
    titles = []
    for item in data:
        target = (item or {}).get("target") or {}
        title = str(target.get("title") or "").strip()
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


# ---------------------------------------------------------------------------
# 状态文件（只在状态变化时告警的判据）
# ---------------------------------------------------------------------------
def _gitignore_fallback_match(relpath):
    """.gitignore 的最小匹配（git 不可用时的兜底）。"""
    gitignore = os.path.join(REPO_ROOT, ".gitignore")
    if not os.path.exists(gitignore):
        return False
    try:
        with open(gitignore, "r", encoding="utf-8") as f:
            patterns = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return False
    rel = relpath.replace("\\", "/")
    base = os.path.basename(rel)
    for pattern in patterns:
        if pattern.startswith("!"):
            continue
        candidate = pattern.lstrip("/")
        if candidate.endswith("/"):
            if rel == candidate.rstrip("/") or rel.startswith(candidate):
                return True
            continue
        if fnmatch.fnmatch(base, candidate) or fnmatch.fnmatch(rel, candidate):
            return True
    return False


def _git_ignored(relpath):
    """路径是否被 git 忽略（先问 git，失败再退回 .gitignore 简易匹配）。"""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relpath],
            cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode in (0, 1):
            return result.returncode == 0
    except Exception:
        pass
    return _gitignore_fallback_match(relpath)


def resolve_state_path(explicit=None):
    """状态文件路径。默认 logs/ 下；若该路径未被 .gitignore 覆盖则回退到 tmp/。"""
    if explicit:
        return os.path.abspath(explicit)
    rel = os.path.relpath(DEFAULT_STATE, REPO_ROOT).replace("\\", "/")
    if _git_ignored(rel):
        return DEFAULT_STATE
    LOG.warning("状态文件默认路径 %s 未被 .gitignore 覆盖，改写到 %s", rel, FALLBACK_STATE)
    return FALLBACK_STATE


def _read_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(path, record):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 告警文案
# ---------------------------------------------------------------------------
def auth_alert_message(code, detail):
    return ("[知乎Cookie] 站点=zhihu 状态=认证失败 code=%s（%s）；"
            "需要人工执行 python3 script/zhihu_cookie_tool.py --login 扫码登录" % (code, detail))


def recovery_alert_message(code):
    return ("[知乎Cookie] 站点=zhihu 状态=已恢复 code=%s；"
            "--refresh 续期成功且校验通过，无需人工介入" % code)


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def check(config_path=None, state_path=None, fetcher=None, notifier=None,
          dry_run=False, timeout=10):
    """纯 HTTP 校验 cookie.auth；仅在状态变化时告警。返回退出码。"""
    config_path = config_path or DEFAULT_CONFIG
    resolved_state = resolve_state_path(state_path)
    fetch = fetcher if fetcher is not None else default_fetcher
    body = ""

    try:
        cookie = cookie_store.read_cookie_auth(config_path)
    except cookie_store.CookieAuthMissingError as e:
        # 文件读得动、YAML 也合法，但**没有凭证** —— 这是 zhihu 站点最可能的生产失效
        # 形态（读不到 cookie.auth → 一直 0 条入库且不报错），必须走状态机 + 告警，
        # 提示人工 --login；绝不能静默 return。
        LOG.error("凭证缺失：%s", e)
        cookie = ""
        state, code = "auth_failed", None
        detail = "无凭证/未识别（%s）" % e
    except cookie_store.CookieConfigError as e:
        # 文件不存在 / 不是合法 YAML / 顶层结构不对：属配置或运维问题，
        # rc=3 且不 @all 告警（避免有人指错路径就打扰全员）。
        LOG.error("配置文件不可用：%s", e)
        return EXIT_ERROR
    else:
        LOG.info("读取 cookie.auth %s（来自 %s）", redact(cookie), config_path)
        try:
            status, body = fetch(DEFAULT_URL, cookie, timeout)
        except TransportError as e:
            detail = "传输失败: %s" % e
            LOG.error("请求热榜接口失败（%s）", detail)
            state, code = "error", 0
        except Exception as e:
            detail = "未预期异常 %s: %s" % (type(e).__name__, e)
            LOG.error("请求热榜接口出现%s", detail)
            state, code = "error", 0
        else:
            state, code, detail = classify(status, body)

    LOG.info("状态文件: %s", resolved_state)
    previous = str(_read_state(resolved_state).get("status") or "")

    alert = None
    if state == "ok":
        LOG.info("HTTP 200 且 data 为非空列表 → 凭证可用")
        for index, title in enumerate(top_titles(body), 1):
            LOG.info("  热榜 #%d %s", index, title)
        if previous == "auth_failed":
            alert = recovery_alert_message(code)
    elif state == "auth_failed":
        LOG.error("认证失败：%s", detail)
        if previous == "auth_failed":
            LOG.warning("与上次状态相同（auth_failed），不重复告警")
        else:
            alert = auth_alert_message(code if code is not None else "n/a", detail)
    else:
        LOG.warning("无法判定凭证状态：%s", detail)

    if alert:
        if dry_run:
            LOG.info("[dry-run] 本应发送通知：%s", alert)
        else:
            cookie_store.notify(alert, notifier)

    if dry_run:
        LOG.info("[dry-run] 不写状态文件（实际会写 %s）", resolved_state)
    else:
        _write_state(resolved_state, {
            "status": state, "ts": _now(), "code": code, "detail": detail,
        })

    LOG.info("判定结果 state=%s code=%s rc=%d", state, code, EXIT_BY_STATE[state])
    return EXIT_BY_STATE[state]


# ---------------------------------------------------------------------------
# --login / --refresh（playwright 延迟导入）
# ---------------------------------------------------------------------------
def _has_valid_z_c0(cookies):
    for item in cookies or []:
        if item.get("name") == "z_c0" and Z_C0_RE.match(str(item.get("value") or "")):
            return True
    return False


def _browser_cookie_string(headless, timeout_s, settle_ms):
    """打开持久化 profile，等 z_c0 生效，返回序列化后的 cookie 串。

    返回 (cookie_str, error)：超时或未登录时 cookie_str 为 None。
    **读 cookies 必须在 context.close() 之前** —— 关闭后 context 即失效。
    """
    from playwright.sync_api import sync_playwright  # 延迟导入：--check 环境无需 playwright

    os.makedirs(PROFILE_DIR, exist_ok=True)
    cookie_str = None
    error = ""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.zhihu.com", wait_until="domcontentloaded")

            deadline = time.monotonic() + timeout_s
            logged_in = False
            while time.monotonic() < deadline:
                if _has_valid_z_c0(context.cookies()):
                    logged_in = True
                    break
                page.wait_for_timeout(POLL_INTERVAL_MS)

            if not logged_in:
                error = "在 %ds 内未检测到有效的 z_c0 cookie" % timeout_s
                return None, error

            if settle_ms:
                page.wait_for_timeout(settle_ms)  # 给页面时间把续期后的 token 写回 jar
            # ← 必须在 close() 之前读；关闭后再读是空的
            cookie_str = cookie_store.format_cookie_header(context.cookies())
        finally:
            context.close()

    if not cookie_str:
        return None, "浏览器 cookie jar 序列化结果为空"
    return cookie_str, ""


def _write_back(config_path, cookie_str):
    backup_path = os.path.join(
        REPO_ROOT, "tmp", "zhihu.yaml.%s.bak" % datetime.now().strftime("%Y%m%d%H%M%S"))
    cookie_store.write_cookie_auth(config_path, cookie_str, backup_path=backup_path)
    LOG.info("已写回 %s 的 cookie.auth（%s），原文件备份到 %s",
             config_path, redact(cookie_str), backup_path)


def run_browser_flow(config_path, headless, timeout_s, settle_ms, dry_run, manual_hint):
    """--login / --refresh 的公共流程。返回退出码。"""
    try:
        cookie_str, error = _browser_cookie_string(headless, timeout_s, settle_ms)
    except ImportError as e:
        LOG.error("playwright 不可导入（%s）。--login/--refresh 需要 playwright + chromium；"
                  "--check 不需要浏览器。", e)
        return EXIT_ERROR
    except Exception as e:
        LOG.error("启动/驱动浏览器失败：%s: %s", type(e).__name__, e)
        return EXIT_ERROR

    if not cookie_str:
        LOG.error("%s。%s", error, manual_hint)
        return EXIT_AUTH

    LOG.info("浏览器 cookie jar 序列化完成 %s", redact(cookie_str))

    if dry_run:
        LOG.info("[dry-run] 不写回 %s，也不发通知", config_path)
        return EXIT_OK

    _write_back(config_path, cookie_str)
    return check(config_path=config_path)


def do_login(config_path=None, dry_run=False, timeout_s=LOGIN_TIMEOUT_S):
    """有头浏览器扫码登录一次，写回 cookie.auth，并立刻跑一次 check。"""
    config_path = config_path or DEFAULT_CONFIG
    LOG.info("有头浏览器启动，请在窗口里扫码登录知乎（profile=%s，超时 %ds）", PROFILE_DIR, timeout_s)
    return run_browser_flow(
        config_path, headless=False, timeout_s=timeout_s, settle_ms=0, dry_run=dry_run,
        manual_hint="未完成扫码登录")


def do_refresh(config_path=None, dry_run=False, timeout_s=LOGIN_TIMEOUT_S):
    """无头复用持久化 profile 续期；cookie 真的变了才写回，写后回读校验，再跑 check。"""
    config_path = config_path or DEFAULT_CONFIG
    LOG.info("无头浏览器续期（profile=%s，settle=%dms，超时 %ds）",
             PROFILE_DIR, REFRESH_SETTLE_MS, timeout_s)

    try:
        cookie_str, error = _browser_cookie_string(
            headless=True, timeout_s=timeout_s, settle_ms=REFRESH_SETTLE_MS)
    except ImportError as e:
        LOG.error("playwright 不可导入（%s）。--refresh 需要 playwright + chromium。", e)
        return EXIT_ERROR
    except Exception as e:
        LOG.error("启动/驱动浏览器失败：%s: %s", type(e).__name__, e)
        return EXIT_ERROR

    if not cookie_str:
        LOG.error("%s。持久化 profile 已失效，需要人工执行 --login 重新扫码登录", error)
        return EXIT_AUTH

    LOG.info("浏览器 cookie jar 序列化完成 %s", redact(cookie_str))

    try:
        current = cookie_store.read_cookie_auth(config_path)
    except cookie_store.CookieConfigError as e:
        LOG.error("读取当前 cookie.auth 失败：%s", e)
        return EXIT_ERROR

    if cookie_str == current:
        LOG.info("与磁盘上的 cookie.auth 一致（%s），跳过写回", redact(cookie_str))
    else:
        LOG.info("cookie 有变化：磁盘 %s → 浏览器 %s", redact(current), redact(cookie_str))
        if dry_run:
            LOG.info("[dry-run] 不写回 %s", config_path)
        else:
            _write_back(config_path, cookie_str)
            try:
                readback = cookie_store.read_cookie_auth(config_path)
            except cookie_store.CookieConfigError as e:
                LOG.error("写回后回读失败：%s", e)
                return EXIT_ERROR
            if readback != cookie_str:
                LOG.error("写回后回读不一致：磁盘 %s vs 浏览器 %s",
                          redact(readback), redact(cookie_str))
                return EXIT_ERROR
            LOG.info("写回后回读一致，续期落盘确认")

    result = check(config_path=config_path, dry_run=dry_run)
    if result != EXIT_OK:
        LOG.error("续期后校验未通过（rc=%d）：需要人工执行 --login 扫码登录", result)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="zhihu_cookie_tool.py",
        description="知乎 Cookie 运维工具：--check（纯 HTTP）/ --login（有头扫码）/ --refresh（无头续期）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="用 stdlib HTTP 校验 cookie.auth 是否可用（无浏览器）")
    group.add_argument("--login", action="store_true",
                       help="有头浏览器扫码登录一次，写回 cookie.auth")
    group.add_argument("--refresh", action="store_true",
                       help="无头复用持久化 profile 续期 cookie.auth")
    parser.add_argument("--config", default=None,
                        help="zhihu.yaml 路径（默认 <repo>/config/zhihu.yaml）")
    parser.add_argument("--state", default=None,
                        help="状态文件路径（默认 logs/zhihu_cookie_state.json）")
    parser.add_argument("--timeout", type=int, default=LOGIN_TIMEOUT_S,
                        help="--check 的 HTTP 超时 / --login|--refresh 的等待秒数（默认 300）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只计算并打印，绝不改写 yaml / 状态文件 / 发通知")
    return parser


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stdout)
    args = build_parser().parse_args(argv)
    config_path = args.config or DEFAULT_CONFIG

    if args.check:
        return check(config_path=config_path, state_path=args.state,
                     dry_run=args.dry_run, timeout=args.timeout)
    if args.login:
        return do_login(config_path=config_path, dry_run=args.dry_run, timeout_s=args.timeout)
    return do_refresh(config_path=config_path, dry_run=args.dry_run, timeout_s=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
