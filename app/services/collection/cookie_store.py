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
  5. 幂等：同一值连写两次，文件字节不变（且**不触发任何原子替换**）。
  6. 事务性：**每一条拒绝路径**都必须让目标文件逐字节等于调用前 —— 预校验在写盘之前，
     回读失败则用内存里的原始字节还原后再抛。

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
    """定位 `cookie:` 段内**直接子键**里所有定义 `auth:` 的行号（0 基）。

    ⚠️ 只认直接子键（缩进等于段内**第一个**子键的缩进）。早期实现认「缩进 > 段缩进」
    的所有行，于是 `cookie: > nested: > auth:` 这种**嵌套**同名键也会命中：那一行会被
    改写，紧接着回读时 `cookie.auth` 依然缺失 → 抛 CookieAuthMissingError，把「拒绝写入」
    这条红线变成了「先改再报错」。嵌套键必须视为 **0 条**（拒绝），而不是 1 条。
    """
    hits = []
    section_indent = None
    child_indent = None
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
        if child_indent is None:
            child_indent = indent  # 段内第一个子键的缩进 = 直接子级缩进
        if indent != child_indent:
            continue  # 比直接子级更深的键属嵌套，一律不算
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


def _atomic_write(path, data):
    """同目录临时文件 + ``os.replace`` 的原子落盘。"""
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, path)


def _restore_bytes(path, raw_bytes):
    """把文件还原成本次调用开始时的原始字节；返回 True/False。

    只在「已经动过盘、但后续校验失败」时调用：红线 4 要求绝不静默报成功，
    但同样不能把半成品（改了一半 / 回读撒谎）留在**生产凭据文件**上。
    """
    try:
        _atomic_write(path, raw_bytes)
        return True
    except OSError:
        return False


def write_cookie_auth(yaml_path, cookie_str, backup_path=None):
    """只改写 `cookie:` 段内那一行 `auth:` 的值，其余字节保持不变。

    成功后返回 None；任何前置校验 / 回读校验失败都抛异常（绝不静默成功），
    且**每条拒绝路径都必须让文件逐字节等于调用前**（事务性）。

    执行顺序刻意是「先在内存里渲染并结构校验 → 备份 → 原子落盘 → 回读 →
    失败则用内存里的原始字节还原」。早期实现把回读校验放在 ``os.replace``
    **之后**且不做还原，于是「回读撒谎」这条路径会把改写后的文件留在盘上。
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
    new_lines = list(text_lines)
    new_lines[index] = prefix + '"' + escaped + '"' + suffix + eol
    new_bytes = "".join(new_lines).encode("utf-8", "surrogateescape")

    # --- 写盘**之前**的结构性预校验：拒绝必须发生在动盘之前 -------------------
    if len(new_lines) != len(text_lines):
        raise CookieWriteError("写回后行数发生变化（%d → %d），拒绝写入: %s"
                               % (len(text_lines), len(new_lines), yaml_path))
    changed = [i for i in range(len(text_lines)) if text_lines[i] != new_lines[i]]
    if changed not in ([], [index]):
        # [] 表示渲染结果与原文完全相同（幂等，本就不需要写盘）；[index] 表示恰好只改 auth 行。
        raise CookieWriteError(
            "写回结构异常：期望只改第 %d 行，实际改动行 %s，拒绝写入: %s"
            % (index + 1, [i + 1 for i in changed], yaml_path))
    if (new_bytes.count(b"\n") != raw_bytes.count(b"\n")
            or new_bytes.count(b"\r") != raw_bytes.count(b"\r")):
        raise CookieWriteError(
            "写回后换行约定发生变化（LF %d → %d，CR %d → %d），拒绝写入: %s"
            % (raw_bytes.count(b"\n"), new_bytes.count(b"\n"),
               raw_bytes.count(b"\r"), new_bytes.count(b"\r"), yaml_path))

    # --- 备份（先备份后写；备份失败时目标文件尚未被动过） ---------------------
    if backup_path:
        try:
            parent = os.path.dirname(os.path.abspath(backup_path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            with open(backup_path, "wb") as f:
                f.write(raw_bytes)
        except OSError as e:
            raise CookieWriteError("写入备份失败: %s (%s: %s)"
                                   % (backup_path, type(e).__name__, e))

    # --- 原子落盘（幂等：渲染结果与原文相同则一个字节都不动） -----------------
    if new_bytes != raw_bytes:
        try:
            _atomic_write(yaml_path, new_bytes)
        except OSError as e:
            raise CookieWriteError("写盘失败: %s (%s: %s)"
                                   % (yaml_path, type(e).__name__, e))

    # --- 回读校验；任何不一致都要**先把文件还原成原始字节**再抛 --------------
    actual = None
    read_error = None
    try:
        # 回读校验（测试会打桩以自证这条路径真的会触发）
        actual = read_cookie_auth(yaml_path)
    except Exception as e:  # 读不回来同样不算校验通过，且磁盘状态未知
        read_error = e
    if read_error is not None or actual != cookie_str:
        restored = _restore_bytes(yaml_path, raw_bytes)
        suffix_note = "" if restored else "；且原文件还原失败"
        if read_error is not None:
            raise CookieWriteVerificationError(
                "写回后回读失败: %s: %s（%s）%s"
                % (type(read_error).__name__, read_error, yaml_path, suffix_note))
        raise CookieWriteVerificationError(
            "写回后回读不一致: 期望 %s，实际 %s（%s）%s"
            % (_fingerprint(cookie_str), _fingerprint(actual), yaml_path, suffix_note))
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
