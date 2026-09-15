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

退出码（运维契约，改这里必须同步改 runbook / script/zhihu_cookie_refresh.sh）
-----------------------------------------------------------------------------
  0 = ok           HTTP 200 且响应体解析出**非空** data 列表
  2 = 认证失败      401（code 101/100）**或** `cookie.auth` 缺失/为空
  3 = 其它一切      传输失败 / 响应体无法解析 / **任何其它非 200 状态（403/429/500/302…）**
                    / 状态文件不可用（父路径被普通文件占位、权限不足…）
                    / **续期没能拿到 cookie**，即
                      · 浏览器或运行环境不可用（playwright 缺失、chromium 未安装或装坏、
                        驱动启动失败），或
                      · 浏览器正常但持久化 profile 里**没有有效 z_c0**（cookie 已过期），
                        而与此同时 `config/zhihu.yaml` 里的凭证**仍然可用**（校验 rc=0）
仅**类别变化**时告警：ok→非ok 一定响铃（含 403/429 风控——它意味着采集已被静默阻断），
→ok 发恢复通知，同一类别反复出现不重复告警。

⚠️ 上一条 rc=3 有一个**刻意的例外**：--refresh 遇到「续期没拿到 cookie」时**不会**直接返回 3
了事，而是**仍然就地跑一次 check()**（探测凭证 → 需要时告警 → 落状态文件），只有 check()
判定凭证失效才返回 2（要人工扫码），否则才返回 3。
理由：若直接短路，就同时短路掉了认证探测、告警与状态落盘 —— cron 里 MAILTO="" 且只写日志
文件，于是「续期每天静默非 0」与「cookie 悄悄过期、zhihu 静默 0 条」会同时发生而无人察觉。
这正是 weibo 站点已经真实发生过的静默降级（`BrowserType.launch: Executable doesn't exist
at .../chrome-headless-shell`，被裸 print 吞掉数月无人发现）；本工具的存在意义就是让这类
故障响铃，绝不能自己犯同一个病。见 _probe_after_renewal_failure()。

⚠️ --login **不走**这条例外（同一个「没拿到 cookie」条件在交互路径上直接返回 2）：人就在
现场扫码，再推一条「请扫码」的告警是假告警。这条分叉是刻意的，见 run_browser_flow 里的注释。

告警投递是**持久化义务**（本工具的立身之本就是「出事会响」）
-----------------------------------------------------------------------------
状态文件除判定本身还记 `alert_pending` / `alert_message`：告警没送出去就保持 true，
之后**每一次**运行都会重试（即使类别没变、should_alert 返回 False），只有投递成功才清掉。
于是「投递失败的告警」不会在故障窗口里消失。退出码**不受投递结果影响**，仍是 0/2/3。

两处「不能静默丢义务」的补丁（都对应 tests 里的行为级用例）：

  · 状态文件**在盘上但读不动**（坏 JSON / 顶层不是对象）：读不出记录 ⇒ 既不知道上次是
    什么类别，也**不知道有没有一笔未送达的告警**。此时按「可能有」处理，合成一条公告并
    把状态文件重写成可用记录 —— 同一处损坏只会响一次（重写后下次就读得动了）。
    日志用 `UNREADABLE_STATE_MARKER` 与既有的 `状态文件无法解析`（宽容降级）区分。
  · `alert_pending=true` 但 `alert_message` 不是可用字符串（null / 42 / 空白 —— 只可能来自
    带外编辑或损坏）：**不能**把它当成「没有义务」而悄悄清标记，要合成一条通用公告补投。

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

# 状态 = **类别名**，直接落进状态文件：
#   ok          200 + data 为非空列表                → rc 0
#   auth_failed 401（code 101/100，或 cookie.auth 缺失/为空）→ rc 2
#   anti_bot    403 / 429（风控拦截，采集被静默阻断）  → rc 3
#   transport   连不上 / 超时 / TLS                    → rc 3
#   error       其它非 200（500/302…）、响应体无法解析、状态文件不可用 → rc 3
# 「类别名」而非粗粒度的 ok/error，是为了让状态机区分 401 认证 / 403·429 风控 / 传输失败：
# 只有类别**变了**才告警，同一类别反复出现不重复打扰。
STATE_OK = "ok"
STATE_AUTH_FAILED = "auth_failed"
STATE_ANTI_BOT = "anti_bot"
STATE_TRANSPORT = "transport"
STATE_ERROR = "error"

ANTI_BOT_STATUSES = (403, 429)

EXIT_BY_STATE = {
    STATE_OK: EXIT_OK,
    STATE_AUTH_FAILED: EXIT_AUTH,
    STATE_ANTI_BOT: EXIT_ERROR,
    STATE_TRANSPORT: EXIT_ERROR,
    STATE_ERROR: EXIT_ERROR,
}

