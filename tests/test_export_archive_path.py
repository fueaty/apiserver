#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归档落点回归锁（script/export_today_headlines.py）

背景（设计 §附录 A）：该脚本此前用 `f"../{today}_headlines_data.json"` 依赖 **cwd**。
生产入口 run_daily_task.sh 先 `cd /opt/apiserver`，此时 `..` = `/opt` ⇒ 快照落到
`/opt` 而不是 `<root>`，与归档侧（`<root>` → `<root>/history_data`）不一致 ⇒ 归档链静默断开。
修法：把输出路径锚到 `PROJECT_ROOT = Path(__file__).resolve().parent.parent`。

本测试是它的**回归锁**（纯标准库、离线、`rc = 1 if FAILED else 0`）：
  [1] 源码锁：真实文件代码行里不得再出现 `f"../{today}` / `f"../{output_file}"`。
  [2] 行为级集成：临时树里**按字节复制真实脚本** + 桩 app 依赖，分别在
      cwd=<proj> 与 cwd=<proj>/script 两个 cwd 下**运行真实脚本**，断言两次都在
      <proj> 根生成 `{today}_headlines_data.json`，且 <proj>/../{today}_... **不存在**。
  [3] E1 变异：把 `return str(PROJECT_ROOT / ...)` 改成 `return str(Path("..") / ...)`
      ⇒ [2] 必须 FAIL（子进程跑本文件）。
  [4] E2 无害对照：只改注释 ⇒ 全绿。

环境变量 EXPORT_ARCHIVE_CHILD=1 标记变异子进程（跳过 [3]/[4]，防递归）。

    python tests/test_export_archive_path.py
