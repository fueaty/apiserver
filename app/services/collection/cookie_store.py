# -*- coding: utf-8 -*-
"""
知乎 Cookie 纯函数工具（依赖：stdlib + PyYAML）。

职责边界
--------
  · 解析 / 序列化 `k=v; k=v` 形式的 Cookie 头字符串；
  · 读取 config/zhihu.yaml 的 `cookie.auth`；
  · **单行写回** `cookie.auth` —— 只改这一行的值，其余字节完全不动。

设计红线（由 tests/test_zhihu_cookie_refresh.py 的行为级用例守卫，改动前先读那个文件）
--------------------------------------------------------------------------------
  1. 写回前必须确认 `cookie:` 段内 `auth:` 行**恰好一条**；0 条或 >1 条一律抛错，绝不猜。
  2. 除 auth 行外，注释 / 键序 / 空行 / 缩进 / 其它键（含 cookie.z_c0、cookie._xsrf、
     access_token、authorization、collection.result_limit）必须**字节不变**。
  3. 保留文件原有换行约定（LF / CRLF）。本仓库在 Windows 上带 core.autocrlf，
     绝不能让通用换行模式把 CRLF 悄悄改写成 LF —— 故全程以二进制读写 + 逐行保留 EOL。
  4. 写盘后**回读校验**；回读值与写入值不一致必须抛错，绝不静默报成功。
  5. 幂等：同一值连写两次，文件字节不变。

副作用约束
----------
本模块**不得**在导入期引入 playwright / 网络 / 通知等副作用；通知走 `notify()` 的
延迟导入，测试可注入替身（fake）。因此本模块可在无浏览器、无 aiohttp 的机器上导入。
"""

import hashlib
import os
import re

import yaml

__all__ = [
    "CookieConfigError",
    "CookieAuthMissingError",
    "CookieWriteError",
    "CookieWriteVerificationError",
    "parse_cookie_header",
    "format_cookie_header",
    "read_cookie_auth",
    "write_cookie_auth",
    "notify",
]


class CookieConfigError(Exception):
    """配置文件缺失 / 不是合法 YAML / 顶层结构不对。"""


class CookieAuthMissingError(CookieConfigError):
    """文件读得动、YAML 也合法，但 `cookie:` 段或 `cookie.auth` 缺失/为空。

    与 CookieConfigError 分开，是为了让 `--check` 能区分两类失败（否则
    "cookie 被清空" 这条**最可能发生**的生产失效会静默）：

      · 文件不存在 / YAML 坏 → 配置或运维问题：rc=3，不推送 @all 告警
        （避免有人在别的机器上指错路径就 @all 一次）；
      · 文件正常但没有凭证   → 真实的生产失效：rc=2，必须告警要求人工 --login
        （zhihu.py 读不到 cookie.auth 就会一直 0 条入库且不报错）。
    """


class CookieWriteError(Exception):
    """写回前置校验失败（结构不唯一、目标行无法解析等）。"""


class CookieWriteVerificationError(CookieWriteError):
    """写盘后回读校验不通过。"""


def _fingerprint(value):
    """用于日志/异常的脱敏指纹：绝不出现在明文 Cookie 值。"""
    if value is None:
        return "<None>"
    data = value.encode("utf-8", "replace")
    return "<%d bytes sha256:%s>" % (len(data), hashlib.sha256(data).hexdigest()[:12])


# ---------------------------------------------------------------------------
# Cookie 头字符串 <-> dict
# ---------------------------------------------------------------------------
def parse_cookie_header(raw):
    """解析 `k=v; k=v; ...` 形式的 Cookie 头。

    - 按 `;` 切分，每段先 strip；
    - 只按**第一个** `=` 切分（值里允许出现 `=`、`|`、`/`、`+`、`:`、空格）；
    - 空段（或 strip 后为空）与不含 `=` 的段一律跳过。
    """
    cookies = {}
    if not raw:
        return cookies
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            continue
        cookies[key] = value
    return cookies