AUTH_LABELS = {101: "无凭证/未识别", 100: "凭证过期"}

# 告警投递是**持久化义务**，不是一次性副作用：投递失败时状态文件会记 alert_pending=true，
# 之后每次运行都会重试，并在日志里打出这一行（运维 grep 这个标记就知道「有告警没送到」）。
PENDING_ALERT_MARKER = "未送达告警"

# 状态文件在盘上、但读不出记录时用的标记。刻意**不**复用 `状态文件无法解析`：
# 那条是「宽容降级、本次按无历史继续」，这条是「主动公告：可能有告警被丢弃」。运维 grep
# 到这一行就知道要去查那台机器的状态文件，而不是以为只是一次无害的读失败。
UNREADABLE_STATE_MARKER = "状态文件不可读"


class TransportError(Exception):
    """传输层失败（连不上、超时、TLS 等），与「认证失败」严格区分。"""


class StateWriteError(Exception):
    """状态文件不可用（父路径被普通文件占位 / 权限不足 / 磁盘错误等）。

    状态文件是「只在状态变化时告警」的判据，写不进去就无法判断本次是否发生变化。
    按 rc 契约「状态文件不可用 → 3」处理，绝不把 OSError 直抛给调用方。
    """


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

    state ∈ {"ok", "auth_failed", "anti_bot", "error"}；code 为接口 code（无则回落 HTTP status）。

    ⚠️ 本函数**必须不可崩**：任何人调用它时都不能让 AttributeError 冒出去把 --check/--refresh
    变成 rc=1「无状态、无告警」。曾经这里写成 `"... %s" % (a, b, c, d).strip()`，
    `.strip()` 绑在**元组**上而不是格式化结果上，于是任何非 200/401 的状态（403/429/500/302）
    都会 AttributeError。测试用「403/429/500/302 → rc=3 且不抛异常」把这条钉住。
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
            return STATE_OK, 200, ""
        if payload is None:
            detail = "HTTP 200 但响应体无法解析为 JSON（%s）" % (parse_error or "空响应体")
        else:
            # 注意：payload 可能是 list/str，直接 .get 会 AttributeError（同一类崩溃路径）
            data = payload.get("data") if isinstance(payload, dict) else None
            detail = "HTTP 200 但 data 不是非空列表（data=%r）" % (data,)
        return STATE_ERROR, status, detail

    if status == 401:
        if api_code == 101:
            label = AUTH_LABELS[101]
        elif api_code == 100 or "ERR_LOGIN_TICKET_EXPIRED" in api_message:
            label = AUTH_LABELS[100]
        else:
            label = "认证失败"
        detail = "code=%s %s name=%s message=%s" % (api_code, label, api_name, api_message)
        return STATE_AUTH_FAILED, api_code if api_code is not None else status, detail.strip()

    if status in ANTI_BOT_STATUSES:
        # 403/429 = 风控/限流：采集同样已经断流，必须响铃（而不是静静地 rc=3）
        detail = ("HTTP %s 风控拦截（anti-bot）name=%s message=%s %s"
                  % (status, api_name, api_message, parse_error))
        return STATE_ANTI_BOT, status, detail.strip()

    detail = "HTTP %s name=%s message=%s %s" % (status, api_name, api_message, parse_error)
    return STATE_ERROR, status, detail.strip()


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
    """读取状态文件，返回 `(record, unreadable)`。

    `unreadable` 为空串表示「拿到了一个可用记录」或「文件不存在（全新部署，按无历史）」；
    非空表示**文件在那儿但拿不到记录**，其值是一句给日志/公告用的原因。

    宽容是刻意的：状态文件只是「是否要告警」的判据，读坏了不应该让采集监控本身挂掉。
    但降级必须可见，而且**不能因此假装「没有未送达的告警」** —— 一个被写坏的 json 既能
    静默掉后续所有告警，也能悄悄吞掉一笔已经挂在账上的告警义务（调用方据此公告，见 check）。

    为什么 OS 级失败（**打不开**文件：被目录占位 / 权限不足 / 父路径被普通文件占位）不返回原因：

      · 本工具只会通过 `_write_state` 往这个路径原子写**普通文件**，所以「打不开」意味着该
        路径上不可能放着一份本工具写下的记录 ⇒ 没有可恢复的义务（不是「静默丢弃」，是「本来
        就没有」）；
      · 这类故障下 `_write_state` 几乎必然也失败（→ StateWriteError → rc=3，日志已点名路径
        与 OS 错误，见 tests [18]），「本次已经公告过」无处落盘 ⇒ 若此时也公告，就把一处
        持久性故障变成**每次运行响一次**的风暴，而「同一处故障只响一次」正是本工具的取舍。

    内容级失败（文件在、但解析不出来 / 顶层不是对象）则不同：那份记录**是本工具写的**，里面
    可能正躺着一笔未送达的告警；而文件就在预期路径上，本次运行能把它重写成可用记录 ⇒ 公告
    只会有一次（同一处损坏不会再响，见 tests [28] 的 6 连跑）。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, ""
    except Exception as e:
        LOG.warning("状态文件无法解析（%s）：%s: %s；本次按『无历史』继续（不重复告警判据失效）",
                    path, type(e).__name__, e)
        if isinstance(e, OSError):
            return {}, ""
        return {}, "%s: %s" % (type(e).__name__, e)
    if not isinstance(data, dict):
        LOG.warning("状态文件顶层不是 JSON 对象（%s，实际类型 %s）；本次按『无历史』继续",
                    path, type(data).__name__)
        return {}, "顶层不是 JSON 对象（实际类型 %s）" % type(data).__name__
    return data, ""


def _write_state(path, record):
    """原子写状态文件；任何 OS 层失败都收敛成 StateWriteError（→ rc=3）。"""
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            # ⚠️ exist_ok=True 救不了「父路径被**普通文件**占位」：那种情况仍抛
            # FileExistsError。这条路径曾经直抛给调用方，把 --check 变成 rc=1。
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        raise StateWriteError("%s (%s: %s)" % (path, type(e).__name__, e))


def _state_record(state, code, detail, pending_message):
    """构造状态文件记录：判定本身 + **这条转换的告警有没有真的送出去**。

    alert_pending / alert_message 是「投递失败不再丢」的唯一依据。只要 alert_pending
    为 true，下一次运行（**即使状态没有变化、should_alert 返回 False**）也会重新投递
    这条告警，直到 cookie_store.notify 返回 True 才清掉它。没有这两个字段时，「状态
    变了但告警没送到」在磁盘上和「状态变了且告警送到了」完全无法区分 ⇒ 下一次同类
    失败被判成「无变化」而永久静默（企微是本项目唯一告警通道）。

    alert_message 存的是告警**原文**，好让重试能一字不差地补投。它由
    state_alert_message()/recovery_alert_message() 生成，只含站点名 / code / detail，
    详细程度与日志相同 —— 不含 cookie 明文（[7]/[15]/[16] 有用例钉住这一点）。
    """
    return {
        "status": state,
        "ts": _now(),
        "code": code,
        "detail": detail,
        "alert_pending": bool(pending_message),
        "alert_message": pending_message or None,
    }


def _pending_alert(record):
    """从状态记录里取出「上一次转换的告警，且尚未送达」的原文；没有则返回 ""。

    ⚠️ `alert_pending=true` 但原文不可用（缺字段 / null / 非字符串 / 纯空白 —— 只可能来自
    带外编辑或损坏）时**绝不能**当成「没有义务」：旧实现直接返回 ""，于是这笔义务被静默清掉
    （投递 0 次、alert_pending 翻成 false、连 PENDING_ALERT_MARKER 都不打）。这里合成一条
    通用公告顶上 —— 原文补不回来，但「有一笔告警丢了」这件事必须传出去。
    """
    if not record.get("alert_pending"):
        return ""
    message = record.get("alert_message")
    if isinstance(message, str) and message.strip():
        return message
    LOG.error("%s：状态文件 alert_pending=true 但 alert_message 不是可用的字符串（%r），"
              "原文无法补投；合成一条通用公告顶上（绝不把义务当没有）",
              PENDING_ALERT_MARKER, message)
    return generic_pending_alert_message(record)


def generic_pending_alert_message(record):
    """`alert_pending=true` 但原文不可用时合成的通用公告。

    刻意不复述具体类别（原文丢了，猜类别只会误导），但必须给出**可执行的动作**：
    查告警通道、查状态文件。detail/code 来自落盘时的判定信息，不含 cookie 明文。
    """
    return ("[知乎Cookie] 站点=zhihu 状态=%s code=%s；状态文件标记 alert_pending=true"
            "（有一笔告警未送达），但 alert_message 原文不可用（%r），无法原样补投。"
            "请人工检查告警通道与状态文件。detail=%s"
            % (record.get("status") or "?", record.get("code"),
               record.get("alert_message"), record.get("detail") or ""))


def unreadable_state_alert_message(path, reason, state, code, detail):
    """状态文件在盘上但读不动时合成的公告。

    读不出记录 ⇒ 无法知道上一次是什么类别，也**无法知道有没有一笔未送达的告警**（原文就
    躺在那个读不动的文件里）。原文不可恢复，所以只能说清「可能有一条告警被丢弃」并把本次
    判定一起带上；宁可多响一次，也不静默吞掉一笔可能的义务（本工具存在的意义就是会响）。
    """
    return ("[知乎Cookie] 站点=zhihu %s（%s：%s）；无法确认上一次状态转换的告警是否已送达，"
            "可能有一条告警被丢弃。本次判定 state=%s code=%s（%s）。"
            "请人工检查该状态文件与告警通道。"
            % (UNREADABLE_STATE_MARKER, path, reason,
               state, "n/a" if code is None else code, detail))


# ---------------------------------------------------------------------------
# 告警文案
# ---------------------------------------------------------------------------
def auth_alert_message(code, detail):
    return ("[知乎Cookie] 站点=zhihu 状态=认证失败 code=%s（%s）；"
            "需要人工执行 python3 script/zhihu_cookie_tool.py --login 扫码登录" % (code, detail))


def anti_bot_alert_message(code, detail):
    return ("[知乎Cookie] 站点=zhihu 状态=风控拦截(anti-bot) code=%s（%s）；"
            "热榜接口已被风控静默拦截，采集实际已断流：请检查出口 IP / 降低请求频率，"
            "必要时人工执行 python3 script/zhihu_cookie_tool.py --login" % (code, detail))


def transport_alert_message(code, detail):
    return ("[知乎Cookie] 站点=zhihu 状态=传输失败 code=%s（%s）；"
            "网络/超时问题，先观察出口连通性，暂不需要人工扫码" % (code, detail))


def error_alert_message(code, detail):
    return ("[知乎Cookie] 站点=zhihu 状态=异常 code=%s（%s）；"
            "接口返回了非预期状态，请人工确认热榜接口是否变更" % (code, detail))


def state_alert_message(state, code, detail):
    """按**类别**产出告警文案：401 认证 / 403·429 风控 / 传输 / 其它异常各自可区分。

    类别不同 ⇒ 文案不同，运维一眼能看出「该扫一次码」还是「该查出口 IP」。
    """
    code = "n/a" if code is None else code
    if state == STATE_AUTH_FAILED:
        return auth_alert_message(code, detail)
    if state == STATE_ANTI_BOT:
        return anti_bot_alert_message(code, detail)
    if state == STATE_TRANSPORT:
        return transport_alert_message(code, detail)
    return error_alert_message(code, detail)


def recovery_alert_message(code):
    return ("[知乎Cookie] 站点=zhihu 状态=已恢复 code=%s；"
            "--refresh 续期成功且校验通过，无需人工介入" % code)


def should_alert(previous, state):
    """状态机：只在**类别变化**时告警。previous 为 "" 表示「无历史」。

    规则（每条都对应一个行为级用例）：
      · 同一类别重复出现 → 不重复告警；
      · 无历史时只有 auth_failed 告警（"凭证缺失"这条最确定的生产失效），
        传输/风控的偶发首现不打扰人；
      · 曾经 ok、现在任何非 ok → 一定响铃（含 403/429 风控）；
      · 两个不同的非 ok 类别之间切换 → 响铃；
      · →ok：previous 非空且不是 ok 时发恢复通知。
    """
    if not previous:
        return state == STATE_AUTH_FAILED
    if previous == state:
        return False
    return True


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
        state, code = STATE_AUTH_FAILED, None
        detail = "无凭证/未识别（%s）" % e
    except cookie_store.CookieConfigError as e:
        # 文件不存在 / 不是合法 YAML / 顶层结构不对：属配置或运维问题，
        # rc=3 且不 @all 告警（避免有人指错路径就打扰全员）。
        LOG.error("配置文件不可用：%s", e)
        return EXIT_ERROR
    else:
        LOG.info("读取 cookie.auth %s（来自 %s）", redact(cookie), config_path)
        try:
            # ⚠️ classify() 必须在 try **内部**调用：它不是「不可能出错」的纯函数
            # （D1：一行 `.strip()` 绑错对象就能让任何非 200/401 状态抛 AttributeError）。
            # 放进 try 体里，分类器出错最多退化成 rc=3，而不是逃出 check() 变成 rc=1
            # ——那种 rc 既没写状态文件也没发告警，是最糟的失效形态。
            status, body = fetch(DEFAULT_URL, cookie, timeout)
            state, code, detail = classify(status, body)
        except TransportError as e:
            detail = "传输失败: %s" % e
            LOG.error("请求热榜接口失败（%s）", detail)
            state, code = STATE_TRANSPORT, 0
        except Exception as e:
            detail = "未预期异常 %s: %s" % (type(e).__name__, e)
            LOG.error("请求热榜接口出现%s", detail)
            state, code = STATE_ERROR, 0

    LOG.info("状态文件: %s", resolved_state)
    previous_record, state_unreadable = _read_state(resolved_state)
    previous = str(previous_record.get("status") or "")
    # 上一次转换的告警如果**没有送到**，它就是一笔尚未偿还的债：本次必须重试，
    # 哪怕本次状态与上次完全相同（那种情况下 should_alert 会返回 False）。
    pending_message = _pending_alert(previous_record)
    if state_unreadable:
        # 文件在盘上却读不出记录 ⇒ 那条记录里可能正躺着一笔未送达的告警。原文已不可恢复，
        # 于是合成一条公告当作本次的待投递告警（与本次转换的公告合并，见下面 `if lost_note`）。
        # 关键：本次运行结束时会把状态文件**重写成可用记录**，所以同一处损坏只会响一次 ——
        # 不重复告警这条约束靠「修复 + 落盘」而不是靠内存里的去重状态。
        # 与上面的 `状态文件无法解析` 区分：那条是宽容降级，这条是主动公告（独立标记便于 grep）。
        lost_note = unreadable_state_alert_message(
            resolved_state, state_unreadable, state, code, detail)
        LOG.error("%s：状态文件读不动（%s：%s），无法判断是否存在未送达的告警；本次按『可能有』"
                  "处理并公告，同时把状态文件重写为可用记录（同一处损坏只会响一次）",
                  UNREADABLE_STATE_MARKER, resolved_state, state_unreadable)
    else:
        lost_note = ""
    if pending_message:
        LOG.error("%s：状态文件 alert_pending=true —— 上一次状态转换的告警没有送达，"
                  "本次运行会重试投递（这是运维唯一会看到这件事的地方）", PENDING_ALERT_MARKER)

    alert = None
    if state == STATE_OK:
        LOG.info("HTTP 200 且 data 为非空列表 → 凭证可用")
        for index, title in enumerate(top_titles(body), 1):
            LOG.info("  热榜 #%d %s", index, title)
        if previous and previous != STATE_OK:
            alert = recovery_alert_message(code)
    else:
        if state == STATE_AUTH_FAILED:
            LOG.error("认证失败：%s", detail)
        else:
            LOG.warning("凭证不可用（state=%s）：%s", state, detail)
        if should_alert(previous, state):
            alert = state_alert_message(state, code, detail)
        else:
            LOG.warning("上次状态 %r → 本次 %r：不重复告警",
                        previous or "<无历史>", state)

    if lost_note:
        # 读不动的状态文件带来的「可能丢了告警」和本次转换的公告**都**要送达，合并成一条：
        # 投递义务必须恒为**有界**的一条（合并后仍是 1 条，不是 2 条，更不是队列）。
        alert = (alert + "\n" + lost_note) if alert else lost_note

    # 本次要送达的告警 = 本次转换的告警（若有）优先，否则是上次欠下的那条。
    #
    # 实际规则（**不是**旧注释说的那样）：新的公告**总是**取代一笔未送达的旧公告，方向不限。
    # 理由是状态机的语义：一笔挂账代表「**当前类别**还没被公告出去」，而不是「历史上每个类别
    # 都要各公告一次」。类别一变，旧公告描述的就是过去的状态，只保留最新的那条才能让义务
    # 恒为 1 条（有界），也避免拿过期状态当现况误导运维。
    #
    # ⚠️ 真实代价（旧注释用「→ok 的恢复通知已经讲清了上一段故障的结局」解释，那只覆盖恢复
    # 方向）：**非 ok → 非 ok 的转换同样会取代**一笔未送达的旧公告，而恢复通知并不在场。
    # 随机回放里大多数取代都发生在两个失败类别之间（未送达的 auth_failed 被 anti_bot 取代）。
    # 此时被取代的那个条件**可能永远不会到达运维**（企微是唯一通道）；唯一的缓解是把被取代
    # 的原文**完整写进日志**（下面这行），让日志成为可审计的落点。tests 的 [30] 用两个方向
    # 的用例把这个取舍钉住（两个方向都不许改）。
    if alert and pending_message and alert != pending_message:
        LOG.warning("%s：上一次未送达的告警已被本次转换的告警取代（旧告警描述的状态已经过去，"
                    "本次告警已说明结局）；被取代的原文仅日志可查，可能不会到达运维=%s",
                    PENDING_ALERT_MARKER, pending_message)
    to_deliver = alert or pending_message

    # ⚠️ 顺序是刻意的：**先把「这次转换的公告还没送到」落盘，再尝试投递**。
    # 早期实现只落盘状态、把「投递成败」留在内存里，于是「通知投递失败」= 状态转换被判成
    # 已公告 ⇒ 投递恢复后也永远补不回来（整个故障窗口静默）。现在只要 alert_pending=true
    # 留在盘上，下一次运行就一定会重试；只有投递**成功**才会把它清掉。
    # 代价是每次有告警的运行会写两次状态文件（先标记、成功后清标记）——这是「送达与否必须
    # 持久化」的直接结果，顺序锁见 tests/test_zhihu_cookie_refresh.py 的 [24]。
    state_written = True
    if dry_run:
        LOG.info("[dry-run] 不写状态文件（实际会写 %s）", resolved_state)
    else:
        try:
            _write_state(resolved_state, _state_record(state, code, detail, to_deliver))
        except StateWriteError as e:
            LOG.error("状态文件不可用：%s；本次判定 state=%s 无法记账，按运维错误返回 rc=%d",
                      e, state, EXIT_ERROR)
            state_written = False

    if to_deliver:
        if dry_run:
            LOG.info("[dry-run] 本应发送通知：%s", to_deliver)
        else:
            delivered = False
            try:
                delivered = bool(cookie_store.notify(to_deliver, notifier))
            except Exception as e:
                # cookie_store.notify 的契约是「绝不抛」；这里再兜一层，保证即使那条契约
                # 被破坏（换实现 / 打补丁 / BaseException 之外的任何东西），也不会把本次
                # 判定（rc + 已落盘的 pending 标记）毁掉。
                # 注意这里**只**接 Exception：SystemExit / KeyboardInterrupt 仍然照常逃出去，
                # 但那时 alert_pending=true 已经在盘上，下一次运行会补投（见 [27]）。
                LOG.error("告警投递未预期异常（%s: %s）", type(e).__name__, e)
            if delivered:
                if not state_written:
                    LOG.error("告警本次已送达，但状态文件不可用（%s 标记无法写入/清除），"
                              "下次运行可能重复投递一次", PENDING_ALERT_MARKER)
                else:
                    # 只有投递成功才清标记；清标记失败宁可下次重复投一次，
                    # 也绝不能让「已送达」被误写成「未送达」——反过来才是永久静默。
                    try:
                        _write_state(resolved_state, _state_record(state, code, detail, ""))
                    except StateWriteError as e:
                        LOG.error("告警已送达但无法清除 alert_pending 标记（%s）：状态文件仍标记"
                                  "未送达，下次运行会重复投递一次；按状态文件不可用返回 rc=%d",
                                  e, EXIT_ERROR)
                        state_written = False
                    else:
                        LOG.info("%s：已成功送达（状态文件 alert_pending → false）",
                                 PENDING_ALERT_MARKER)
            else:
                LOG.error("告警投递失败：%s；状态转换已落盘（本次 rc 不受投递结果影响）——"
                          "%s：状态文件 alert_pending 保持 true，下次运行会继续重试",
                          to_deliver, PENDING_ALERT_MARKER)

    if not state_written:
        return EXIT_ERROR

    rc = EXIT_BY_STATE.get(state, EXIT_ERROR)
    LOG.info("判定结果 state=%s code=%s rc=%d", state, code, rc)
    return rc


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


def apply_refreshed_cookie(config_path, cookie_str, dry_run=False):
    """续期写回：**只在序列化后的 cookie 串真的变化时**改写 `cookie.auth`，写后回读复验。

    返回 True 表示确实落盘，False 表示磁盘上已是同值（跳过写入）。

    单独抽成函数是为了让「只在变化时写回 + 写后复验」这条 --refresh 的核心语义
    能在**没有浏览器**的环境里被直接验证（浏览器只是取 cookie 的手段）。
    """
    current = cookie_store.read_cookie_auth(config_path)  # 失败由调用方映射退出码
    if cookie_str == current:
        LOG.info("与磁盘上的 cookie.auth 一致（%s），跳过写回", redact(cookie_str))
        return False

    LOG.info("cookie 有变化：磁盘 %s → 浏览器 %s", redact(current), redact(cookie_str))
    if dry_run:
        LOG.info("[dry-run] 不写回 %s", config_path)
        return False

    _write_back(config_path, cookie_str)
    readback = cookie_store.read_cookie_auth(config_path)
    if readback != cookie_str:
        raise cookie_store.CookieWriteVerificationError(
            "写回后回读不一致：磁盘 %s vs 浏览器 %s" % (redact(readback), redact(cookie_str)))
    LOG.info("写回后回读一致，续期落盘确认")
    return True


def _probe_after_renewal_failure(config_path, state_path, fetcher, notifier, dry_run, reason):
    """续期流程**在拿到 cookie 之前就失败**时的兜底探测：rc 契约不变，但告警义务一条都不许丢。

    适用两条形态（都用 reason 如实描述，日志绝不与事实不符）：
      · 浏览器/运行环境不可用：playwright 不可导入 / chromium 装坏 / 驱动启动失败；
      · 浏览器正常但 profile 里**没有有效 z_c0**（= cookie 真的过期）。

    从前这几条分支都是直接 `return EXIT_ERROR` / `return EXIT_AUTH` —— 于是「续期没做成」
    同时意味着「不做认证探测、不写状态文件、不发告警」，只剩一行日志。而本工具的 cron 调用点
    `MAILTO=""` 且只写日志文件 ⇒ 续期每天静默非 0 的同时，cookie 在同一时间悄悄过期、
    zhihu 静默 0 条入库，几个月没人发现。这等于把 weibo 站点已经真实发生过的静默降级
    （`BrowserType.launch: Executable doesn't exist at .../chrome-headless-shell`，被裸 print
    吞掉）移植进了「为消灭静默失败而造」的这个工具里。

    所以这里用**完全相同的** config/state/fetcher/notifier/dry_run 跑一次 check()，
    借它的副作用去探测凭证、在凭证不可用时把告警发出去、并把状态落盘，然后：

      · check() == EXIT_AUTH → 凭证确实失效，告警已经发出 ⇒ 返回 EXIT_AUTH（要人工扫码）；
      · 否则（包括 check() 判成 ok 的情形）→ 续期确实没做成 ⇒ 返回 EXIT_ERROR。
        「凭证仍可用就不告警」是刻意的：此时采集**还没断**，报 2 会让 wrapper 打出
        「凭证仍不可用、需要人工扫码」这种**假指引**，还会诱发假告警；持续静默降级由 rc=3
        + 状态文件暴露，等 cookie 真的过期那一次再由 check() 的 401 升级成 rc=2 + 告警。

    check() 自身抛异常也兜住：rc 永远只落在 {0,2,3}，绝不因为这里变成 rc=1 + traceback ——
    那个 rc 既没落状态文件也没发告警，是比 rc=3 更糟的失效形态。
    """
    LOG.error("续期未拿到 cookie（%s）：仍就地跑一次 check 探测凭证可用性 —— 凭证若确实已失效，"
              "告警必须发出去（否则 cron 下只剩一行日志，cookie 过期无人知道）", reason)
    try:
        result = check(config_path=config_path, state_path=state_path, fetcher=fetcher,
                       notifier=notifier, dry_run=dry_run)
    except Exception as e:
        LOG.error("续期失败（%s）后的兜底 check 抛出未预期异常（%s: %s）；本次按 rc=%d 处理",
                  reason, type(e).__name__, e, EXIT_ERROR)
        return EXIT_ERROR
    if result == EXIT_AUTH:
        LOG.error("续期失败（%s），且兜底 check 判定凭证确实失效（rc=%d）：告警已发出，"
                  "需要人工执行 --login 扫码登录", reason, EXIT_AUTH)
        return EXIT_AUTH
    LOG.error("续期失败（%s），但兜底 check 未判定凭证失效（check rc=%s）—— 采集尚未断流，"
              "不上浮成 rc=2（避免假指引/假告警）；本次按 rc=%d 处理", reason, result, EXIT_ERROR)
    return EXIT_ERROR


def run_browser_flow(config_path, headless, timeout_s, settle_ms, dry_run, manual_hint,
                     state_path=None, fetcher=None, notifier=None):
    """--login / --refresh 的公共流程。返回退出码。"""
    try:
        cookie_str, error = _browser_cookie_string(headless, timeout_s, settle_ms)
    except ImportError as e:
        LOG.error("playwright 不可导入（%s）。--login/--refresh 需要 playwright + chromium；"
                  "--check 不需要浏览器。", e)
        # 浏览器不可用 ≠ 可以跳过认证探测：凭证若已失效，告警必须发出去（见函数 docstring）
        return _probe_after_renewal_failure(
            config_path, state_path, fetcher, notifier, dry_run,
            reason="playwright 不可导入，无法驱动浏览器")
    except Exception as e:
        LOG.error("启动/驱动浏览器失败：%s: %s", type(e).__name__, e)
        return _probe_after_renewal_failure(
            config_path, state_path, fetcher, notifier, dry_run,
            reason="启动/驱动浏览器失败（%s）" % type(e).__name__)

    if not cookie_str:
        # ⚠️ 这条分支**刻意**与 do_refresh 的同名分支分叉，不要在重构时「顺手统一」：
        # · --login 是**交互路径**：人就在现场准备扫码，再推一条「请扫码」的企微告警纯属噪声，
        #   而且会把「一次正常的人工登录」变成一次假告警（tests [15] 与 [31-L9] 故意锁住了
        #   「不误发通知、也不为它跑 check」）；
        # · --refresh 走 cron **无人值守**，同一个条件（profile 里没有有效 z_c0）意味着
        #   cookie 真的过期 ⇒ 必须响铃，所以那边会调 _probe_after_renewal_failure（见 do_refresh）。
        LOG.error("%s。%s", error, manual_hint)
        return EXIT_AUTH

    LOG.info("浏览器 cookie jar 序列化完成 %s", redact(cookie_str))

    if dry_run:
        LOG.info("[dry-run] 不写回 %s；仍做一次只读校验（不落状态文件、不发通知）", config_path)
    else:
        _write_back(config_path, cookie_str)
    # 退出码以「就地跑一次 check」为准：写回去不等于登录态真的可用
    return check(config_path=config_path, state_path=state_path, fetcher=fetcher,
                 notifier=notifier, dry_run=dry_run)


def do_login(config_path=None, dry_run=False, timeout_s=LOGIN_TIMEOUT_S,
             state_path=None, fetcher=None, notifier=None):
    """有头浏览器扫码登录一次，写回 cookie.auth，并立刻跑一次 check。"""
    config_path = config_path or DEFAULT_CONFIG
    LOG.info("有头浏览器启动，请在窗口里扫码登录知乎（profile=%s，超时 %ds）", PROFILE_DIR, timeout_s)
    return run_browser_flow(
        config_path, headless=False, timeout_s=timeout_s, settle_ms=0, dry_run=dry_run,
        manual_hint="未完成扫码登录", state_path=state_path, fetcher=fetcher, notifier=notifier)


def do_refresh(config_path=None, dry_run=False, timeout_s=LOGIN_TIMEOUT_S,
               state_path=None, fetcher=None, notifier=None):
    """无头复用持久化 profile 续期；cookie 真的变了才写回，写后回读校验，再跑 check。"""
    config_path = config_path or DEFAULT_CONFIG
    LOG.info("无头浏览器续期（profile=%s，settle=%dms，超时 %ds）",
             PROFILE_DIR, REFRESH_SETTLE_MS, timeout_s)

    try:
        cookie_str, error = _browser_cookie_string(
            headless=True, timeout_s=timeout_s, settle_ms=REFRESH_SETTLE_MS)
    except ImportError as e:
        LOG.error("playwright 不可导入（%s）。--refresh 需要 playwright + chromium。", e)
        # 浏览器不可用 ≠ 可以跳过认证探测：凭证若已失效，告警必须发出去（见函数 docstring）
        return _probe_after_renewal_failure(
            config_path, state_path, fetcher, notifier, dry_run,
            reason="playwright 不可导入，无法驱动浏览器")
    except Exception as e:
        LOG.error("启动/驱动浏览器失败：%s: %s", type(e).__name__, e)
        return _probe_after_renewal_failure(
            config_path, state_path, fetcher, notifier, dry_run,
            reason="启动/驱动浏览器失败（%s）" % type(e).__name__)

    if not cookie_str:
        LOG.error("%s。持久化 profile 已失效，需要人工执行 --login 重新扫码登录", error)
        # ⚠️ 这条分支**不能**像 run_browser_flow 那样直接 `return EXIT_AUTH`：--refresh 由 cron
        # 无人值守调用，而「profile 里没有有效 z_c0」= **cookie 真的过期** —— 正是本工具最想抓
        # 的那种生产失效。旧的直接返回只剩一行日志（cron MAILTO="" ⇒ 等于静默），而
        # script/zhihu_cookie_refresh.sh 头部注释早已宣称这里会走 --check 的告警路径。
        # 所以仍然就地跑一次 check：凭证确实不可用才返回 2（且告警已发出）；若 config 里的
        # 凭证其实还有效（profile 空但 cookie 未过期），返回 3 而不是 2，免得 wrapper 打出
        # 「凭证仍不可用，需要人工扫码」这种**假指引**、并诱发假告警。
        return _probe_after_renewal_failure(
            config_path, state_path, fetcher, notifier, dry_run,
            reason="持久化 profile 中无有效 z_c0（浏览器已正常返回）")

    LOG.info("浏览器 cookie jar 序列化完成 %s", redact(cookie_str))

    write_error = ""
    try:
        apply_refreshed_cookie(config_path, cookie_str, dry_run=dry_run)
    except (cookie_store.CookieWriteError, cookie_store.CookieConfigError) as e:
        write_error = "%s: %s" % (type(e).__name__, e)
        LOG.error("续期写回失败：%s", write_error)

    # 无论写回是否成功都要跑 check：凭证若确实不可用，告警必须发出去
    # （上面三条「续期没拿到 cookie」的失败分支同样适用 —— 见 _probe_after_renewal_failure）
    result = check(config_path=config_path, state_path=state_path, fetcher=fetcher,
                   notifier=notifier, dry_run=dry_run)
    if write_error and result == EXIT_OK:
        LOG.error("写回未成功但校验通过（%s）：本次凭证仍可用，故不告警，但续期并未落盘", write_error)
        return EXIT_ERROR
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
