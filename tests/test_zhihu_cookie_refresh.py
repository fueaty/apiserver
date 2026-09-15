#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
知乎 Cookie 工具的行为级离线测试（Task：Cookie 免人工续期）—— 无外网、无浏览器。

为什么必须是行为级
------------------
`write_cookie_auth` 是整个工具里唯一会**改写生产凭据文件**的函数，它最危险的失效形态不是
"崩了"，而是**静默改坏**：多改了一行、把 CRLF 洗成 LF、auth 行出现两条却随手挑了第一条、
或者根本没写成功却报成功。这类失效用"文本锁"（断言源码里出现过某函数名）完全测不出来，
所以本文件用「临时副本 + 逐字节比对 + 打桩自证」三层行为断言来守。

本文件同时锁住三件容易退化的接线：
  [A] 写入守卫真的会**拒绝**：auth 行 0 条 / 2 条 / 回读不一致，三种都必须抛。
  [B] 告警只在**状态变化**时发：首次失败发一次、连续同样失败不发、恢复时发一次。
  [C] 退出码与 HTTP 语义绑定：401 → 2 且告警；200 + 非空 data → 0 且**不**告警。

打桩自证（关键）
----------------
[6] 有一条"回读不一致必须抛"的用例。为了证明它**不是永远绿的废断言**，同组里给了两个对照：
     · 不打桩时同一调用成功（说明 raise 不是别的原因造成的）；
     · 打桩返回**正确**值时不抛（说明被鉴别的是"不一致"本身）。
另外 [1] 断言导入本工具没有把 playwright / app.wework.notification_push 拉进 sys.modules。

凭据卫生
--------
本文件使用真实 config/zhihu.yaml 的**临时副本**（字节复制）来测写回保真度，但：
  · 任何断言 detail 都不含该文件内容，只含行号 / md5 / 长度；
  · 结构性变体（缺 auth、auth 两条、回读不一致）一律基于**脱敏文本**构造；
  · 末尾断言真实 config/zhihu.yaml 的 md5 与测试开始时完全一致。

    python tests/test_zhihu_cookie_refresh.py     # 期望 RC=0
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

REAL_YAML = os.path.join(ROOT, "config", "zhihu.yaml")
REAL_MD5_AT_IMPORT = None

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [OK] %s" % name)
    else:
        # 带上**调用点行号**：变异验证时要能直接报出「是哪个测试的哪一行抓到的」。
        where = "%s:%d" % (os.path.basename(__file__), sys._getframe(1).f_lineno)
        FAILED.append("%s :: %s @ %s" % (name, detail, where))
        print("  [FAIL] %s  %s  @ %s" % (name, detail, where))


def _expect_raises(name, exc_type, fn):
    # 记下**调用点**行号：helper 内部抛错时，check 记到的是本函数这一行，
    # 变异验证要的是「哪个用例的哪一行把这个变异抓住了」，所以把调用点也带进 detail。
    caller = "%s:%d" % (os.path.basename(__file__), sys._getframe(1).f_lineno)
    try:
        fn()
    except exc_type:
        check(name, True)
        return True
    except Exception as e:
        check(name, False, "抛了非预期异常 %s: %s（期望 %s，用例调用点 %s）"
              % (type(e).__name__, e, exc_type.__name__, caller))
        return False
    check(name, False, "未抛出任何异常（守卫失效，用例调用点 %s）" % caller)
    return False


# ---------------------------------------------------------------------------
# 被测模块加载
# ---------------------------------------------------------------------------
# cookie_store 走**包导入**：tool 内部也是 `from app.services.collection import cookie_store`，
# 两边必须拿到同一个模块对象，否则 [6] 的 monkeypatch 打不到 tool 用的那份。
from app.services.collection import cookie_store  # noqa: E402


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "zhihu_cookie_tool_under_test", os.path.join(ROOT, "script", "zhihu_cookie_tool.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["zhihu_cookie_tool_under_test"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

if os.path.exists(REAL_YAML):
    with open(REAL_YAML, "rb") as _f:
        REAL_MD5_AT_IMPORT = hashlib.md5(_f.read()).hexdigest()


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _lines(path):
    with open(path, "rb") as f:
        return f.read().splitlines(keepends=True)


def _workdir():
    return tempfile.mkdtemp(prefix="zhihu_cookie_test_")


def _copy_real(tmpdir, name="zhihu.yaml"):
    """真实配置的**字节副本**（含实时凭据，但只落在系统临时目录里）。"""
    dst = os.path.join(tmpdir, name)
    shutil.copyfile(REAL_YAML, dst)
    return dst


def _sanitized_real_text():
    """真实配置的文本，但 cookie.auth 的值替换为占位符 —— 构造结构变体时用。"""
    with open(REAL_YAML, "rb") as f:
        text = f.read().decode("utf-8")
    return re.sub(r"(?m)^([ \t]*auth[ \t]*:).*$", r'\1 "DUMMY_COOKIE"', text)


def _write_text(path, text, newline="\n"):
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)
    return path


NEW_COOKIE = "z_c0=2|1:0|10:9999999999|4:z_c0|92:NEWVALUE=|deadbeef; _xsrf=NEW=="

TRICKY_COOKIE = ("z_c0=2|1:0|10:1000000000|4:z_c0|92:EXAMPLEBASE64=|deadbeefcafe; "
                 "_xsrf=AbCd+Ef/Gh==; d_c0=a|1:0|10:1000000000|x=1; "
                 "q_c1=abc=def:ghi/jkl+mno; empty_slot=; ; sessionid=s%3Axy.z")


# ---------------------------------------------------------------------------
# [0] 导入期无副作用
# ---------------------------------------------------------------------------
def test_import_side_effects():
    print("\n[0] 导入期无副作用（--check 环境没有 playwright / aiohttp）")
    playwright_mods = [m for m in sys.modules if m == "playwright" or m.startswith("playwright.")]
    check("[0] 导入 tool / cookie_store 后 sys.modules 无 playwright", playwright_mods == [],
          "modules=%r" % (playwright_mods,))
    check("[0] 导入期未拉入 app.wework.notification_push（aiohttp 依赖）",
          "app.wework.notification_push" not in sys.modules, "已被导入")
    check("[0] 真实 config/zhihu.yaml 存在（写回保真度用例的前提）", os.path.exists(REAL_YAML), REAL_YAML)


# ---------------------------------------------------------------------------
# [1] parse / format
# ---------------------------------------------------------------------------
def test_parse_format():
    print("\n[1] parse_cookie_header / format_cookie_header")
    parsed = cookie_store.parse_cookie_header(TRICKY_COOKIE)

    check("[1] parse: z_c0 值原样保留（含 | :）",
          parsed.get("z_c0") == "2|1:0|10:1000000000|4:z_c0|92:EXAMPLEBASE64=|deadbeefcafe",
          "len=%d" % len(parsed.get("z_c0") or ""))
    check("[1] parse: 值里的 + / = 不被 mangle",
          parsed.get("_xsrf") == "AbCd+Ef/Gh==", repr(parsed.get("_xsrf")))
    check("[1] parse: 只按**第一个** = 切分",
          parsed.get("q_c1") == "abc=def:ghi/jkl+mno", repr(parsed.get("q_c1")))
    check("[1] parse: 值里的小写 | 与 = 混排完整保留",
          parsed.get("d_c0") == "a|1:0|10:1000000000|x=1", repr(parsed.get("d_c0")))
    check("[1] parse: 段数 == 6（空段被忽略）", len(parsed) == 6, "n=%d keys=%s" % (len(parsed), sorted(parsed)))
    check("[1] parse: 空值段保留为空串值", parsed.get("empty_slot") == "", repr(parsed.get("empty_slot")))

    check("[1] parse: 中间空段被忽略",
          cookie_store.parse_cookie_header("a=1; ;  ; b=2") == {"a": "1", "b": "2"}, "")
    check("[1] parse: 无 = 的段被忽略",
          cookie_store.parse_cookie_header("a=1; junk; b=2") == {"a": "1", "b": "2"}, "")
    check("[1] parse: 值内空格保留",
          cookie_store.parse_cookie_header("k=a b c") == {"k": "a b c"}, "")
    check("[1] parse: 空输入返回空 dict",
          cookie_store.parse_cookie_header("") == {} and cookie_store.parse_cookie_header(None) == {}, "")

    check("[1] format(list): 保持浏览器顺序（不排序）",
          cookie_store.format_cookie_header([{"name": "b", "value": "2"}, {"name": "a", "value": "1"}]) == "b=2; a=1",
          repr(cookie_store.format_cookie_header([{"name": "b", "value": "2"}, {"name": "a", "value": "1"}])))
    check("[1] format(dict): 按键排序（确定性）",
          cookie_store.format_cookie_header({"b": "2", "a": "1"}) == "a=1; b=2", "")
    check("[1] format: 非 list/dict 输入抛 TypeError", _type_error_fires(), "")

    round_trip = cookie_store.format_cookie_header(cookie_store.parse_cookie_header(TRICKY_COOKIE))
    check("[1] round-trip: parse→format→parse 等价", cookie_store.parse_cookie_header(round_trip) == parsed, "")
    check("[1] round-trip: 段数仍为 6", len(round_trip.split("; ")) == 6, "segments=%d" % len(round_trip.split("; ")))
    sorted_header = "a=1; b=2; c=3"
    check("[1] round-trip: 已排序头的 parse→format 逐字节还原（真·round-trip）",
          cookie_store.format_cookie_header(cookie_store.parse_cookie_header(sorted_header)) == sorted_header, "")
    check("[1] parse 返回 dict，故未排序头经 format 会**按键归一化排序**（设计如此，非丢数据）",
          cookie_store.format_cookie_header(cookie_store.parse_cookie_header("z=1; a=2")) == "a=2; z=1", "")


def _type_error_fires():
    try:
        cookie_store.format_cookie_header(12345)
    except TypeError:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# [2] write_cookie_auth：只改 auth 行
# ---------------------------------------------------------------------------
def test_write_only_auth_line():
    print("\n[2] write_cookie_auth：只改 auth 行，其余字节不变")
    tmp = _workdir()
    path = _copy_real(tmp)
    before = open(path, "rb").read()
    before_lines = _lines(path)
    before_auth = cookie_store.read_cookie_auth(path)

    cookie_store.write_cookie_auth(path, NEW_COOKIE)

    after = open(path, "rb").read()
    after_lines = _lines(path)

    check("[2] 回读 cookie.auth == 写入值", cookie_store.read_cookie_auth(path) == NEW_COOKIE, "")
    check("[2] 行数不变", len(before_lines) == len(after_lines),
          "%d → %d" % (len(before_lines), len(after_lines)))

    changed = [i for i in range(min(len(before_lines), len(after_lines))) if before_lines[i] != after_lines[i]]
    check("[2] **恰好 1 行**发生变化", len(changed) == 1, "changed=%r" % (changed,))
    if len(changed) == 1:
        idx = changed[0]
        check("[2] 变化的是第 12 行（0 基 index=11）的 auth 行", idx == 11, "idx=%d（共 %d 行）" % (idx, len(before_lines)))
        check("[2] 该行前缀 `  auth: ` 保持不变",
              after_lines[idx].startswith(b"  auth: "), repr(after_lines[idx][:16]))

    others_same = all(before_lines[i] == after_lines[i]
                      for i in range(len(before_lines)) if i not in changed)
    check("[2] 其余每一行逐字节一致（注释/键序/空行/缩进/其它键）", others_same, "")

    import yaml
    before_doc = yaml.safe_load(before.decode("utf-8"))
    after_doc = yaml.safe_load(after.decode("utf-8"))
    before_doc["cookie"]["auth"] = after_doc["cookie"]["auth"]
    check("[2] yaml 语义：除 cookie.auth 外完全一致", before_doc == after_doc, "")
    check("[2] 其它关键键仍在且未变",
          after_doc["cookie"].get("z_c0") == before_doc_original("cookie", "z_c0")
          and "authorization" in after_doc and "collection" in after_doc, "")
    check("[2] 写入值与原值不同（证明确实改了东西）", before_auth != NEW_COOKIE, "")

    # 行内注释与引号尾巴必须保留
    annotated = _write_text(os.path.join(tmp, "annotated.yaml"),
                            'cookie:\n  auth: "old"  # 保留这条注释\napi:\n  base_url: "x"\n')
    cookie_store.write_cookie_auth(annotated, NEW_COOKIE)
    check("[2] auth 行行内注释被保留",
          b"# \xe4\xbf\x9d\xe7\x95\x99" in open(annotated, "rb").read()
          and cookie_store.read_cookie_auth(annotated) == NEW_COOKIE, "")


def before_doc_original(section, key):
    import yaml
    with open(REAL_YAML, "rb") as f:
        return yaml.safe_load(f.read().decode("utf-8"))[section][key]


# ---------------------------------------------------------------------------
# [3] EOL 约定
# ---------------------------------------------------------------------------
def test_eol_preserved():
    print("\n[3] write_cookie_auth：保留文件原有换行约定")
    tmp = _workdir()

    lf_path = _copy_real(tmp, "lf.yaml")
    lf_before = open(lf_path, "rb").read()
    check("[3] 前置：真实副本为纯 LF（无 CRLF）", b"\r\n" not in lf_before, "")
    cookie_store.write_cookie_auth(lf_path, NEW_COOKIE)
    lf_after = open(lf_path, "rb").read()
    check("[3] LF 文件写回后仍无 CRLF", b"\r\n" not in lf_after, "")
    check("[3] LF 计数不变", lf_after.count(b"\n") == lf_before.count(b"\n"),
          "%d → %d" % (lf_before.count(b"\n"), lf_after.count(b"\n")))

    crlf_path = os.path.join(tmp, "crlf.yaml")
    with open(crlf_path, "wb") as f:
        f.write(lf_before.replace(b"\n", b"\r\n"))
    crlf_before = open(crlf_path, "rb").read()
    check("[3] 前置：CRLF 副本构造成功", crlf_before.count(b"\r\n") == lf_before.count(b"\n"), "")
    cookie_store.write_cookie_auth(crlf_path, NEW_COOKIE)
    crlf_after = open(crlf_path, "rb").read()
    check("[3] CRLF 文件写回后 CRLF 计数不变",
          crlf_after.count(b"\r\n") == crlf_before.count(b"\r\n"),
          "%d → %d" % (crlf_before.count(b"\r\n"), crlf_after.count(b"\r\n")))
    check("[3] CRLF 文件写回后没有裸 LF（未被洗成 LF）",
          crlf_after.count(b"\n") == crlf_after.count(b"\r\n"), "")
    check("[3] CRLF 文件回读值正确",
          cookie_store.read_cookie_auth(crlf_path) == NEW_COOKIE, "")


