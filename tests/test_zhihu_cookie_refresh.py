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


def _cfg_and_state(tmp, name="zhihu.yaml"):
    cfg = _write_text(os.path.join(tmp, name), _sanitized_real_text())
    return cfg, os.path.join(tmp, "state_%s.json" % name)


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
    check("[7] 状态文件已写入且 status=auth_failed",
          json.load(open(state, encoding="utf-8")).get("status") == "auth_failed", "")
    raw_state = open(state, encoding="utf-8").read()
    check("[7] 状态文件不含 cookie 明文",
          "DUMMY_COOKIE" not in raw_state and "z_c0=" not in raw_state, "")

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
    check("[9] 状态文件 status=ok", json.load(open(state2, encoding="utf-8")).get("status") == "ok", "")

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
    check("[10] 缺凭证 → 状态文件 status=auth_failed",
          json.load(open(state3, encoding="utf-8")).get("status") == "auth_failed", "")
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

    wrote_same = tool.apply_refreshed_cookie(cfg, NEW_COOKIE)
    check("[14] 串未变化 → 返回 False（跳过写回）", wrote_same is False, repr(wrote_same))
    check("[14] 串未变化 → 文件逐字节未动", open(cfg, "rb").read() == before, "")

    changed = NEW_COOKIE + "; extra=1"
    wrote_new = tool.apply_refreshed_cookie(cfg, changed)
    check("[14] 串有变化 → 返回 True（已落盘）", wrote_new is True, repr(wrote_new))
    check("[14] 串有变化 → 回读即为新值", cookie_store.read_cookie_auth(cfg) == changed, "")
    check("[14] 串有变化 → 仍只改 auth 行（行数不变）",
          len(open(cfg, "rb").read().splitlines(keepends=True)) == len(before.splitlines(keepends=True)),
          "")

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
    check("[15] --refresh 的失败走了**注入的** notifier（1 次告警）", len(rec.messages) == 1,
          "n=%d" % len(rec.messages))
    check("[15] 注入的 state_path 被真实使用（state=auth_failed）",
          json.load(open(state, encoding="utf-8")).get("status") == "auth_failed", "")
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
        check("[16] HTTP %d 状态文件 status=%s" % (status, expect_state),
              os.path.exists(state)
              and json.load(open(state, encoding="utf-8")).get("status") == expect_state, "")

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
        check("[17] 401（%s）→ 状态文件 status=auth_failed" % label,
              json.load(open(state, encoding="utf-8")).get("status") == "auth_failed", "")


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
    check("[20] D4 tool:507 此时就地校验确实通过了（状态文件被写成 ok）",
          json.load(open(state3, encoding="utf-8")).get("status") == "ok", "")


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
    test_real_config_untouched()

    print("=" * 70)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