"""

import datetime
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "script", "export_today_headlines.py")
IS_CHILD = os.environ.get("EXPORT_ARCHIVE_CHILD") == "1"

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [OK] %s" % name)
    else:
        FAILED.append("%s :: %s" % (name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def code_only(text):
    """只保留会真正执行的代码行（去掉空行与整行注释），避免注释里的历史说明误伤。"""
    return "\n".join(ln for ln in text.splitlines()
                     if ln.strip() and not ln.strip().startswith("#"))


# —— 桩 app 模块（避免拉入飞书/网络依赖）——
STUB_FEISHU = (
    "class FeishuService:\n"
    "    def __init__(self, *a, **k):\n"
    "        pass\n"
    "    async def list_records(self, app_token, table_id, page_size=500, page_token=None):\n"
    "        return {'items': []}\n"
)
STUB_CONFIG = (
    "class _ConfigManager:\n"
    "    def get_credentials(self):\n"
    "        return {'feishu': {'tables': {'headlines': {\n"
    "            'app_token': 'stub_app', 'table_id': 'stub_tbl'}}}}\n"
    "config_manager = _ConfigManager()\n"
)
STUB_NOOP = "def %s(*a, **k):\n    return None\n"


def build_proj(dst):
    """在 dst 里造一个假项目：<dst>/script/真实脚本 + <dst>/app 桩。"""
    # 按字节复制真实脚本
    write_text(os.path.join(dst, "script", "export_today_headlines.py"),
               read_text(EXPORT))
    write_text(os.path.join(dst, "app", "__init__.py"), "")
    write_text(os.path.join(dst, "app", "services", "__init__.py"), "")
    write_text(os.path.join(dst, "app", "services", "feishu", "__init__.py"), "")
    write_text(os.path.join(dst, "app", "services", "feishu", "feishu_service.py"), STUB_FEISHU)
    write_text(os.path.join(dst, "app", "core", "__init__.py"), "")
    write_text(os.path.join(dst, "app", "core", "config.py"), STUB_CONFIG)
    write_text(os.path.join(dst, "app", "wework", "__init__.py"), "")
    write_text(os.path.join(dst, "app", "wework", "file_push.py"), STUB_NOOP % "send_file_message")
    write_text(os.path.join(dst, "app", "wework", "notification_push.py"), STUB_NOOP % "send_message")


def run_real_script(proj, cwd):
    """以 cwd 运行真实脚本（脚本按字节复制在 proj/script 下）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = proj + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = os.path.join(proj, "script", "export_today_headlines.py")
    proc = subprocess.run([sys.executable, script], cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
def test_source_lock():
    print("\n[1] 源码锁：真实脚本代码行不再依赖 f\"../...\"")
    src = code_only(read_text(EXPORT))
    check("代码行不含 f\"../{today}...\"", 'f"../{today}' not in src,
          [ln for ln in src.splitlines() if 'f"../{today}' in ln])
    check("代码行不含 f\"../{output_file}\"", 'f"../{output_file}"' not in src,
          [ln for ln in src.splitlines() if 'f"../{output_file}"' in ln])
    check("代码行含 PROJECT_ROOT 推导", "Path(__file__).resolve().parent.parent" in src)


def test_behavior():
    print("\n[2] 行为级集成：两个 cwd 都落 <proj> 根，且 <proj>/.. 无落点")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    proj = tempfile.mkdtemp(prefix="export_proj_")
    try:
        build_proj(proj)
        in_root = os.path.join(proj, "%s_headlines_data.json" % today)
        in_parent = os.path.join(os.path.dirname(proj), "%s_headlines_data.json" % today)

        for label, cwd in (("cwd=<proj>", proj), ("cwd=<proj>/script", os.path.join(proj, "script"))):
            if os.path.exists(in_root):
                os.remove(in_root)
            if os.path.exists(in_parent):
                os.remove(in_parent)
            rc, out = run_real_script(proj, cwd)
            check("%s 退出码 0" % label, rc == 0, "rc=%s out=%s" % (rc, out[-200:]))
            check("%s 在 <proj> 根生成 {today}_headlines_data.json" % label,
                  os.path.exists(in_root), "missing=%s" % in_root)
            check("%s <proj>/.. 无 {today}_headlines_data.json（旧 bug 落点）" % label,
                  not os.path.exists(in_parent), "leaked=%s" % in_parent)
    finally:
        shutil.rmtree(proj, ignore_errors=True)


def test_mutation_selfproof():
    print("\n[3/4] 变异自证：E1 断路径 -> 红；E2 只改注释 -> 绿")
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    # E1：把锚到 PROJECT_ROOT 的默认返回改成 Path("..")（相对 cwd）-> [2] 必须 FAIL
    work = tempfile.mkdtemp(prefix="export_mut_e1_")
    try:
        write_text(os.path.join(work, "tests", "test_export_archive_path.py"),
                   read_text(os.path.abspath(__file__)))
        src = read_text(EXPORT)
        old = 'return str(PROJECT_ROOT / f"{today}_headlines_data.json")'
        check("E1 靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
        write_text(os.path.join(work, "script", "export_today_headlines.py"),
                   src.replace(old, 'return str(Path("..") / f"{today}_headlines_data.json")', 1))
        rc, out = _run_child(work)
        check("E1 断路径后 -> 本测试变红", rc != 0, "rc=%s" % rc)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # E2：只改注释 -> 仍绿
    work2 = tempfile.mkdtemp(prefix="export_mut_e2_")
    try:
        write_text(os.path.join(work2, "tests", "test_export_archive_path.py"),
                   read_text(os.path.abspath(__file__)))
        src = read_text(EXPORT)
        write_text(os.path.join(work2, "script", "export_today_headlines.py"),
                   src.replace('"""导出今天采集的数据脚本',
                               '"""导出今天采集的数据脚本（注释变异）', 1))
        rc, out = _run_child(work2)
        check("E2 只改注释 -> 本测试仍绿", rc == 0, "rc=%s out=%s" % (rc, out[-200:]))
    finally:
        shutil.rmtree(work2, ignore_errors=True)


def _run_child(tree_root):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree_root + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["EXPORT_ARCHIVE_CHILD"] = "1"
    proc = subprocess.run(
        [sys.executable, os.path.join(tree_root, "tests", "test_export_archive_path.py")],
        cwd=tree_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def main():
    print("=" * 66)
    print("归档落点回归锁  [mode=%s]" % ("CHILD" if IS_CHILD else "FULL"))
    print("=" * 66)
    test_source_lock()
    test_behavior()
    if not IS_CHILD:
        test_mutation_selfproof()
    print("\n" + "=" * 66)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