# ---------------------------------------------------------------------------
# [4] 幂等
# ---------------------------------------------------------------------------
def test_idempotent():
    print("\n[4] write_cookie_auth：幂等")
    tmp = _workdir()
    path = _copy_real(tmp)
    cookie_store.write_cookie_auth(path, NEW_COOKIE)
    first = _md5(path)
    cookie_store.write_cookie_auth(path, NEW_COOKIE)
    second = _md5(path)
    check("[4] 同值连写两次 → 文件字节完全一致", first == second, "%s vs %s" % (first, second))
    check("[4] 备份路径参数可用且不改变目标文件语义",
          _backup_works(tmp), "")


def _backup_works(tmp):
    src = _copy_real(tmp, "bak_src.yaml")
    backup = os.path.join(tmp, "nested", "zhihu.yaml.bak")
    cookie_store.write_cookie_auth(src, NEW_COOKIE, backup_path=backup)
    return os.path.exists(backup) and cookie_store.read_cookie_auth(src) == NEW_COOKIE


# ---------------------------------------------------------------------------
# [5] 守卫必须拒绝：auth 行 0 条 / 2 条
# ---------------------------------------------------------------------------
def _expect_rejects_without_touching(label, path, fn):
    """前置校验失败必须同时满足：① 抛 CookieWriteError；② **一个字节都不写**。

    ② 才是「不猜改哪一条」这条守卫的独立鉴别点，只断言 ① 会漏掉一种假实现：
    先闷头改第一条 auth 行、再靠**写后回读**把不一致兜回来 —— PyYAML 接受重复键
    （后者胜出），所以回读必然不等 ⇒ 也抛 CookieWriteError，测试全绿，但
    「auth 行必须唯一」实际上已经失效。变异 M1 就是靠 ② 才被检出。
    """
    before = open(path, "rb").read()
    _expect_raises(label, cookie_store.CookieWriteError, fn)
    check(label + "｜且该文件一个字节都没动", open(path, "rb").read() == before,
          "文件被改动了 → 前置唯一性校验形同虚设")


def _dup_key_last_wins(path):
    """自证：文件里有多条 ``auth:`` 行时，``yaml.safe_load`` **不报错**（静默取最后一条）。

    这正是"只断言抛错的用例可以被回读守卫顶替"的根因；把这条场景事实也钉住，
    以后若换成严格 YAML 解析器（重复键报错），本用例会提醒你回来看唯一的鉴别点。
    """
    import yaml
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    if len(re.findall(r"(?m)^[ \t]*auth[ \t]*:", text)) < 2:
        return False
    try:
        loaded = yaml.safe_load(text)["cookie"]["auth"]
    except Exception:
        return False
    return bool(loaded)


def test_guard_rejects():
    print("\n[5] write_cookie_auth：结构守卫（0 条 / 2 条 auth）必须拒绝")
    tmp = _workdir()

    missing = _write_text(os.path.join(tmp, "no_auth.yaml"),
                          "cookie:\n  z_c0: \"x\"\n  _xsrf: \"y\"\napi:\n  base_url: \"https://www.zhihu.com\"\n")
    _expect_rejects_without_touching(
        "[5] cookie 段内 0 条 auth: → 拒绝",
        missing, lambda: cookie_store.write_cookie_auth(missing, NEW_COOKIE))
    _expect_raises("[5] 同文件 read_cookie_auth 也抛 CookieConfigError",
                   cookie_store.CookieConfigError,
                   lambda: cookie_store.read_cookie_auth(missing))

    sanitized = _sanitized_real_text()
    duplicated = sanitized.replace('  auth: "DUMMY_COOKIE"',
                                   '  auth: "DUMMY_COOKIE"\n  auth: "DUMMY_COOKIE_2"')
    dup_path = _write_text(os.path.join(tmp, "dup_auth.yaml"), duplicated)
    _expect_rejects_without_touching(
        "[5] cookie 段内 2 条 auth: → 拒绝（不猜改哪条）",
        dup_path, lambda: cookie_store.write_cookie_auth(dup_path, NEW_COOKIE))
    check("[5] 场景自证：重复副本确实含 2 条 auth 行",
          duplicated.count('auth: "DUMMY') == 2, "n=%d" % duplicated.count('auth: "DUMMY'))
    check("[5] 场景自证：重复键被 PyYAML 静默接受（后者胜出）——这正是回读守卫会顶替唯一性守卫的原因",
          _dup_key_last_wins(dup_path), "")

    outside = _write_text(os.path.join(tmp, "outside.yaml"),
                          "cookie:\n  z_c0: \"x\"\nother:\n  auth: \"not-inside-cookie\"\n")
    _expect_rejects_without_touching(
        "[5] auth: 在 cookie 段之外 → 视为 0 条并拒绝",
        outside, lambda: cookie_store.write_cookie_auth(outside, NEW_COOKIE))

    empty = _write_text(os.path.join(tmp, "empty_auth.yaml"), 'cookie:\n  auth: ""\n')
    _expect_raises("[5] 写入空串 → 拒绝",
                   cookie_store.CookieWriteError,
                   lambda: cookie_store.write_cookie_auth(empty, "   "))
    _expect_raises("[5] 值里带换行（头注入）→ 拒绝",
                   cookie_store.CookieWriteError,
                   lambda: cookie_store.write_cookie_auth(empty, "a=1\r\nX-Evil: 1"))
    # D4 cs:235 头注入守卫：**裸 CR**（不含 LF）也必须拒绝。
    # 只测 "\r\n" 的用例挡不住「把守卫弱化成只查 \n」——python3 里裸 CR 一样能构造头注入，
    # 且 PyYAML 对裸 CR 的处理与 LF 不同。这条钉住「\r 与 \n 都要查」。
    _expect_rejects_without_touching(
        "[5] D4 cs:235 值里带裸 CR（无 LF）→ 拒绝且不动文件",
        empty, lambda: cookie_store.write_cookie_auth(empty, "a=1\rX-Evil: 1"))
    _expect_rejects_without_touching(
        "[5] D4 cs:235 值里带裸 LF → 拒绝且不动文件",
        empty, lambda: cookie_store.write_cookie_auth(empty, "a=1\nX-Evil: 1"))
    # 上面两条只钉住「结果」，挡不住「把 \r 那半拿掉、靠别的守卫兜回来」的实现
    # （写回后的换行计数校验同样会拒）。这一条钉的是**守卫本身在不在**：
    # 给一个**不存在**的目标路径，若头注入守卫在，就在碰磁盘之前先抛 CookieWriteError；
    # 若 \r 被放行，就会先去 open() 那个不存在的文件 → 抛 CookieConfigError（原因就不是注入了）。
    _expect_raises("[5] D4 cs:235 裸 CR 必须在**碰磁盘之前**就被拒（不依赖文件内容/其它守卫）",
                   cookie_store.CookieWriteError,
                   lambda: cookie_store.write_cookie_auth(
                       os.path.join(tmp, "never_created.yaml"), "a=1\rX-Evil: 1"))


# ---------------------------------------------------------------------------
# [6] 回读校验必须真的会触发（含打桩自证）
# ---------------------------------------------------------------------------
def test_readback_verification():
    print("\n[6] write_cookie_auth：回读校验必须真的会触发")
    tmp = _workdir()
    target = _copy_real(tmp)
    real_read = cookie_store.read_cookie_auth

    calls = {"n": 0}

    def lying_read(_path):
        calls["n"] += 1
        return "TAMPERED-NOT-WHAT-WE-WROTE"

    raised = False
    cookie_store.read_cookie_auth = lying_read
    try:
        cookie_store.write_cookie_auth(target, NEW_COOKIE)
    except cookie_store.CookieWriteVerificationError:
        raised = True
    except Exception as e:
        check("[6] 回读不一致抛的是 CookieWriteVerificationError",
              False, "实际抛出 %s: %s" % (type(e).__name__, e))
    finally:
        cookie_store.read_cookie_auth = real_read

    check("[6] 回读不一致 → 抛 CookieWriteVerificationError", raised, "未抛出（守卫失效）")
    check("[6] 回读确实被调用过（证明校验路径真的走到）", calls["n"] >= 1, "calls=%d" % calls["n"])

    # 对照 1：不打桩时同一调用成功 —— 证明上面的 raise 不是别的原因（如结构守卫）造成的
    control = _copy_real(tmp, "control.yaml")
    ok = True
    try:
        cookie_store.write_cookie_auth(control, NEW_COOKIE)
    except Exception as e:
        ok = False
        print("     对照异常: %s: %s" % (type(e).__name__, e))
    check("[6] 对照：不打桩时同一调用成功（raise 确由『不一致』引起）", ok, "")
    check("[6] 对照：该文件回读值正确", cookie_store.read_cookie_auth(control) == NEW_COOKIE, "")

    # 对照 2：打桩返回**正确**值 → 不抛 —— 证明被鉴别的是"不一致"本身，不是"打了桩"
    target2 = _copy_real(tmp, "target2.yaml")
    ok2 = True
    cookie_store.read_cookie_auth = lambda _p: NEW_COOKIE
    try:
        cookie_store.write_cookie_auth(target2, NEW_COOKIE)
    except Exception as e:
        ok2 = False
        print("     对照2异常: %s: %s" % (type(e).__name__, e))
    finally:
        cookie_store.read_cookie_auth = real_read
    check("[6] 对照：打桩返回正确值 → 不抛（鉴别的是不一致本身）", ok2, "")


# ---------------------------------------------------------------------------
# HTTP / 通知替身
# ---------------------------------------------------------------------------
class _FakeFetcher(object):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        self.calls = 0
        self.last_cookie = None

    def __call__(self, url, cookie, timeout=10):
        self.calls += 1
        self.last_cookie = cookie
        return self.status, self.body


class _Recorder(object):
    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)