def format_cookie_header(cookies):
    """把 cookie 集合序列化为 Cookie 头字符串。

    - list[dict]（playwright `context.cookies()` 的形状，每项含 name/value）
      → 按**列表顺序**连接（顺序即浏览器顺序，不能重排）；
    - dict → 按 key 排序后连接（保证确定性）。
    """
    if isinstance(cookies, dict):
        items = [(str(k), cookies[k]) for k in sorted(cookies.keys())]
    elif isinstance(cookies, (list, tuple)):
        items = []
        for item in cookies:
            if not isinstance(item, dict) or "name" not in item:
                raise TypeError("cookie 列表项必须是含 name/value 的 dict，收到: %r" % (item,))
            items.append((str(item["name"]), item.get("value", "")))
    else:
        raise TypeError("format_cookie_header 只接受 list[dict] 或 dict，收到: %s" % type(cookies).__name__)

    return "; ".join("%s=%s" % (name, value) for name, value in items)


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def read_cookie_auth(yaml_path):
    """返回 `cookie.auth` 字符串；缺失时抛 CookieConfigError（消息里指明缺哪一层）。"""
    if not os.path.exists(yaml_path):
        raise CookieConfigError("配置文件不存在: %s" % yaml_path)
    try:
        with open(yaml_path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise CookieConfigError("读取配置文件失败: %s (%s)" % (yaml_path, e))

    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise CookieConfigError("配置文件不是 UTF-8 文本: %s (%s)" % (yaml_path, e))
    except yaml.YAMLError as e:
        raise CookieConfigError("配置文件不是合法 YAML: %s (%s)" % (yaml_path, e))

    if not isinstance(data, dict):
        raise CookieConfigError("配置文件顶层不是映射: %s" % yaml_path)
    cookie = data.get("cookie")
    if not isinstance(cookie, dict):
        raise CookieAuthMissingError("配置文件缺少 `cookie:` 段: %s" % yaml_path)
    if "auth" not in cookie:
        raise CookieAuthMissingError("配置文件的 `cookie:` 段缺少 `auth:` 键: %s" % yaml_path)
    value = cookie.get("auth")
    if not isinstance(value, str) or not value.strip():
        raise CookieAuthMissingError("配置文件的 `cookie.auth` 为空: %s" % yaml_path)
    return value


# ---------------------------------------------------------------------------
# 单行写回（风险最高的函数，逐条满足上面的红线 1-5）
# ---------------------------------------------------------------------------
_KEY_LINE_RE = re.compile(r"^([ \t]*)([^:#]+?)[ \t]*:(.*)$")
_AUTH_LINE_RE = re.compile(r"^([ \t]*auth[ \t]*:)([ \t]*)(.*)$")


def _split_eol(raw):
    """把一行拆成 (行体, 行尾 EOL)，EOL 原样保留。"""
    if raw.endswith("\r\n"):
        return raw[:-2], "\r\n"
    if raw.endswith("\n"):
        return raw[:-1], "\n"
    if raw.endswith("\r"):
        return raw[:-1], "\r"
    return raw, ""


def _indent_width(prefix):
    return len(prefix.expandtabs(8))


def _find_auth_key_lines(text_lines, section="cookie"):
    """定位 `cookie:` 段内**所有**定义 `auth:` 的行号（0 基）。"""
    hits = []
    section_indent = None
    for index, raw in enumerate(text_lines):
        body, _eol = _split_eol(raw)
        stripped = body.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _KEY_LINE_RE.match(body)
        if m is None:
            continue
        indent = _indent_width(m.group(1))
        key = m.group(2).strip()
        if section_indent is None:
            if key == section and indent == 0:
                section_indent = indent
            continue
        if indent <= section_indent:
            break  # 段结束
        if key == "auth":
            hits.append(index)
    return hits


def _trailing_after_value(rest):
    """取出「值 token」之后原样保留的尾巴（行内注释等）。"""
    if rest[:1] in ('"', "'"):
        quote = rest[0]
        i, n = 1, len(rest)
        while i < n:
            ch = rest[i]
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and i + 1 < n and rest[i + 1] == "'":
                    i += 2  # YAML 单引号内的 '' 转义
                    continue
                return rest[i + 1:]
            i += 1
        return ""  # 引号未闭合：当作没有尾巴
    if rest.startswith("#"):
        return rest
    m = re.search(r"[ \t]#", rest)
    return rest[m.start():] if m else ""


def write_cookie_auth(yaml_path, cookie_str, backup_path=None):
    """只改写 `cookie:` 段内那一行 `auth:` 的值，其余字节保持不变。

    成功后返回 None；任何前置校验 / 回读校验失败都抛异常（绝不静默成功）。
    """
    if not isinstance(cookie_str, str) or not cookie_str.strip():
        raise CookieWriteError("拒绝写入空的 cookie.auth")
    if "\r" in cookie_str or "\n" in cookie_str:
        raise CookieWriteError("cookie 串不允许包含换行（防 HTTP 头注入）")

    try:
        with open(yaml_path, "rb") as f:
            raw_bytes = f.read()
    except FileNotFoundError:
        raise CookieConfigError("配置文件不存在: %s" % yaml_path)
    except OSError as e:
        raise CookieWriteError("读取配置文件失败: %s (%s)" % (yaml_path, e))

    text = raw_bytes.decode("utf-8", "surrogateescape")
    text_lines = text.splitlines(keepends=True)

    hits = _find_auth_key_lines(text_lines)
    if not hits:
        raise CookieWriteError(
            "`cookie:` 段内未找到 `auth:` 行（0 条），拒绝写入: %s" % yaml_path)
    if len(hits) > 1:
        raise CookieWriteError(
            "`cookie:` 段内 `auth:` 行出现 %d 条（第 %s 行），无法确定改哪一条，拒绝写入: %s"
            % (len(hits), [i + 1 for i in hits], yaml_path))

    index = hits[0]
    body, eol = _split_eol(text_lines[index])
    m = _AUTH_LINE_RE.match(body)
    if m is None:  # 定位阶段已按同一正则匹配过，这里属防御
        # 注意：这里绝不能用 %r 打整行 —— 那一行就是实时 Cookie 明文
        raise CookieWriteError("无法解析第 %d 行的 auth 行（%s）"
                               % (index + 1, _fingerprint(body)))

    prefix = m.group(1) + m.group(2)
    suffix = _trailing_after_value(m.group(3))
    escaped = cookie_str.replace("\\", "\\\\").replace('"', '\\"')
    # 值统一用双引号标量：cookie 值含 ":"、"|"、"/"、"+"、"#" 时裸标量会破 YAML。
    text_lines[index] = prefix + '"' + escaped + '"' + suffix + eol

    new_bytes = "".join(text_lines).encode("utf-8", "surrogateescape")

    if new_bytes.count(b"\r\n") != raw_bytes.count(b"\r\n"):
        raise CookieWriteError(
            "写回后 CRLF 数量发生变化（%d → %d），拒绝写入: %s"
            % (raw_bytes.count(b"\r\n"), new_bytes.count(b"\r\n"), yaml_path))

    if backup_path:
        parent = os.path.dirname(os.path.abspath(backup_path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(backup_path, "wb") as f:
            f.write(raw_bytes)

    if new_bytes != raw_bytes:  # 幂等：值相同则一个字节都不动
        tmp_path = yaml_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(new_bytes)
        os.replace(tmp_path, yaml_path)

    actual = read_cookie_auth(yaml_path)  # ← 回读校验（测试会打桩以自证这条路径真的会触发）
    if actual != cookie_str:
        raise CookieWriteVerificationError(
            "写回后回读不一致: 期望 %s，实际 %s（%s）"
            % (_fingerprint(cookie_str), _fingerprint(actual), yaml_path))
    return None


# ---------------------------------------------------------------------------
# 可注入通知
# ---------------------------------------------------------------------------
def notify(message, notifier=None):
    """发送运维通知。

    notifier 为 None 时**延迟导入** app.wework.notification_push 并调用 send_message
    （该模块会拉起 aiohttp/requests，故不能放在导入期）。测试传 fake 即可完全离线。

    返回 True 表示已成功投递；notifier 抛异常时记录并返回 False（不让告警失败拖垮退出码）。
    """
    if notifier is None:
        from app.wework.notification_push import send_message  # noqa: PLC0415  延迟导入是刻意的
        notifier = send_message
    try:
        notifier(message)
        return True
    except Exception as e:  # 通知失败不应改变 --check 的判定结果
        print("发送通知失败: %s: %s" % (type(e).__name__, e))
        return False