class _ScriptedFetcher(object):
    """按调用次序返回预设的 (status, body)；用尽后重复最后一个（便于跑同一段序列）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url, cookie, timeout=10):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


class _FlakyNotifier(object):
    """可切换「投递失败 / 投递成功」的 notifier，记录**每一次尝试**与**每一条真正送达**的文案。

    attempts 与 delivered 必须分开看：两次都算「尝试」，只有 working=True 那次算「送达」。
    「恰好一次」这条断言正是建立在这个区分上的（尝试可以 >1，送达必须 ==1）。
    """

    def __init__(self, working=False):
        self.working = working
        self.attempts = 0
        self.delivered = []

    def __call__(self, message):
        self.attempts += 1
        if not self.working:
            raise RuntimeError("wecom webhook 不可用（注入的确定性失败）")
        self.delivered.append(message)


BODY_CODE_101 = json.dumps({"code": 101, "name": "AuthenticationError",
                            "message": "\u8eab\u4efd\u672a\u7ecf\u8fc7\u9a8c\u8bc1"}, ensure_ascii=False)
BODY_CODE_100 = json.dumps({"code": 100, "name": "AuthenticationInvalidRequest",
                            "message": "ERR_LOGIN_TICKET_EXPIRED"}, ensure_ascii=False)


def _ok_body(n=3):
    return json.dumps({"data": [{"target": {"title": "\u70ed\u699c\u6807\u9898%d" % i, "id": i}}
                                for i in range(1, n + 1)]}, ensure_ascii=False)


def _check_catching(**kwargs):
    """调用 tool.check，把「抛未捕获异常」变成一个可断言的信号，返回 (rc, crash)。

    D1 的原始失效形态就是「异常逃出 check()」：测试若直接调用，traceback 会打断整套用例，
    只能算 subprocess crash —— 那不是真正的行为级检出。包成返回值后，「不抛异常」就变成
    一条普通断言，能出现在 fail 列表里、并带上下面的行号。
    """
    try:
        return tool.check(**kwargs), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _check_catching_base(**kwargs):
    """同 `_check_catching`，但**连 BaseException 一起**收敛成返回值。

    G4 的场景是 notifier 抛 SystemExit：它必须照常逃出 check()（我们刻意不 catch
    BaseException），所以只有把 BaseException 也接住，才能既断言「确实逃出去了」，
    又让用例继续跑下去断言「状态里的 alert_pending 已落盘」。
    """
    try:
        return tool.check(**kwargs), None
    except BaseException as e:  # noqa: BLE001  被测的就是「SystemExit 不被吞掉」
        return None, "%s: %s" % (type(e).__name__, e)


def _call_catching(fn, *args, **kwargs):
    """把任意直接调用点的「抛未捕获异常」收敛成可断言的 (result, crash)。

    理由同 `_check_catching`，但用在 tool.apply_refreshed_cookie 这类**非 check** 的
    用法点上：G3 说 tool:571 那次 _write_back 被去掉时，原来只会让
    CookieWriteVerificationError 逃出用例把整个 runner 崩掉（= (b) subprocess crash），
    那不是行为级检出。改成返回值后它是一条普通 [FAIL]，带行号。
    """
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _read_auth_catching(path):
    """读 cookie.auth，把异常收敛成 (value, crash)；理由同 `_read_json`。"""
    try:
        return cookie_store.read_cookie_auth(path), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _cfg_and_state(tmp, name="zhihu.yaml"):
    cfg = _write_text(os.path.join(tmp, name), _sanitized_real_text())
    return cfg, os.path.join(tmp, "state_%s.json" % name)


def _read_json(path):
    """读 JSON，**不抛异常**：把「不存在 / 读不动 / JSON 坏」变成可断言的 (data, err)。

    变异验证时的关键差别：若断言写成 `json.load(open(state, ...))`，那么「注入的 state_path
    被丢弃」这个变异会让文件不存在 → FileNotFoundError → **subprocess crash**（还算不上
    behavior 检出，且取决于运行环境的路径是否凑巧存在）。改成返回 (data, err) 后，同一个
    变异变成一条普通的 [FAIL] 断言，带上下面的行号。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), ""
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _read_text(path):
    """读文本，**不抛异常**；理由同 `_read_json`。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), ""
    except Exception as e:
        return "", "%s: %s" % (type(e).__name__, e)


def _state_field(path, field):
    """读状态文件的某个字段，返回 (value, err)；文件缺失/坏掉时 err 非空、value 为 None。"""
    data, err = _read_json(path)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "状态文件顶层不是对象: %r" % (data,)
    return data.get(field), ""


def _assert_state(name, path, field, expected):
    """断言「注入的 state_path 上确实写成了期望值」——落盘位置与内容一起被锁住。"""
    value, err = _state_field(path, field)
    check(name, err == "" and value == expected,
          "path=%s %s=%r（期望 %r）err=%s" % (path, field, value, expected, err or "-"))
    return value


# ---------------------------------------------------------------------------
# [7] 仅在状态变化时告警
# ---------------------------------------------------------------------------
def test_notify_only_on_state_change():
    print("\n[7] 仅在状态变化时告警（auth_failed 首次告警 / 连续不重发 / 恢复告警）")
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp)
    recorder = _Recorder()

    rc1 = tool.check(config_path=cfg, state_path=state,
                     fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=recorder)
    check("[7] 首次 401(code=100) → rc==2", rc1 == 2, "rc=%r" % (rc1,))
    check("[7] 首次失败 → 告警恰好 1 次", len(recorder.messages) == 1, "n=%d" % len(recorder.messages))
    if recorder.messages:
        msg = recorder.messages[0]
        check("[7] 告警含站点名 zhihu", "zhihu" in msg, msg)
        check("[7] 告警含 code=100", "100" in msg, msg)
        check("[7] 告警含人工动作 --login", "--login" in msg, msg)
        check("[7] 告警不含 cookie 明文",
              "DUMMY_COOKIE" not in msg and "z_c0=" not in msg, msg)
    _assert_state("[7] 状态文件已写入且 status=auth_failed", state, "status", "auth_failed")
    raw_state, raw_err = _read_text(state)
    check("[7] 状态文件不含 cookie 明文",
          raw_err == "" and "DUMMY_COOKIE" not in raw_state and "z_c0=" not in raw_state, raw_err)

    rc2 = tool.check(config_path=cfg, state_path=state,
                     fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=recorder)
    check("[7] 连续第二次同样失败 → rc==2", rc2 == 2, "rc=%r" % (rc2,))
    check("[7] 连续同样失败 → **不重复告警**（仍 1 次）", len(recorder.messages) == 1,
          "n=%d" % len(recorder.messages))

    rc3 = tool.check(config_path=cfg, state_path=state,
                     fetcher=_FakeFetcher(200, _ok_body()), notifier=recorder)
    check("[7] 恢复为 200 → rc==0", rc3 == 0, "rc=%r" % (rc3,))
    check("[7] 恢复 → 发出恢复通知（累计 2 次）", len(recorder.messages) == 2,
          "n=%d" % len(recorder.messages))
    if len(recorder.messages) == 2:
        check("[7] 恢复通知说明无需人工介入",
              "恢复" in recorder.messages[1] or "--refresh" in recorder.messages[1],
              recorder.messages[1])

    rc4 = tool.check(config_path=cfg, state_path=state,
                     fetcher=_FakeFetcher(200, _ok_body()), notifier=recorder)
    check("[7] 恢复后再次 OK → 不重复发恢复通知（仍 2 次）", len(recorder.messages) == 2,
          "n=%d" % len(recorder.messages))
    check("[7] 恢复后 rc 仍为 0", rc4 == 0, "rc=%r" % (rc4,))


# ---------------------------------------------------------------------------
# [8][9] 401 → rc2 + 告警；200 → rc0 + 不告警
# ---------------------------------------------------------------------------
def test_exit_codes_and_notify():
    print("\n[8] 负向：401 → rc==2 且告警一次")
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "auth101.yaml")
    recorder = _Recorder()
    fetcher = _FakeFetcher(401, BODY_CODE_101)
    rc = tool.check(config_path=cfg, state_path=state, fetcher=fetcher, notifier=recorder)
    check("[8] HTTP 401 / code=101 → rc==2", rc == 2, "rc=%r" % (rc,))
    check("[8] 401 → 告警被调用（1 次）", len(recorder.messages) == 1, "n=%d" % len(recorder.messages))
    if recorder.messages:
        check("[8] code=101 告警标注『无凭证/未识别』", "无凭证" in recorder.messages[0],
              recorder.messages[0])
    check("[8] fetcher 确实被调用且收到配置里的 cookie",
          fetcher.calls == 1 and fetcher.last_cookie == "DUMMY_COOKIE",
          "calls=%d cookie=%r" % (fetcher.calls, fetcher.last_cookie))

    print("\n[9] 正向：200 + 非空 data → rc==0 且**不**告警")
    tmp2 = _workdir()
    cfg2, state2 = _cfg_and_state(tmp2, "ok.yaml")
    recorder2 = _Recorder()
    fetcher2 = _FakeFetcher(200, _ok_body())
    rc2 = tool.check(config_path=cfg2, state_path=state2, fetcher=fetcher2, notifier=recorder2)
    check("[9] 200 + 非空 data → rc==0", rc2 == 0, "rc=%r" % (rc2,))
    check("[9] 正常态 → **不告警**", recorder2.messages == [], "n=%d" % len(recorder2.messages))
    _assert_state("[9] 状态文件 status=ok", state2, "status", "ok")

    # 200 但 data 为空 / body 不可解析 → rc==3（不是 0）
    for label, body in (("data 为空列表", json.dumps({"data": []})),
                        ("body 非 JSON", "<html>not json</html>")):
        tmp3 = _workdir()
        cfg3, state3 = _cfg_and_state(tmp3, "bad.yaml")
        rec3 = _Recorder()
        rc3 = tool.check(config_path=cfg3, state_path=state3,
                         fetcher=_FakeFetcher(200, body), notifier=rec3)
        check("[9] 200 但 %s → rc==3（不误判为可用）" % label, rc3 == 3, "rc=%r" % (rc3,))
        check("[9] 200 但 %s → 不发认证告警" % label, rec3.messages == [], "")


# ---------------------------------------------------------------------------
# [10] 传输错误 → rc3，且不误判为认证失败
# ---------------------------------------------------------------------------
def test_transport_error():
    print("\n[10] 传输错误 → rc==3 且不误判为认证失败")
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "transport.yaml")
    recorder = _Recorder()

    def boom(_url, _cookie, timeout=10):
        raise tool.TransportError("connection refused")

    rc = tool.check(config_path=cfg, state_path=state, fetcher=boom, notifier=recorder)
    check("[10] TransportError → rc==3", rc == 3, "rc=%r" % (rc,))
    check("[10] 传输错误不触发认证告警", recorder.messages == [], "n=%d" % len(recorder.messages))

    tmp2 = _workdir()
    cfg2, state2 = _cfg_and_state(tmp2, "nocfg.yaml")
    rc2 = tool.check(config_path=os.path.join(tmp2, "does_not_exist.yaml"),
                     state_path=state2, fetcher=_FakeFetcher(200, _ok_body()),
                     notifier=_Recorder())
    check("[10] 配置文件不存在 → rc==3", rc2 == 3, "rc=%r" % (rc2,))

    # 文件存在、YAML 合法，但**没有凭证** —— 这是 zhihu 站点最可能的生产失效形态
    # （读不到 cookie.auth ⇒ 一直 0 条入库且不报错）。必须 rc==2 且发告警，绝不能静默 rc==3。
    tmp3 = _workdir()
    no_auth_key = _write_text(os.path.join(tmp3, "no_auth_key.yaml"), 'cookie:\n  z_c0: ""\n')
    state3 = os.path.join(tmp3, "state.json")
    rec3, fetch3 = _Recorder(), _FakeFetcher(200, _ok_body())
    rc3 = tool.check(config_path=no_auth_key, state_path=state3, fetcher=fetch3, notifier=rec3)
    check("[10] 缺 cookie.auth 键 → rc==2（不是 3，不静默）", rc3 == 2, "rc=%r" % (rc3,))
    check("[10] 缺凭证 → 告警恰好 1 次且点名 --login",
          len(rec3.messages) == 1 and "--login" in rec3.messages[0],
          "n=%d" % len(rec3.messages))
    _assert_state("[10] 缺凭证 → 状态文件 status=auth_failed", state3, "status", "auth_failed")
    check("[10] 缺凭证 → 不去打网络（fetcher 未被调用）", fetch3.calls == 0,
          "calls=%d" % fetch3.calls)

    tmp4 = _workdir()
    blank = _write_text(os.path.join(tmp4, "blank.yaml"), 'cookie:\n  auth: ""\n')
    state4 = os.path.join(tmp4, "state.json")
    rec4 = _Recorder()
    rc4 = tool.check(config_path=blank, state_path=state4,
                     fetcher=_FakeFetcher(200, _ok_body()), notifier=rec4)
    check("[10] cookie.auth 为空串 → rc==2 且告警 1 次",
          rc4 == 2 and len(rec4.messages) == 1, "rc=%r n=%d" % (rc4, len(rec4.messages)))

    tmp5 = _workdir()
    broken = _write_text(os.path.join(tmp5, "broken.yaml"), "cookie:\n  auth: [unclosed\n")
    rc5 = tool.check(config_path=broken, state_path=os.path.join(tmp5, "s.json"),
                     fetcher=_FakeFetcher(200, _ok_body()), notifier=_Recorder())
    check("[10] YAML 语法坏 → rc==3（配置/运维问题，不 @all）", rc5 == 3, "rc=%r" % (rc5,))


# ---------------------------------------------------------------------------
# [11] --dry-run 不得落任何盘
# ---------------------------------------------------------------------------
def test_dry_run():
    print("\n[11] --dry-run：计算并打印，但不落盘 / 不发通知")
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "dry.yaml")
    recorder = _Recorder()
    rc = tool.check(config_path=cfg, state_path=state,
                    fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=recorder, dry_run=True)
    check("[11] dry-run 仍返回真实判定 rc==2", rc == 2, "rc=%r" % (rc,))
    check("[11] dry-run 不写状态文件", not os.path.exists(state), state)
    check("[11] dry-run 不发通知", recorder.messages == [], "n=%d" % len(recorder.messages))

    rc2 = tool.do_refresh(config_path=cfg, dry_run=True)
    check("[11] --refresh --dry-run 在无 playwright 环境干净退出 rc==3", rc2 == 3, "rc=%r" % (rc2,))
    rc3 = tool.do_login(config_path=cfg, dry_run=True)
    check("[11] --login --dry-run 在无 playwright 环境干净退出 rc==3", rc3 == 3, "rc=%r" % (rc3,))
    check("[11] 无 playwright 时未创建 runtime/ profile 目录",
          not os.path.exists(os.path.join(ROOT, "runtime", "zhihu_profile")), "")


# ---------------------------------------------------------------------------
# [12] 状态文件路径必须落在 git 忽略区
# ---------------------------------------------------------------------------
def test_state_path_ignored():
    print("\n[12] 状态文件路径必须被 .gitignore 覆盖")
    resolved = tool.resolve_state_path(None)
    check("[12] 默认状态文件路径取 logs/ 或 tmp/",
          resolved in (tool.DEFAULT_STATE, tool.FALLBACK_STATE), resolved)
    rel = os.path.relpath(resolved, ROOT).replace("\\", "/")
    check("[12] 该路径确实被 git 忽略（%s）" % rel, tool._git_ignored(rel) is True, rel)
    check("[12] runtime/ profile 目录也已被忽略（内含实时登录态）",
          tool._git_ignored("runtime/zhihu_profile/Cookies") is True, "runtime/zhihu_profile/Cookies")
    check("[12] write_cookie_auth 的原子落盘临时文件也被忽略（否则中途中断会残留实时凭据）",
          tool._git_ignored("config/zhihu.yaml.tmp") is True, "config/zhihu.yaml.tmp")


# ---------------------------------------------------------------------------
# [13] 真实配置未被测试污染
# ---------------------------------------------------------------------------
def test_real_config_untouched():
    print("\n[13] 真实 config/zhihu.yaml 未被测试改写")
    check("[13] md5 与测试开始时一致", _md5(REAL_YAML) == REAL_MD5_AT_IMPORT,
          "%s vs %s" % (REAL_MD5_AT_IMPORT, _md5(REAL_YAML)))
    check("[13] 行数仍为 46 行", len(_lines(REAL_YAML)) == 46, "n=%d" % len(_lines(REAL_YAML)))


# ---------------------------------------------------------------------------
# [14] --refresh 的写回判据（无需浏览器即可验证）
# ---------------------------------------------------------------------------
def test_refresh_write_decision():
    print("\n[14] --refresh 写回判据：只在真变化时落盘 + 写后复验")
    tmp = _workdir()
    cfg = _write_text(os.path.join(tmp, "refresh.yaml"), _sanitized_real_text())
    cookie_store.write_cookie_auth(cfg, NEW_COOKIE)  # 先让磁盘上就是 NEW_COOKIE
    before = open(cfg, "rb").read()

    wrote_same, crash_same = _call_catching(tool.apply_refreshed_cookie, cfg, NEW_COOKIE)
    check("[14] 串未变化 → 返回 False（跳过写回）",
          crash_same is None and wrote_same is False,
          "wrote=%r crash=%s" % (wrote_same, crash_same))
    check("[14] 串未变化 → 文件逐字节未动", open(cfg, "rb").read() == before, "")

    changed = NEW_COOKIE + "; extra=1"
    wrote_new, crash_new = _call_catching(tool.apply_refreshed_cookie, cfg, changed)
    check("[14] 串有变化 → 返回 True（已落盘）",
          crash_new is None and wrote_new is True,
          "wrote=%r crash=%s" % (wrote_new, crash_new))
    check("[14] 串有变化 → 回读即为新值", cookie_store.read_cookie_auth(cfg) == changed, "")
    check("[14] 串有变化 → 仍只改 auth 行（行数不变）",
          len(open(cfg, "rb").read().splitlines(keepends=True)) == len(before.splitlines(keepends=True)),
          "")

    # --- U2/G3：第二个 _write_back 用法点（tool:571，apply_refreshed_cookie 内部）---
    # 锁在**可观察的文件效果**上。把 tool:571 那次 `_write_back(...)` 去掉时，
    #   · 旧写法：外层的回读复验抛 CookieWriteVerificationError，逃出用例 ⇒ 整个 runner
    #     崩掉 = (b) subprocess crash（不算真正的行为级检出，而且会掩盖后面所有用例）；
    #   · 现在：经 `_call_catching` 收敛成返回值 ⇒ 普通的 [FAIL]，带调用点行号 = (a)。
    obs_cfg = _write_text(os.path.join(tmp, "writeback_obs.yaml"), _sanitized_real_text())
    obs_target = "u2|second-usage==point"
    obs_before = open(obs_cfg, "rb").read()
    obs_auth0, obs_crash0 = _read_auth_catching(obs_cfg)
    check("[14] 场景自证：目标串与磁盘现值不同（否则『文件变了』无从谈起）",
          obs_crash0 is None and obs_auth0 != obs_target, "crash=%s" % (obs_crash0 or "-"))

    obs_result, obs_crash = _call_catching(tool.apply_refreshed_cookie, obs_cfg, obs_target)
    check("[14] U2 tool:571 串有变化 → apply_refreshed_cookie 不抛异常且返回 True",
          obs_crash is None and obs_result is True,
          "result=%r crash=%s" % (obs_result, obs_crash))
    obs_after = open(obs_cfg, "rb").read()
    check("[14] U2 tool:571 可观察效果：目标文件**字节确实变了**", obs_after != obs_before,
          "字节未变 ⇒ tool:571 那次 _write_back 没发生")
    obs_auth, obs_read_crash = _read_auth_catching(obs_cfg)
    check("[14] U2 tool:571 可观察效果：回读 == 传入的新串",
          obs_read_crash is None and obs_auth == obs_target,
          "回读 %r crash=%s" % (obs_auth, obs_read_crash))

    dry_before = open(cfg, "rb").read()
    wrote_dry = tool.apply_refreshed_cookie(cfg, changed + "; dry=1", dry_run=True)
    check("[14] dry_run → 返回 False 且一个字节都没落盘",
          wrote_dry is False and open(cfg, "rb").read() == dry_before, "")
    check("[14] dry_run 后回读仍是原值", cookie_store.read_cookie_auth(cfg) == changed, "")

    # 内层守卫：write_cookie_auth 自己的回读校验（打桩让回读撒谎 → 必须抛）。
    # ⚠️ 这条拦下来的是**内层** write_cookie_auth 的守卫，不是 apply_refreshed_cookie 的：
    #    内层先抛，外层那行 `if readback != cookie_str` 根本走不到。所以它**不能**用来证明
    #    外层复验存在 —— 把外层复验删掉（变异 M8）这条依然全绿。外层的独立覆盖见下一段。
    real_read = cookie_store.read_cookie_auth
    raised = False
    cookie_store.read_cookie_auth = lambda _p: "TAMPERED"
    try:
        tool.apply_refreshed_cookie(cfg, "yet=another|value==x")
    except cookie_store.CookieWriteVerificationError:
        raised = True
    except Exception as e:
        check("[14] 内层回读校验不一致 → 抛 CookieWriteVerificationError", False,
              "实际抛出 %s: %s" % (type(e).__name__, e))
    finally:
        cookie_store.read_cookie_auth = real_read
    check("[14] 内层回读校验不一致 → 抛（内层守卫真的会拦，不是装饰）", raised, "未抛出（守卫失效）")

    # 外层复验：apply_refreshed_cookie 自己那行 `if readback != cookie_str` 必须真的会拦。
    # 关键是先把**内层** write_cookie_auth 的复验绕开（否则又是内层先抛），办法是把
    # `_write_back` 打桩成"什么都不写"：于是磁盘仍是旧值 ≠ 传入值，只有外层能拦。
    outer_target = "outer|guard==check"
    real_write_back = tool._write_back
    outer_raised = False
    tool._write_back = lambda _cfg, _cookie: None
    try:
        tool.apply_refreshed_cookie(cfg, outer_target)
    except cookie_store.CookieWriteVerificationError:
        outer_raised = True
    except Exception as e:
        check("[14] 外层复验不一致 → 抛 CookieWriteVerificationError", False,
              "实际抛出 %s: %s" % (type(e).__name__, e))
    finally:
        tool._write_back = real_write_back
    check("[14] 场景自证：内层被绕开后磁盘值确实 != 传入值（外层才有机会拦）",
          cookie_store.read_cookie_auth(cfg) != outer_target, "")
    check("[14] 外层复验不一致 → 抛（绕开内层后外层仍会拦，不是装饰）", outer_raised,
          "未抛出（外层复验是装饰 → 变异 M8 会存活）")


# ---------------------------------------------------------------------------
# [15] --login / --refresh 的就地 check 可注入（离线验证告警路径）
# ---------------------------------------------------------------------------
def test_login_refresh_alert_path_offline():
    print("\n[15] --refresh / --login 的就地 check 可注入（离线验证告警路径）")
    tmp = _workdir()
    cfg = _write_text(os.path.join(tmp, "flow.yaml"), _sanitized_real_text())
    state = os.path.join(tmp, "state.json")

    real_browser = tool._browser_cookie_string
    fake_browser = lambda headless, timeout_s, settle_ms: (NEW_COOKIE, "")  # noqa: E731
    try:
        tool._browser_cookie_string = fake_browser
        rec = _Recorder()
        rc = tool.do_refresh(config_path=cfg, state_path=state,
                             fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=rec)
    finally:
        tool._browser_cookie_string = real_browser

    check("[15] --refresh 拿到 cookie 且校验 401 → rc==2", rc == 2, "rc=%r" % (rc,))
    # 断言「注入的 notifier 收到了什么」而不是「没崩」：把 notifier 在透传链上弄丢
    # （do_refresh → check）会让真实企微通道被尝试，在有 aiohttp 的机器上就是一次真外呼；
    # 这里锁住**调用次数 + 文案内容**，丢掉注入就一定是一条断言失败。
    check("[15] --refresh 的失败走了**注入的** notifier（恰好 1 次）", len(rec.messages) == 1,
          "n=%d" % len(rec.messages))
    if rec.messages:
        msg = rec.messages[0]
        check("[15] 注入 notifier 收到的文案含 code=100 与 --login",
              "code=100" in msg and "--login" in msg, msg)
        check("[15] 注入 notifier 收到的文案不含 cookie 明文",
              "DUMMY_COOKIE" not in msg and "z_c0=" not in msg, msg)
    _assert_state("[15] 注入的 state_path 被真实使用（state=auth_failed）",
                  state, "status", "auth_failed")
    _assert_state("[15] 注入的 state_path 上记的 code 是接口 code=100", state, "code", 100)
    check("[15] --refresh 已把新 cookie 写回（回读一致）",
          cookie_store.read_cookie_auth(cfg) == NEW_COOKIE, "")

    before = open(cfg, "rb").read()
    try:
        tool._browser_cookie_string = fake_browser
        rec2 = _Recorder()
        rc2 = tool.do_refresh(config_path=cfg, state_path=state,
                              fetcher=_FakeFetcher(200, _ok_body()), notifier=rec2)
    finally:
        tool._browser_cookie_string = real_browser
    check("[15] 第二次同值 → rc==0", rc2 == 0, "rc=%r" % (rc2,))
    check("[15] 第二次同值 → 文件字节未变（跳过写回）", open(cfg, "rb").read() == before, "")
    check("[15] auth_failed → ok → 发恢复通知 1 次", len(rec2.messages) == 1,
          "n=%d" % len(rec2.messages))
    if rec2.messages:
        check("[15] 恢复通知也走注入的 notifier（文案含『已恢复』）",
              "已恢复" in rec2.messages[0], rec2.messages[0])
    _assert_state("[15] 恢复后注入的 state_path 上 status=ok", state, "status", "ok")

    # --login 走同一条公共流程：假浏览器返回空串 → 必须是 2（未完成扫码登录），且不发通知
    try:
        tool._browser_cookie_string = lambda headless, timeout_s, settle_ms: (None, "超时")
        rec3 = _Recorder()
        rc3 = tool.do_login(config_path=cfg, state_path=state, fetcher=_FakeFetcher(200, _ok_body()),
                            notifier=rec3)
    finally:
        tool._browser_cookie_string = real_browser
    check("[15] --login 未拿到 cookie → rc==2", rc3 == 2, "rc=%r" % (rc3,))
    check("[15] --login 未拿到 cookie → 不误发通知", rec3.messages == [], "n=%d" % len(rec3.messages))


# ---------------------------------------------------------------------------
# [4b] 幂等短路 / 备份保真 / notify 返回值：三个「改了没人知道」的用法点
# ---------------------------------------------------------------------------
def test_write_side_effects_locked():
    """这三个断言都锁在**可观察行为**上（是否发生原子替换 / 备份的字节 / 返回值），
    不是「源码里有没有出现某个名字」——后者在本仓库有过「全绿但行为已腐烂」的前科。

    对应变异：
      · cs:286 `if new_bytes != raw_bytes:` → 恒真：同值再写会多做一次 os.replace；
      · cs:283 `f.write(raw_bytes)` → `f.write(b"")`：备份变成空文件；
      · cs:318 `return False` → `return True`：通知失败的返回值被翻转。
    """
    print("\n[4b] 幂等短路 / 备份保真 / notify 返回值（行为级锁）")
    tmp = _workdir()
    path = _copy_real(tmp)
    cookie_store.write_cookie_auth(path, NEW_COOKIE)
    before = open(path, "rb").read()

    # --- D4 cs:286 幂等短路：同值再写**不得**触发任何原子替换 ---
    replaces = []
    real_replace = cookie_store.os.replace

    def spying_replace(src, dst):
        replaces.append((src, dst))
        return real_replace(src, dst)

    cookie_store.os.replace = spying_replace
    try:
        cookie_store.write_cookie_auth(path, NEW_COOKIE)
    finally:
        cookie_store.os.replace = real_replace
    check("[4b] D4 cs:286 同值再写 → 一次 os.replace 都没发生（短路真的生效）",
          replaces == [], "replaces=%r" % (replaces,))
    check("[4b] 同值再写 → 文件字节不变", open(path, "rb").read() == before, "")

    # --- D4 cs:283 备份必须是「调用前的原始字节」---
    src = _copy_real(tmp, "bak_src.yaml")
    src_before = open(src, "rb").read()
    backup = os.path.join(tmp, "bakdir", "zhihu.yaml.bak")
    cookie_store.write_cookie_auth(src, NEW_COOKIE, backup_path=backup)
    check("[4b] D4 cs:283 备份文件已生成", os.path.exists(backup), backup)
    check("[4b] D4 cs:283 备份内容 == 调用前的原始字节（逐字节且非空）",
          os.path.exists(backup) and open(backup, "rb").read() == src_before,
          "backup_len=%d src_len=%d"
          % (os.path.getsize(backup) if os.path.exists(backup) else -1, len(src_before)))
    check("[4b] 备份内容与写后的目标文件不同（证明确实是「写前」的旧内容）",
          open(backup, "rb").read() != open(src, "rb").read(), "")

    # --- D4 cs:318 notify 的返回值（此前无人断言）---
    seen = []
    ok = cookie_store.notify("hello-alert", lambda m: seen.append(m))
    check("[4b] D4 cs:318 notifier 正常 → notify 返回 True", ok is True, repr(ok))
    check("[4b] notifier 确实收到同一条消息", seen == ["hello-alert"], repr(seen))

    def failing_notifier(_m):
        raise RuntimeError("webhook 500")

    bad = cookie_store.notify("hello-alert", failing_notifier)
    check("[4b] D4 cs:318 notifier 抛异常 → notify 返回 False（不让告警失败拖垮退出码）",
          bad is False, repr(bad))


# ---------------------------------------------------------------------------
# [19] D3：每条拒绝路径都必须让文件**逐字节**等于调用前（事务性）
# ---------------------------------------------------------------------------
def test_d3_transactional_rejections():
    print("\n[19] D3: 拒绝路径的事务性 —— 0 条 / 2 条 / 嵌套 auth / 回读不一致")
    tmp = _workdir()
    import yaml

    # (a) 嵌套 auth:（cookie: > nested: > auth:）必须算 **0 条**（拒绝），不是 1 条
    nested_before = (b'cookie:\n  z_c0: "x"\n  nested:\n    auth: "inner"\n')
    nested = os.path.join(tmp, "nested.yaml")
    with open(nested, "wb") as f:
        f.write(nested_before)
    check("[19] 场景自证：嵌套副本确实含 auth: 行（拒绝不能是因为『0 条』这个更弱的原因）",
          b"auth:" in nested_before, "")
    _expect_raises("[19] D3(a) 嵌套 auth: 不是 cookie 的直接子键 → 必须拒绝",
                   cookie_store.CookieWriteError,
                   lambda: cookie_store.write_cookie_auth(nested, NEW_COOKIE))
    check("[19] D3(a) 嵌套 auth: 被拒后文件逐字节不变",
          open(nested, "rb").read() == nested_before, "文件被改动了（先改后报错）")

    # (b) 正对照：直接子键 auth + 嵌套同名键共存 → 恰好 1 条，正常写回且不碰嵌套值。
    #     没有这条正对照，「把 child_indent 写得过严（一条都不认）」也会让 (a) 变绿。
    mixed = os.path.join(tmp, "mixed.yaml")
    with open(mixed, "wb") as f:
        f.write(b'cookie:\n  auth: "old"\n  nested:\n    auth: "inner"\n')
    mixed_ok, mixed_err = True, ""
    try:
        cookie_store.write_cookie_auth(mixed, NEW_COOKIE)
    except Exception as e:
        mixed_ok, mixed_err = False, "%s: %s" % (type(e).__name__, e)
    check("[19] D3(a) 正对照：直接子键 auth 存在时，嵌套同名键不影响写入", mixed_ok, mixed_err)
    check("[19] D3(a) 正对照：回读 == 写入值",
          cookie_store.read_cookie_auth(mixed) == NEW_COOKIE, "")
    check("[19] D3(a) 正对照：嵌套的 nested.auth 保持原值",
          yaml.safe_load(open(mixed, encoding="utf-8").read())["cookie"]["nested"]["auth"]
          == "inner", "")

    # (c) 0 条 auth 行
    zero = os.path.join(tmp, "zero.yaml")
    with open(zero, "wb") as f:
        f.write(b'cookie:\n  z_c0: "x"\n')
    zero_before = open(zero, "rb").read()
    _expect_raises("[19] D3 0 条 auth 行 → 拒绝", cookie_store.CookieWriteError,
                   lambda: cookie_store.write_cookie_auth(zero, NEW_COOKIE))
    check("[19] D3 0 条 auth 行 → 文件逐字节不变",
          open(zero, "rb").read() == zero_before, "")

    # (d) 2 条 auth 行
    dup = os.path.join(tmp, "dup.yaml")
    with open(dup, "wb") as f:
        f.write(b'cookie:\n  auth: "a"\n  auth: "b"\n')
    dup_before = open(dup, "rb").read()
    _expect_raises("[19] D3 2 条 auth 行 → 拒绝", cookie_store.CookieWriteError,
                   lambda: cookie_store.write_cookie_auth(dup, NEW_COOKIE))
    check("[19] D3 2 条 auth 行 → 文件逐字节不变",
          open(dup, "rb").read() == dup_before, "")

    # (e) 回读「撒谎」：写盘已经发生，但回读返回错值 → 必须把原始字节还原回去
    target = _copy_real(tmp, "readback.yaml")
    target_before = open(target, "rb").read()
    original_auth = cookie_store.read_cookie_auth(target)
    check("[19] 场景自证：原值与将写入的值不同（写入确实发生了）",
          original_auth != NEW_COOKIE, "")
    real_read = cookie_store.read_cookie_auth
    raised = False
    cookie_store.read_cookie_auth = lambda _p: "TAMPERED-NOT-WHAT-WE-WROTE"
    try:
        cookie_store.write_cookie_auth(target, NEW_COOKIE)
    except cookie_store.CookieWriteVerificationError:
        raised = True
    except Exception as e:
        check("[19] D3 回读不一致 → 抛 CookieWriteVerificationError", False,
              "实际抛出 %s: %s" % (type(e).__name__, e))
    finally:
        cookie_store.read_cookie_auth = real_read
    check("[19] D3 回读不一致 → 抛 CookieWriteVerificationError（拦住了）", raised, "未抛出")
    check("[19] D3 **回读撒谎后文件已还原为原始字节**（写盘后不还原 = 半成品留在生产凭据上）",
          open(target, "rb").read() == target_before,
          "len %d → %d" % (len(target_before), len(open(target, "rb").read())))
    check("[19] D3 还原后磁盘值 == 调用前的原值",
          cookie_store.read_cookie_auth(target) == original_auth, "")

    # (f) 回读直接抛异常（不是撒谎）→ 同样必须还原
    target2 = _copy_real(tmp, "readfail.yaml")
    target2_before = open(target2, "rb").read()

    def exploding_read(_p):
        raise cookie_store.CookieConfigError("read exploded")

    raised2 = False
    cookie_store.read_cookie_auth = exploding_read
    try:
        cookie_store.write_cookie_auth(target2, NEW_COOKIE)
    except cookie_store.CookieWriteVerificationError:
        raised2 = True
    except Exception as e:
        check("[19] D3 回读抛异常 → 收敛为 CookieWriteVerificationError", False,
              "实际抛出 %s: %s" % (type(e).__name__, e))
    finally:
        cookie_store.read_cookie_auth = real_read
    check("[19] D3 回读抛异常 → 抛 CookieWriteVerificationError", raised2, "未抛出")
    check("[19] D3 回读抛异常后文件逐字节不变",
          open(target2, "rb").read() == target2_before, "")


# ---------------------------------------------------------------------------
# [16] D1：403 / 429 / 500 / 302 → rc==3、ok→非ok 必响铃、**不抛异常**
# ---------------------------------------------------------------------------
def _log_capture():
    """捕获 tool 的日志（stdlib logging，不联网）。"""
    import logging

    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler()
    tool.LOG.addHandler(handler)
    return handler, records


def test_non200_statuses():
    print("\n[16] D1: 403/429/500/302 → rc==3、ok→非ok 告警、不抛异常")
    for status in (403, 429, 500, 302):
        tmp = _workdir()
        cfg, state = _cfg_and_state(tmp, "s%d.yaml" % status)
        # 1) 先建立 ok 历史（否则「状态变化」这条判据无从谈起）
        rc_ok, crash_ok = _check_catching(config_path=cfg, state_path=state,
                                          fetcher=_FakeFetcher(200, _ok_body()),
                                          notifier=_Recorder())
        check("[16] HTTP %d 前置：建立 ok 历史 → rc==0" % status,
              crash_ok is None and rc_ok == 0, "rc=%r crash=%s" % (rc_ok, crash_ok))

        rec = _Recorder()
        rc, crashed = _check_catching(config_path=cfg, state_path=state,
                                      fetcher=_FakeFetcher(status, ""), notifier=rec)

        check("[16] D1 HTTP %d → 不抛未捕获异常（'.strip() 绑到 tuple' 崩溃路径）" % status,
              crashed is None, crashed or "")
        check("[16] D1 HTTP %d → rc==3" % status, rc == 3,
              "rc=%r（crashed=%s）" % (rc, crashed))
        check("[16] HTTP %d → ok→非ok 触发告警恰好 1 次" % status,
              len(rec.messages) == 1, "n=%d" % len(rec.messages))
        if rec.messages:
            msg = rec.messages[0]
            check("[16] HTTP %d 告警文案含该状态码（证明 classify 真的跑完了）" % status,
                  str(status) in msg, msg)
            check("[16] HTTP %d 告警不含 cookie 明文" % status,
                  "DUMMY_COOKIE" not in msg and "z_c0=" not in msg, msg)
            check("[16] HTTP %d 告警类别正确（403/429 标风控，500/302 不标）" % status,
                  ("风控" in msg) == (status in (403, 429)), msg)
        expect_state = "anti_bot" if status in (403, 429) else "error"
        _assert_state("[16] HTTP %d 状态文件 status=%s" % (status, expect_state),
                      state, "status", expect_state)
        _assert_state("[16] HTTP %d 状态文件 code 回落为 HTTP 状态码" % status,
                      state, "code", status)

        # 2) 同一类别再来一次 → 不重复告警
        rec2 = _Recorder()
        rc2, crash2 = _check_catching(config_path=cfg, state_path=state,
                                      fetcher=_FakeFetcher(status, ""), notifier=rec2)
        check("[16] HTTP %d 连续第二次 → rc==3 且不重复告警" % status,
              crash2 is None and rc2 == 3 and rec2.messages == [],
              "rc=%r n=%d crash=%s" % (rc2, len(rec2.messages), crash2))

        # 3) 非 ok → ok → 发恢复通知
        rec3 = _Recorder()
        rc3, crash3 = _check_catching(config_path=cfg, state_path=state,
                                      fetcher=_FakeFetcher(200, _ok_body()), notifier=rec3)
        check("[16] HTTP %d → 恢复 ok：rc==0 且发恢复通知 1 次" % status,
              crash3 is None and rc3 == 0 and len(rec3.messages) == 1,
              "rc=%r n=%d crash=%s" % (rc3, len(rec3.messages), crash3))

    # 403 响应体是「非 JSON 的 HTML 风控页」时同样不能崩
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "blocked_html.yaml")
    rc, crashed = _check_catching(config_path=cfg, state_path=state,
                                  fetcher=_FakeFetcher(403, "<html><body>403 Forbidden</body></html>"),
                                  notifier=_Recorder())
    check("[16] 403 + HTML 风控页 → 不抛异常且 rc==3",
          crashed is None and rc == 3, "rc=%r crashed=%s" % (rc, crashed))


# ---------------------------------------------------------------------------
# [17] D1 / D4 tool:155：401 无 code 字段 → rc==2（认证失败），不能崩
# ---------------------------------------------------------------------------
def test_401_without_code():
    print("\n[17] D1/D4: 401 响应体无 code / 非 JSON / 空 → rc==2 且告警")
    cases = (
        ("无 code 字段", json.dumps({"name": "AuthenticationError",
                                     "message": "身份未经过验证"}, ensure_ascii=False)),
        ("非 JSON 响应体", "<html>401 from CDN</html>"),
        ("空响应体", ""),
    )
    for label, body in cases:
        tmp = _workdir()
        cfg, state = _cfg_and_state(tmp, "nocode.yaml")
        rec = _Recorder()
        rc, crashed = _check_catching(config_path=cfg, state_path=state,
                                      fetcher=_FakeFetcher(401, body), notifier=rec)
        check("[17] 401（%s）→ 不抛异常" % label, crashed is None, crashed or "")
        check("[17] D4 tool:155 401（%s）→ rc==2" % label, rc == 2,
              "rc=%r（crashed=%s）" % (rc, crashed))
        check("[17] 401（%s）→ 告警 1 次且点名 --login" % label,
              len(rec.messages) == 1 and "--login" in rec.messages[0],
              "n=%d" % len(rec.messages))
        _assert_state("[17] 401（%s）→ 状态文件 status=auth_failed" % label,
                      state, "status", "auth_failed")
        # --- U2：`api_code if api_code is not None else status` 这层回落必须被**值**锁住 ---
        # 去掉回落时 suite 仍然全绿（rc 还是 2），但 state.code 变成 null、告警文案从
        # code=401 变成 code=n/a —— 运维就无法从告警里看出到底哪个状态码触发的。
        _assert_state("[17] D4 tool:205 401（%s）→ state.code 回落为 HTTP 401（不是 null）" % label,
                      state, "code", 401)
        if rec.messages:
            check("[17] D4 tool:205 401（%s）→ 告警文案带状态码回落 code=401" % label,
                  "code=401" in rec.messages[0] and "code=n/a" not in rec.messages[0],
                  rec.messages[0])


# ---------------------------------------------------------------------------
# [18] D2：状态文件父路径被普通文件占位 → 降级 rc==3 + 明确日志，绝不抛出去
# ---------------------------------------------------------------------------
def test_state_path_blocked_by_file():
    print("\n[18] D2: 状态文件不可用 → 降级 rc==3 + 日志点名路径与 OS 错误")
    tmp = _workdir()
    blocker = os.path.join(tmp, "blocker")
    with open(blocker, "wb") as f:
        f.write(b"i am a regular file, not a directory\n")
    cfg = _write_text(os.path.join(tmp, "cfg.yaml"), _sanitized_real_text())
    state_path = os.path.join(blocker, "state.json")
    check("[18] 场景自证：父路径确实是普通文件而非目录",
          os.path.isfile(blocker) and not os.path.isdir(blocker), blocker)

    handler, records = _log_capture()
    rec = _Recorder()
    crashed, rc = None, None
    try:
        rc = tool.check(config_path=cfg, state_path=state_path,
                        fetcher=_FakeFetcher(200, _ok_body()), notifier=rec)
    except Exception as e:
        crashed = "%s: %s" % (type(e).__name__, e)
    finally:
        tool.LOG.removeHandler(handler)
    blob = "\n".join(r.getMessage() for r in records)

    check("[18] 父路径被文件占位 → 不抛异常（makedirs 的 FileExistsError 已收敛）",
          crashed is None, crashed or "")
    check("[18] D2 降级为 rc==3", rc == 3, "rc=%r（crashed=%s）" % (rc, crashed))
    check("[18] D2 日志点名状态文件路径", state_path in blob, blob[-500:])
    check("[18] D2 日志含 OS 错误类型与细节（Errno/WinError）",
          ("FileExistsError" in blob or "NotADirectoryError" in blob or "OSError" in blob)
          and ("[WinError" in blob or "Errno" in blob), blob[-500:])

    # 判定为 auth_failed(2) 时，状态文件仍不可用 → 契约规定降级 rc==3；但告警不能丢
    handler2, records2 = _log_capture()
    rec2 = _Recorder()
    rc2 = None
    raised2 = None
    try:
        rc2 = tool.check(config_path=cfg, state_path=state_path,
                         fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=rec2)
    except Exception as e:
        raised2 = "%s: %s" % (type(e).__name__, e)
    finally:
        tool.LOG.removeHandler(handler2)
    check("[18] 判定 auth_failed 但状态文件不可用 → 仍降级 rc==3（不抛）",
          raised2 is None and rc2 == 3, "rc=%r raised=%s" % (rc2, raised2))
    check("[18] 降级前告警已发出（不因记账失败丢掉告警）",
          len(rec2.messages) == 1, "n=%d" % len(rec2.messages))


# ---------------------------------------------------------------------------
# [20] D4：settle 常量 / backup_path / check 透传链 / rc=3 降级（行为级锁）
# ---------------------------------------------------------------------------
def test_tool_wiring_locks():
    print("\n[20] D4: settle 常量 / _write_back 备份 / check 透传链 / rc=3 降级")
    tmp = _workdir()
    cfg = _write_text(os.path.join(tmp, "wiring.yaml"), _sanitized_real_text())
    state = os.path.join(tmp, "wiring_state.json")

    seen = {}
    real_browser = tool._browser_cookie_string

    def fake_browser(headless, timeout_s, settle_ms):
        seen["headless"] = headless
        seen["settle_ms"] = settle_ms
        seen["timeout_s"] = timeout_s
        return NEW_COOKIE + "; wired=1", ""

    capture = {}
    real_check = tool.check

    def spying_check(**kwargs):
        capture.clear()
        capture.update(kwargs)
        return 0

    # --- do_refresh：settle 常量必须传给取 cookie 的流程，并把参数透传给 check ---
    fetch = _FakeFetcher(200, _ok_body())
    rec = _Recorder()
    rc = None
    crashed = None
    try:
        tool._browser_cookie_string = fake_browser
        tool.check = spying_check
        rc = tool.do_refresh(config_path=cfg, state_path=state, fetcher=fetch, notifier=rec)
    except Exception as e:
        crashed = "%s: %s" % (type(e).__name__, e)
    finally:
        tool.check = real_check
        tool._browser_cookie_string = real_browser
    check("[20] --refresh 全流程不抛异常", crashed is None, crashed or "")
    check("[20] D4 tool:65 REFRESH_SETTLE_MS == 12000（0 与 12 必须可区分）",
          tool.REFRESH_SETTLE_MS == 12000, repr(tool.REFRESH_SETTLE_MS))
    check("[20] D4 tool:483 --refresh 把 REFRESH_SETTLE_MS 传给取 cookie 流程",
          seen.get("settle_ms") == tool.REFRESH_SETTLE_MS, repr(seen))
    check("[20] --refresh 走无头浏览器（headless=True）", seen.get("headless") is True, repr(seen))
    check("[20] D4 tool:460 run_browser_flow → check 的 state_path 透传",
          capture.get("state_path") == state, repr(capture.get("state_path")))
    check("[20] D4 tool:460 run_browser_flow → check 的 fetcher 透传",
          capture.get("fetcher") is fetch, repr(capture.get("fetcher")))
    check("[20] D4 tool:460 run_browser_flow → check 的 notifier 透传",
          capture.get("notifier") is rec, repr(capture.get("notifier")))
    check("[20] --refresh 的 rc 取自就地 check", rc == 0, "rc=%r" % (rc,))

    # --- do_login：settle 必须为 0（扫码完成即取，不需要等续期回写）---
    seen.clear()
    capture.clear()
    fetch2 = _FakeFetcher(200, _ok_body())
    rec2 = _Recorder()
    crash2 = None
    try:
        tool._browser_cookie_string = fake_browser
        tool.check = spying_check
        tool.do_login(config_path=cfg, state_path=state, fetcher=fetch2, notifier=rec2)
    except Exception as e:
        crash2 = "%s: %s" % (type(e).__name__, e)
    finally:
        tool.check = real_check
        tool._browser_cookie_string = real_browser
    check("[20] D4 tool:471 --login 的 settle 为 0", seen.get("settle_ms") == 0, repr(seen))
    check("[20] --login 走有头浏览器（headless=False）", seen.get("headless") is False, repr(seen))
    check("[20] D4 tool:471 do_login → check 的 state_path/fetcher/notifier 全部透传",
          capture.get("state_path") == state and capture.get("fetcher") is fetch2
          and capture.get("notifier") is rec2 and crash2 is None,
          "crash=%s captured=%r" % (crash2, sorted(capture)))

    # --- D4 tool:404 _write_back 必须把 backup_path 传给写盘函数 ---
    wcapture = {}
    real_write = cookie_store.write_cookie_auth

    def spying_write(path, cookie, backup_path=None):
        wcapture["path"] = path
        wcapture["cookie"] = cookie
        wcapture["backup_path"] = backup_path

    cookie_store.write_cookie_auth = spying_write
    try:
        tool._write_back(cfg, NEW_COOKIE + "; bak=1")
    finally:
        cookie_store.write_cookie_auth = real_write
    bk = wcapture.get("backup_path")
    check("[20] D4 tool:404 _write_back 把 backup_path 传给了写盘函数",
          isinstance(bk, str) and bk.endswith(".bak"), repr(bk))
    check("[20] backup_path 落在 repo 的 tmp/ 下（含实时凭据，必须在忽略区）",
          isinstance(bk, str) and os.path.abspath(bk).startswith(
              os.path.abspath(os.path.join(ROOT, "tmp")) + os.sep), repr(bk))
    check("[20] _write_back 把目标配置路径与 cookie 原样传给写盘函数",
          wcapture.get("path") == cfg and wcapture.get("cookie") == NEW_COOKIE + "; bak=1", "")

    # --- D4 tool:507 写回失败但就地校验通过（rc 本应是 0）→ 必须降级为 rc==3 ---
    cfg3 = _write_text(os.path.join(tmp, "wiring3.yaml"), _sanitized_real_text())
    state3 = os.path.join(tmp, "wiring_state3.json")
    real_wb = tool._write_back

    def broken_write_back(_cfg, _cookie):
        raise cookie_store.CookieWriteError("disk full")

    rc3, crash3 = None, None
    try:
        tool._browser_cookie_string = fake_browser
        tool._write_back = broken_write_back
        rc3 = tool.do_refresh(config_path=cfg3, state_path=state3,
                              fetcher=_FakeFetcher(200, _ok_body()), notifier=_Recorder())
    except Exception as e:
        crash3 = "%s: %s" % (type(e).__name__, e)
    finally:
        tool._write_back = real_wb
        tool._browser_cookie_string = real_browser
    check("[20] D4 tool:507 写回失败但校验通过 → 降级 rc==3",
          crash3 is None and rc3 == 3, "rc=%r crash=%s" % (rc3, crash3))
    _assert_state("[20] D4 tool:507 此时就地校验确实通过了（状态文件被写成 ok）",
                  state3, "status", "ok")


# ---------------------------------------------------------------------------
# [21] 告警必须走**注入的** notifier，不能碰真实企微 webhook
# ---------------------------------------------------------------------------
def test_fake_notifier_is_the_one_used():
    print("\n[21] 告警走的是注入的 notifier（真实企微通道不可能被命中）")
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "notifier.yaml")
    rec = _Recorder()
    seen = []
    real_notify = cookie_store.notify

    def spying_notify(message, notifier=None):
        seen.append((message, notifier))
        return real_notify(message, notifier)

    cookie_store.notify = spying_notify
    try:
        rc = tool.check(config_path=cfg, state_path=state,
                        fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=rec)
    finally:
        cookie_store.notify = real_notify
    check("[21] rc==2（告警路径确实走到了）", rc == 2, "rc=%r" % (rc,))
    check("[21] cookie_store.notify 收到的 notifier 就是注入的那个",
          len(seen) == 1 and seen[0][1] is rec,
          repr([type(s[1]).__name__ if s[1] is not None else None for s in seen]))
    check("[21] 注入的 fake notifier 真的收到告警", rec.messages != [], "")
    # --- M18：把「传 notifier」这半边去掉（cookie_store.notify(alert)）必须是一条**断言**
    # 失败，而不是靠「延迟导入在无 aiohttp 机器上抛 ImportError」把进程崩掉才红。
    # 断言注入方**收到的参数与文案内容**：调用次数 + 消息内容 + 消息同源。
    check("[21] 注入的 notifier 恰好被调用 1 次（调用次数被锁住）", len(rec.messages) == 1,
          "n=%d" % len(rec.messages))
    if rec.messages:
        check("[21] 注入的 notifier 收到的文案含 code=100 / 站点 zhihu / 人工动作 --login",
              "code=100" in rec.messages[0] and "zhihu" in rec.messages[0]
              and "--login" in rec.messages[0], rec.messages[0])
        check("[21] cookie_store.notify 收到的 message 与 notifier 收到的是同一条",
              seen and seen[0][0] == rec.messages[0], repr(seen[:1]))
    check("[21] 全程未导入 app.wework.notification_push（零外呼的必要条件之一）",
          "app.wework.notification_push" not in sys.modules, "已被导入")


# ---------------------------------------------------------------------------
# [22] 零外呼：把底层网络入口全部计数，跑完代表性路径后必须全 0
# ---------------------------------------------------------------------------
def test_no_network_egress():
    print("\n[22] 零外呼：connect/connect_ex/create_connection/getaddrinfo/socket()/urlopen 全 0")
    import socket as _socket
    import urllib.request as _urllib_request

    counts = {"connect": 0, "connect_ex": 0, "create_connection": 0,
              "getaddrinfo": 0, "socket": 0, "urlopen": 0}
    real_socket = _socket.socket
    real_cc = _socket.create_connection
    real_gai = _socket.getaddrinfo
    real_urlopen = _urllib_request.urlopen

    # socket() 这一层用**子类**计数（而不是把 socket.socket 换成函数）：
    # 这样外层若也装了同类计数器（例如零外呼复现脚本），彼此仍可嵌套而不是互相打崩。
    socket_patched = isinstance(real_socket, type)

    class _CountingSocket(real_socket):
        def __init__(self, *a, **k):
            counts["socket"] += 1
            real_socket.__init__(self, *a, **k)

        def connect(self, *a, **k):
            counts["connect"] += 1
            return real_socket.connect(self, *a, **k)

        def connect_ex(self, *a, **k):
            counts["connect_ex"] += 1
            return real_socket.connect_ex(self, *a, **k)

    def counting_cc(*a, **k):
        counts["create_connection"] += 1
        return real_cc(*a, **k)

    def counting_gai(*a, **k):
        counts["getaddrinfo"] += 1
        return real_gai(*a, **k)

    def counting_urlopen(*a, **k):
        counts["urlopen"] += 1
        return real_urlopen(*a, **k)

    if socket_patched:
        _socket.socket = _CountingSocket
    _socket.create_connection = counting_cc
    _socket.getaddrinfo = counting_gai
    _urllib_request.urlopen = counting_urlopen
    crash = None
    try:
        tmp = _workdir()
        cfg, state = _cfg_and_state(tmp, "egress.yaml")
        for fetcher in (_FakeFetcher(200, _ok_body()), _FakeFetcher(401, BODY_CODE_101),
                        _FakeFetcher(403, ""), _FakeFetcher(500, ""),
                        _FakeFetcher(302, "")):
            tool.check(config_path=cfg, state_path=state, fetcher=fetcher, notifier=_Recorder())

        # 传输失败路径（fetcher 自己抛，不落到 socket）
        def boom(_u, _c, timeout=10):
            raise tool.TransportError("connection refused")

        tool.check(config_path=cfg, state_path=state, fetcher=boom, notifier=_Recorder())
        # 缺凭证路径（不打网络）
        no_auth = _write_text(os.path.join(tmp, "no_auth_egress.yaml"), 'cookie:\n  z_c0: ""\n')
        tool.check(config_path=no_auth, state_path=os.path.join(tmp, "s2.json"),
                   fetcher=_FakeFetcher(200, _ok_body()), notifier=_Recorder())
    except Exception as e:
        crash = "%s: %s" % (type(e).__name__, e)
    finally:
        _socket.socket = real_socket
        _socket.create_connection = real_cc
        _socket.getaddrinfo = real_gai
        _urllib_request.urlopen = real_urlopen

    check("[22] 代表性路径全流程不抛异常", crash is None, crash or "")
    for key in ("connect", "connect_ex", "create_connection", "getaddrinfo", "urlopen"):
        check("[22] %s 调用次数 == 0（零外呼）" % key, counts[key] == 0, "counts=%r" % (counts,))
    if socket_patched:
        check("[22] socket() 调用次数 == 0（零外呼）", counts["socket"] == 0, "counts=%r" % (counts,))
    else:
        print("      [SKIP] socket() 计数被外层复现脚本接管（socket.socket 已不是类）")


# ---------------------------------------------------------------------------
# [23] D5：坏状态文件仍然宽容，但降级必须**可见**（点名路径 + 解析错误）
# ---------------------------------------------------------------------------
def test_corrupt_state_file_is_visible():
    print("\n[23] D5: 不可解析 / 结构不对的状态文件 → 宽容继续但必须 warning")
    import logging

    cases = (
        ("非法 JSON", "{not json at all", ("JSONDecodeError", "ValueError")),
        ("顶层不是对象", "[]", ("不是 JSON 对象",)),
    )
    for label, content, needles in cases:
        tmp = _workdir()
        cfg, state = _cfg_and_state(tmp, "corrupt.yaml")
        _write_text(state, content)

        handler, records = _log_capture()
        rec = _Recorder()
        rc, crashed = None, None
        try:
            rc = tool.check(config_path=cfg, state_path=state,
                            fetcher=_FakeFetcher(200, _ok_body()), notifier=rec)
        except Exception as e:
            crashed = "%s: %s" % (type(e).__name__, e)
        finally:
            tool.LOG.removeHandler(handler)
        blob = "\n".join(r.getMessage() for r in records)
        warnings = [r for r in records if r.levelno == logging.WARNING]

        check("[23] D5 坏状态文件（%s）仍宽容：不抛且 rc==0" % label,
              crashed is None and rc == 0, "rc=%r crashed=%s" % (rc, crashed))
        check("[23] D5 坏状态文件（%s）有 WARNING 级日志（降级可见，不再静默）" % label,
              len(warnings) >= 1, "warnings=%d" % len(warnings))
        check("[23] D5 warning 点名状态文件路径（%s）" % label, state in blob, blob[-400:])
        check("[23] D5 warning 含解析/结构错误信息（%s）" % label,
              any(n in blob for n in needles), blob[-400:])


# ---------------------------------------------------------------------------
# [24] E1：告警投递失败不得吞掉状态转换、不得改 rc、也不得静默
# ---------------------------------------------------------------------------
def test_alert_delivery_failure_is_contained():
    print("\n[24] E1: 告警投递失败（含 notifier 延迟导入失败）→ 不崩 / rc 类别码 / 状态已落盘")
    # 场景构造：notifier=None 时 cookie_store.notify 会
    #   `from app.wework.notification_push import send_message`（该模块拉起 aiohttp）。
    # 往 sys.modules 里塞 None 可以让这次延迟导入**确定性地**抛 ImportError —— 不依赖
    # 「本机恰好没装 aiohttp」。生产机装了 aiohttp，靠真实 ImportError 会变成一次真的
    # 企微 webhook 外呼，那是不能接受的测试副作用。
    mod_name = "app.wework.notification_push"
    check("[24] 场景自证：测试开始时未导入 notification_push", mod_name not in sys.modules,
          "已被导入")

    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "notifyfail.yaml")

    handler, records = _log_capture()
    crashed, rc, direct = None, None, None
    real_notify = cookie_store.notify
    sys.modules[mod_name] = None  # None → `from X import Y` 抛 ImportError（确定性、离线）
    try:
        try:
            direct = real_notify("probe-alert", None)  # 直接证明 notify 自己不抛
        except Exception as e:  # noqa: BLE001  被测的就是「绝不抛」这条契约
            direct = "RAISED %s: %s" % (type(e).__name__, e)
        rc, crashed = _check_catching(config_path=cfg, state_path=state,
                                      fetcher=_FakeFetcher(401, BODY_CODE_100), notifier=None)
    finally:
        del sys.modules[mod_name]
        tool.LOG.removeHandler(handler)
    blob = "\n".join(r.getMessage() for r in records)

    check("[24] E1 cs:383 延迟导入失败时 cookie_store.notify 自己不抛且返回 False",
          direct is False, repr(direct))
    check("[24] E1 tool:456 告警投递失败时**没有任何异常逃出 check()**", crashed is None,
          crashed or "")
    check("[24] E1 退出码是类别码 rc==2（不是 1/9 那种『无状态无告警』的崩溃码）", rc == 2,
          "rc=%r crashed=%s" % (rc, crashed))
    # 「投递成败」与「状态转换是否落盘」必须彻底解耦
    _assert_state("[24] E1 投递失败后状态文件**已写入**且 status=auth_failed",
                  state, "status", "auth_failed")
    _assert_state("[24] E1 投递失败后状态文件仍带完整判定信息（code=100）", state, "code", 100)
    check("[24] E1 投递失败被**明确记录**（不是静默吞掉）", "告警投递失败" in blob, blob[-600:])
    check("[24] 未把 notification_push 留在 sys.modules（测试自身无污染）",
          mod_name not in sys.modules, "残留")

    # 变体 1：注入的 notifier 自己抛 → 同样「不崩 / rc 类别码 / 状态已落盘 / 有明确日志」
    tmp2 = _workdir()
    cfg2, state2 = _cfg_and_state(tmp2, "notifyraise.yaml")

    def exploding_notifier(_message):
        raise RuntimeError("webhook 500")

    handler2, records2 = _log_capture()
    rc2, crash2 = None, None
    fail_order = []
    real_writer2 = tool._write_state

    def counting_writer(path, record):
        fail_order.append("write_state")
        return real_writer2(path, record)

    tool._write_state = counting_writer
    try:
        rc2, crash2 = _check_catching(config_path=cfg2, state_path=state2,
                                      fetcher=_FakeFetcher(401, BODY_CODE_100),
                                      notifier=exploding_notifier)
    finally:
        tool._write_state = real_writer2
        tool.LOG.removeHandler(handler2)
    blob2 = "\n".join(r.getMessage() for r in records2)
    check("[24] E1 注入 notifier 抛异常 → 不抛未捕获异常且 rc==2",
          crash2 is None and rc2 == 2, "rc=%r crash=%s" % (rc2, crash2))
    _assert_state("[24] E1 注入 notifier 抛异常 → 状态文件仍然落盘", state2, "status",
                  "auth_failed")
    check("[24] E1 注入 notifier 抛异常 → 投递失败被明确记录",
          "告警投递失败" in blob2, blob2[-600:])
    # G1：投递**失败**时只能有一次落盘（写入 pending 标记），绝不能出现「清标记」的第二次。
    # 这是「mark delivered ONLY on success」的可观察等价物。
    _assert_state("[24] G1 投递失败 → 状态文件 alert_pending 保持 true",
                  state2, "alert_pending", True)
    saved_msg = _state_field(state2, "alert_message")[0]
    check("[24] G1 投递失败 → 未送达的告警原文被持久化（下次运行才能原样补投）",
          isinstance(saved_msg, str) and "code=100" in saved_msg and "--login" in saved_msg
          and "DUMMY_COOKIE" not in saved_msg,
          "alert_message=%r" % (saved_msg,))
    check("[24] G1 投递失败的那次运行只落盘一次（清标记只允许在成功之后）",
          fail_order == ["write_state"], repr(fail_order))

    # 变体 2（顺序锁）：把 cookie_store.notify 换成**会抛**的实现 —— 也就是「绝不抛」这条
    # 契约被破坏。此时状态转换必须**已经落盘**（先写状态、再发告警），异常也不得逃出 check()。
    # 顺序一旦倒过来（先发告警再写状态），这条就红。
    tmp3 = _workdir()
    cfg3, state3 = _cfg_and_state(tmp3, "notifyorder.yaml")

    def catastrophic_notify(_message, _notifier=None):
        raise RuntimeError("notify 实现被替换成会抛的版本")

    handler3, records3 = _log_capture()
    rc3, crash3 = None, None
    real_notify3 = cookie_store.notify
    cookie_store.notify = catastrophic_notify
    try:
        rc3, crash3 = _check_catching(config_path=cfg3, state_path=state3,
                                      fetcher=_FakeFetcher(401, BODY_CODE_100),
                                      notifier=_Recorder())
    finally:
        cookie_store.notify = real_notify3
        tool.LOG.removeHandler(handler3)
    blob3 = "\n".join(r.getMessage() for r in records3)
    check("[24] E1 notify 契约被破坏（每次都抛）→ 异常不逃出 check() 且 rc==2",
          crash3 is None and rc3 == 2, "rc=%r crash=%s" % (rc3, crash3))
    _assert_state("[24] E1 **顺序锁**：notify 抛掉时状态转换已经落盘（先写状态、后发告警）",
                  state3, "status", "auth_failed")
    check("[24] E1 notify 抛掉时也有明确日志（未预期异常 / 投递失败）",
          "告警投递" in blob3, blob3[-600:])

    # 顺序锁（不依赖异常的可观察事件序列）：状态落盘必须发生在告警投递之前
    tmp4 = _workdir()
    cfg4, state4 = _cfg_and_state(tmp4, "notifyorder2.yaml")
    order = []
    real_writer = tool._write_state
    real_notify4 = cookie_store.notify

    def spying_writer(path, record):
        order.append("write_state")
        return real_writer(path, record)

    def spying_notify(message, notifier=None):
        order.append("notify")
        return real_notify4(message, notifier)

    tool._write_state = spying_writer
    cookie_store.notify = spying_notify
    try:
        rc4, crash4 = _check_catching(config_path=cfg4, state_path=state4,
                                      fetcher=_FakeFetcher(401, BODY_CODE_100),
                                      notifier=_Recorder())
    finally:
        tool._write_state = real_writer
        cookie_store.notify = real_notify4
    check("[24] E1 事件顺序：状态/pending 标记的落盘**先于**告警投递",
          order[:2] == ["write_state", "notify"], repr(order))
    # G1 让「送达与否」也持久化：投递**成功**后必须再落一次盘把 alert_pending 清掉。
    # 这条比原来的 `order == ["write_state", "notify"]` 更严：它同时钉住
    #   ① 清标记只可能发生在投递之后（先 notify 再写 ⇒ 红）；
    #   ② 投递成功必然产生第二次落盘（漏掉 ⇒ 下次会重复投递，见 [27]）。
    check("[24] G1 事件顺序：投递成功后**再落一次盘**记录『已送达』",
          order == ["write_state", "notify", "write_state"], repr(order))
    _assert_state("[24] G1 投递成功 → 状态文件 alert_pending 被清为 false",
                  state4, "alert_pending", False)
    check("[24] E1 顺序锁场景本身有效（有告警被投递且 rc==2）",
          crash4 is None and rc4 == 2 and order[:2] == ["write_state", "notify"],
          "rc=%r crash=%s order=%r" % (rc4, crash4, order))


# ---------------------------------------------------------------------------
# [25] E2：深层嵌套 YAML（解析爆栈）必须归入「配置不可用」，而不是崩成 rc=1
# ---------------------------------------------------------------------------
def test_deep_yaml_is_config_error():
    print("\n[25] E2: 深层嵌套 YAML → 解析爆栈被收敛成『配置不可用』rc==3（不崩、不告警）")
    import yaml

    depth = 900
    text = "\n".join([" " * i + "k%d:" % i for i in range(depth)]) + "\n" + " " * depth + "v\n"
    tmp = _workdir()
    deep = _write_text(os.path.join(tmp, "deep.yaml"), text)
    state = os.path.join(tmp, "deep_state.json")

    # 场景自证：这份文本确实会让 safe_load 爆栈 —— 否则本用例什么都没测
    boom = ""
    try:
        with open(deep, encoding="utf-8") as f:
            yaml.safe_load(f.read())
    except RecursionError:
        boom = "RecursionError"
    except Exception as e:  # noqa: BLE001  别的异常类型下这条自证会用另一种方式红
        boom = "%s: %s" % (type(e).__name__, e)
    check("[25] 场景自证：该 YAML 确实让 yaml.safe_load 抛 RecursionError",
          boom == "RecursionError", "boom=%r" % (boom,))

    raised = ""
    detail = ""
    try:
        cookie_store.read_cookie_auth(deep)
    except cookie_store.CookieConfigError as e:
        raised = "CookieConfigError"
        detail = str(e)
    except Exception as e:  # noqa: BLE001
        raised = "%s: %s" % (type(e).__name__, e)
    # ⚠️ G2：这里**没有** RecursionError 专用分支 —— 收敛它的是 cs:154 那条唯一的兜底
    # `except Exception`（RecursionError 是 Exception 的子类）。曾经那条更靠前的专用分支是
    # 死代码：删掉它这条断言仍然全绿（这正是「有守卫 ≠ 需要守卫」）。所以本用例的鉴别力
    # 必须落在**真正接住它的那条路径**上：把 cs:154 改成 `except ValueError`（RecursionError
    # 于是不再被接住）时，这一行会以 (a) 的形式红，而不是只让某个专用分支消失。
    check("[25] E2 cs:154 深嵌套 → 由唯一的兜底分支收敛为 CookieConfigError（不再是 RecursionError）",
          raised == "CookieConfigError", repr(raised))
    check("[25] E2 收敛后的错误信息带上底层异常类型 RecursionError 与文件路径（可诊断）",
          raised == "CookieConfigError" and "RecursionError" in detail and deep in detail,
          "detail=%s" % (detail[-160:],))

    rec = _Recorder()
    rc, crashed = _check_catching(config_path=deep, state_path=state,
                                  fetcher=_FakeFetcher(200, _ok_body()), notifier=rec)
    check("[25] E2 tool:399 深嵌套 → 不抛未捕获异常", crashed is None, crashed or "")
    check("[25] E2 tool:399 深嵌套 → rc==3（配置不可用，不是 rc=1 崩溃）", rc == 3,
          "rc=%r crashed=%s" % (rc, crashed))
    check("[25] 深嵌套不误判为认证失败（不 @all 告警）", rec.messages == [],
          "n=%d" % len(rec.messages))


# ---------------------------------------------------------------------------
# [26] U1：--login / --refresh 的写回必须产生**可观察的文件效果**
# ---------------------------------------------------------------------------
def test_login_refresh_writeback_is_observable():
    print("\n[26] U1: --login/--refresh 的写回锁在『文件字节变了 + 回读是新值』上")
    tmp = _workdir()
    real_browser = tool._browser_cookie_string

    def fake_browser(value):
        return lambda headless, timeout_s, settle_ms: (value, "")  # noqa: E731

    # --- --login：真实配置的**字节副本** + 假浏览器缝，断言可观察的文件效果 ---
    cfg = _copy_real(tmp, "login_flow.yaml")
    state = os.path.join(tmp, "login_state.json")
    original_auth = cookie_store.read_cookie_auth(cfg)
    before = open(cfg, "rb").read()
    before_lines = len(before.splitlines(keepends=True))
    login_cookie = NEW_COOKIE + "; login=1"
    check("[26] 场景自证：浏览器给出的新串 != 磁盘现值（否则『文件变了』无从谈起）",
          login_cookie != original_auth, "新串与现值不同")

    rc, crashed = None, None
    try:
        tool._browser_cookie_string = fake_browser(login_cookie)
        rc = tool.do_login(config_path=cfg, state_path=state,
                           fetcher=_FakeFetcher(200, _ok_body()), notifier=_Recorder())
    except Exception as e:  # noqa: BLE001
        crashed = "%s: %s" % (type(e).__name__, e)
    finally:
        tool._browser_cookie_string = real_browser

    check("[26] --login 全流程不抛异常", crashed is None, crashed or "")
    check("[26] --login 拿到 cookie 且校验 200 → rc==0", rc == 0, "rc=%r" % (rc,))
    after = open(cfg, "rb").read()
    check("[26] U1 tool:585 --login 之后配置文件**字节确实变了**（写回不是空炮）",
          after != before, "字节未变 ⇒ do_login 的写回没发生（变异『改成 pass』就死在这里）")
    check("[26] U1 --login 回读配置 == 浏览器刚拿到的 cookie",
          cookie_store.read_cookie_auth(cfg) == login_cookie,
          "回读 %s" % cookie_store._fingerprint(cookie_store.read_cookie_auth(cfg)))
    check("[26] --login 写回仍只改 auth 行（行数不变）",
          len(after.splitlines(keepends=True)) == before_lines, "")
    _assert_state("[26] --login 的就地校验把注入的 state_path 写成 ok", state, "status", "ok")

    # --- --refresh：同一条链（apply_refreshed_cookie → _write_back），同样锁文件效果 ---
    cfg2 = _copy_real(tmp, "refresh_flow.yaml")
    state2 = os.path.join(tmp, "refresh_state.json")
    before2 = open(cfg2, "rb").read()
    refresh_cookie = NEW_COOKIE + "; refresh=1"
    rc2, crash2 = None, None
    try:
        tool._browser_cookie_string = fake_browser(refresh_cookie)
        rc2 = tool.do_refresh(config_path=cfg2, state_path=state2,
                              fetcher=_FakeFetcher(200, _ok_body()), notifier=_Recorder())
    except Exception as e:  # noqa: BLE001
        crash2 = "%s: %s" % (type(e).__name__, e)
    finally:
        tool._browser_cookie_string = real_browser

    check("[26] --refresh 全流程不抛异常", crash2 is None, crash2 or "")
    check("[26] --refresh → rc==0", rc2 == 0, "rc=%r" % (rc2,))
    check("[26] U1 --refresh 之后配置文件**字节确实变了**",
          open(cfg2, "rb").read() != before2, "字节未变")
    check("[26] U1 --refresh 回读配置 == 浏览器刚拿到的 cookie",
          cookie_store.read_cookie_auth(cfg2) == refresh_cookie, "")
    _assert_state("[26] --refresh 的就地校验把注入的 state_path 写成 ok", state2, "status", "ok")

    # --- 反面对照：--dry-run 下同一流程**不得**动车上的文件 ---
    # 没有这条，「文件变了」也可能是别的原因造成的；有了它，变与不变都由写回单独解释。
    cfg3 = _copy_real(tmp, "dry_login.yaml")
    before3 = open(cfg3, "rb").read()
    try:
        tool._browser_cookie_string = fake_browser(NEW_COOKIE + "; dry=1")
        tool.do_login(config_path=cfg3, dry_run=True, state_path=os.path.join(tmp, "dry.json"),
                      fetcher=_FakeFetcher(200, _ok_body()), notifier=_Recorder())
    finally:
        tool._browser_cookie_string = real_browser
    check("[26] 反面对照：--login --dry-run → 文件字节一个都没动",
          open(cfg3, "rb").read() == before3, "")


# ---------------------------------------------------------------------------
# [27] G1/G4：告警投递是**持久化义务**——投递失败会被重试、成功只补投一次、SystemExit 也不丢
# ---------------------------------------------------------------------------
def test_alert_delivery_is_durable():
    print("\n[27] G1/G4: 投递失败的告警是持久化债务（重试 / 恰好一次 / 不重复 / SystemExit 兜住）")
    check("[27] 场景自证：存在可 grep 的『未送达』日志标记常量",
          isinstance(getattr(tool, "PENDING_ALERT_MARKER", None), str)
          and str(tool.PENDING_ALERT_MARKER).strip() != "",
          repr(getattr(tool, "PENDING_ALERT_MARKER", None)))
    marker = tool.PENDING_ALERT_MARKER

    # ===== 主场景（题目给的 B1/B2/B3/C1/D1/D2 序列）=====
    # A0 先建立 ok 历史，B1 才是一次**真实的 ok→auth_failed 转换**（而不是「无历史首次失败」）。
    # 全程 notifier 注入、fetcher 注入：一次真实外呼都不会发生。
    tmp = _workdir()
    cfg, state = _cfg_and_state(tmp, "durable.yaml")
    notifier = _FlakyNotifier(working=False)          # 先全程投递失败
    fetcher = _ScriptedFetcher([(200, _ok_body())]
                               + [(401, BODY_CODE_100)] * 3
                               + [(200, _ok_body())] * 3)
    steps = {}

    def run(label):
        handler, records = _log_capture()
        try:
            rc, crash = _check_catching(config_path=cfg, state_path=state,
                                        fetcher=fetcher, notifier=notifier)
        finally:
            tool.LOG.removeHandler(handler)
        steps[label] = {
            "rc": rc, "crash": crash,
            "blob": "\n".join(r.getMessage() for r in records),
            "pending": _state_field(state, "alert_pending")[0],
            "msg": _state_field(state, "alert_message")[0],
        }
        return steps[label]

    a0 = run("A0")
    check("[27] A0 建立 ok 历史：rc==0、不产生任何投递尝试",
          a0["crash"] is None and a0["rc"] == 0 and notifier.attempts == 0,
          "rc=%r crash=%s attempts=%d" % (a0["rc"], a0["crash"], notifier.attempts))
    check("[27] A0 ok 态的状态文件 alert_pending=false（无债务）", a0["pending"] is False,
          "alert_pending=%r" % (a0["pending"],))

    # --- B1：真正的 ok→auth_failed 转换，投递失败 ---
    b1 = run("B1")
    check("[27] B1 ok→auth_failed：rc==2（0/2/3 契约不变）、投递尝试 1 次、送达 0 条",
          b1["crash"] is None and b1["rc"] == 2 and notifier.attempts == 1
          and notifier.delivered == [],
          "rc=%r attempts=%d delivered=%d" % (b1["rc"], notifier.attempts, len(notifier.delivered)))
    check("[27] G1 B1 投递失败 → 状态文件**显式字段** alert_pending=true",
          b1["pending"] is True, "alert_pending=%r" % (b1["pending"],))
    check("[27] G1 B1 未送达的告警原文被持久化（补投要有原文可用）",
          isinstance(b1["msg"], str) and "--login" in b1["msg"], "alert_message=%r" % (b1["msg"],))
    check("[27] G1 B1 投递失败当次就有『未送达』日志标记（不是等到下一次运行才可见）",
          marker in b1["blob"], b1["blob"][-500:])

    # --- B2：状态与上次完全相同（should_alert 返回 False），但必须**重试投递** ---
    b2 = run("B2")
    check("[27] B2 同类别重复：rc==2、**仍重试投递**（累计尝试 2 次）、仍 0 送达",
          b2["crash"] is None and b2["rc"] == 2 and notifier.attempts == 2
          and notifier.delivered == [],
          "rc=%r attempts=%d" % (b2["rc"], notifier.attempts))
    check("[27] G1 B2 日志里出现『未送达』标记（每次运行都可见，不再只剩『不重复告警』）",
          marker in b2["blob"], b2["blob"][-500:])

    b3 = run("B3")
    check("[27] B3 继续重试（累计尝试 3 次、仍 0 送达）",
          b3["crash"] is None and b3["rc"] == 2 and notifier.attempts == 3
          and notifier.delivered == [],
          "rc=%r attempts=%d" % (b3["rc"], notifier.attempts))
    check("[27] G1 B3 日志里同样出现『未送达』标记", marker in b3["blob"], b3["blob"][-500:])

    # --- C1：恢复为 ok，恢复通知走**同一个**重试机制（投递仍然失败）---
    c1 = run("C1")
    check("[27] C1 auth_failed→ok：rc==0、恢复通知也被尝试投递（累计 4 次）、送达仍 0 条",
          c1["crash"] is None and c1["rc"] == 0 and notifier.attempts == 4
          and notifier.delivered == [],
          "rc=%r attempts=%d" % (c1["rc"], notifier.attempts))
    check("[27] G1 C1 恢复通知未送达 → alert_pending 仍 true，且存的是**恢复**通知原文",
          c1["pending"] is True and isinstance(c1["msg"], str) and "已恢复" in c1["msg"],
          "pending=%r msg=%r" % (c1["pending"], c1["msg"]))

    # --- D1：投递恢复 + 状态没有变化 → 必须补投，且只补投一次 ---
    notifier.working = True
    d1 = run("D1")
    check("[27] D1 投递恢复 → 补投那条未送达的恢复通知（尝试 5 次、送达 1 条）",
          d1["crash"] is None and d1["rc"] == 0 and notifier.attempts == 5
          and len(notifier.delivered) == 1,
          "rc=%r attempts=%d delivered=%d" % (d1["rc"], notifier.attempts, len(notifier.delivered)))
    check("[27] G1 D1 补投的正是 C1 那条原文（一字不差，不是重造的另一条）",
          notifier.delivered == [c1["msg"]], repr(notifier.delivered))
    check("[27] G1 D1 **送达成功之后**才清标记：alert_pending→false、alert_message→null",
          d1["pending"] is False and d1["msg"] is None,
          "pending=%r msg=%r" % (d1["pending"], d1["msg"]))

    # --- D2：债务已清 → 不得重复投递 ---
    d2 = run("D2")
    check("[27] D2 状态仍是 ok、债务已清 → 不再投递（尝试仍 5 次、送达仍 1 条）——**不重复**",
          d2["crash"] is None and d2["rc"] == 0 and notifier.attempts == 5
          and len(notifier.delivered) == 1,
          "rc=%r attempts=%d delivered=%d" % (d2["rc"], notifier.attempts, len(notifier.delivered)))
    check("[27] G1 全序列**恰好送达 1 条**告警（恰好一次：不重复、不丢失）",
          len(notifier.delivered) == 1 and len(set(notifier.delivered)) == 1,
          "delivered=%r" % (notifier.delivered,))
    check("[27] 退出码全程只有 0/2（投递成败绝不改变退出码契约）",
          [steps[k]["rc"] for k in ("A0", "B1", "B2", "B3", "C1", "D1", "D2")] == [0, 2, 2, 2, 0, 0, 0],
          repr([steps[k]["rc"] for k in ("A0", "B1", "B2", "B3", "C1", "D1", "D2")]))

    # ===== 子场景：投递在**状态没有变化**时恢复 → 那条丢失的失败告警必须被补投 =====
    # 这一条是「不丢失」的直接证据：B1 那条告警在投递恢复后必须原样落地，而不是被跳过。
    tmp2 = _workdir()
    cfg2, state2 = _cfg_and_state(tmp2, "durable_same_state.yaml")
    n2 = _FlakyNotifier(working=False)
    f2 = _ScriptedFetcher([(200, _ok_body())] + [(401, BODY_CODE_100)] * 4)

    rc_ok2, crash_ok2 = _check_catching(config_path=cfg2, state_path=state2,
                                        fetcher=f2, notifier=n2)
    check("[27] 子场景前置：ok 历史建立 rc==0", crash_ok2 is None and rc_ok2 == 0,
          "rc=%r crash=%s" % (rc_ok2, crash_ok2))
    rc_b2, crash_b2 = _check_catching(config_path=cfg2, state_path=state2,
                                      fetcher=f2, notifier=n2)
    lost = _state_field(state2, "alert_message")[0]
    check("[27] 子场景 B1 转换发生但投递失败：rc==2、尝试 1 次、送达 0 条、pending=true",
          crash_b2 is None and rc_b2 == 2 and n2.attempts == 1 and n2.delivered == []
          and _state_field(state2, "alert_pending")[0] is True,
          "rc=%r attempts=%d pending=%r" % (rc_b2, n2.attempts,
                                            _state_field(state2, "alert_pending")[0]))

    n2.working = True     # 投递恢复；但**状态依然是 auth_failed**（没有任何新转换）
    rc_r, crash_r = _check_catching(config_path=cfg2, state_path=state2,
                                    fetcher=f2, notifier=n2)
    check("[27] G1 子场景 投递恢复且状态未变 → 那条丢失的告警被补投（恰好 1 条）",
          crash_r is None and rc_r == 2 and len(n2.delivered) == 1,
          "rc=%r attempts=%d delivered=%r" % (rc_r, n2.attempts, n2.delivered))
    check("[27] G1 子场景 补投的就是 B1 那条告警原文（**没有丢失**）",
          n2.delivered == [lost], "delivered=%r lost=%r" % (n2.delivered, lost))
    check("[27] G1 子场景 补投后 alert_pending 被清掉",
          _state_field(state2, "alert_pending")[0] is False,
          "alert_pending=%r" % (_state_field(state2, "alert_pending")[0],))
    attempts_before = n2.attempts
    rc_x, crash_x = _check_catching(config_path=cfg2, state_path=state2,
                                    fetcher=f2, notifier=n2)
    check("[27] G1 子场景 债务已清后再跑一次 → 不再重复投递（不重复）",
          crash_x is None and rc_x == 2 and n2.attempts == attempts_before
          and len(n2.delivered) == 1,
          "rc=%r attempts=%d (was %d) delivered=%d"
          % (rc_x, n2.attempts, attempts_before, len(n2.delivered)))

    # ===== G4：notifier 抛 SystemExit =====
    # `except Exception` **故意不接** SystemExit，所以它会照常逃出 check()；但那一刻
    # alert_pending=true 已经在盘上 ⇒ 下一次运行照样补投（这正是「状态写了、rc 没返回」
    # 那条路径，不需要也不应该靠 catch BaseException 去堵）。
    tmp3 = _workdir()
    cfg3, state3 = _cfg_and_state(tmp3, "durable_sysexit.yaml")
    f3 = _ScriptedFetcher([(200, _ok_body())] + [(401, BODY_CODE_100)] * 2)
    rc_ok3, crash_ok3 = _check_catching(config_path=cfg3, state_path=state3,
                                        fetcher=f3, notifier=_Recorder())
    check("[27] G4 前置：ok 历史建立 rc==0", crash_ok3 is None and rc_ok3 == 0,
          "rc=%r crash=%s" % (rc_ok3, crash_ok3))

    def exiting_notifier(_message):
        raise SystemExit(7)

    rc_exit, crash_exit = _check_catching_base(config_path=cfg3, state_path=state3,
                                               fetcher=f3, notifier=exiting_notifier)
    check("[27] G4 SystemExit 照常逃出 check()（没有被 catch BaseException 吞掉）",
          rc_exit is None and crash_exit is not None and "SystemExit" in crash_exit,
          "rc=%r crash=%r" % (rc_exit, crash_exit))
    check("[27] G4 逃出时**状态已落盘**且带 alert_pending=true（『状态写了、rc 没返回』）",
          _state_field(state3, "status")[0] == "auth_failed"
          and _state_field(state3, "alert_pending")[0] is True,
          "status=%r pending=%r" % (_state_field(state3, "status")[0],
                                    _state_field(state3, "alert_pending")[0]))
    g4_msg = _state_field(state3, "alert_message")[0]

    handler3, records3 = _log_capture()
    rec3 = _Recorder()
    try:
        rc_retry, crash_retry = _check_catching(config_path=cfg3, state_path=state3,
                                                fetcher=f3, notifier=rec3)
    finally:
        tool.LOG.removeHandler(handler3)
    blob3 = "\n".join(r.getMessage() for r in records3)
    check("[27] G4 下一次运行补投那条被 SystemExit 打断的告警（恰好 1 条）",
          crash_retry is None and rc_retry == 2 and len(rec3.messages) == 1,
          "rc=%r n=%d crash=%s" % (rc_retry, len(rec3.messages), crash_retry))
    check("[27] G4 补投的原文与逃出前落盘的那条一致，且点名 --login",
          rec3.messages == [g4_msg] and "--login" in (g4_msg or ""),
          "delivered=%r recorded=%r" % (rec3.messages, g4_msg))
    check("[27] G4 补投成功 → alert_pending → false",
          _state_field(state3, "alert_pending")[0] is False,
          "alert_pending=%r" % (_state_field(state3, "alert_pending")[0],))
    check("[27] G4 补投那次运行日志里出现『未送达』标记（运维可见）",
          marker in blob3, blob3[-500:])


def main():
    print("=" * 70)
    print("知乎 Cookie 工具行为级测试（离线）：写入守卫 / EOL / 幂等 / 回读校验 / 状态变化告警")
    print("=" * 70)

    if not os.path.exists(REAL_YAML):
        print("  [FAIL] 前置：真实 config/zhihu.yaml 不存在，无法验证写回保真度")
        return 1

    test_import_side_effects()
    test_parse_format()
    test_write_only_auth_line()
    test_eol_preserved()
    test_idempotent()
    test_write_side_effects_locked()
    test_guard_rejects()
    test_readback_verification()
    test_notify_only_on_state_change()
    test_exit_codes_and_notify()
    test_transport_error()
    test_dry_run()
    test_state_path_ignored()
    test_d3_transactional_rejections()
    test_refresh_write_decision()
    test_login_refresh_alert_path_offline()
    test_non200_statuses()
    test_401_without_code()
    test_state_path_blocked_by_file()
    test_tool_wiring_locks()
    test_fake_notifier_is_the_one_used()
    test_no_network_egress()
    test_corrupt_state_file_is_visible()
    test_alert_delivery_failure_is_contained()
    test_deep_yaml_is_config_error()
    test_login_refresh_writeback_is_observable()
    test_alert_delivery_is_durable()
    test_real_config_untouched()

    print("=" * 70)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
