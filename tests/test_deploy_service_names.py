#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy.sh 服务名接线锁（docker-compose 服务名引用 vs docker-compose.yml 定义）。

背景（本项目的「静默失效」坑）：
  deploy.sh 曾经做 `docker-compose ps api` / `ps celery-worker` 健康检查，
  但 docker-compose.yml 的 services 只有 apiserver/redis/mongodb/playwright
  ⇒ `api`、`celery-worker` 都不存在，这两个检查**永远不可能 Up、也不报错**。
  「检查写了、但永远不成立」这类坑只能靠**机器锁**防住，不能靠人眼。

本测试做三件事（离线、纯标准库；读 compose 优先 yaml、缺库回退最小缩进解析）：
  [1] 解析 docker-compose.yml 的 services 集合，并**断言恰为 4 个**且等于期望集合
      —— 防「解析失败得到空集 → 所有断言真空通过」（`all([]) == True` 是踩过的坑）。
  [2] 从 deploy.sh **代码行**里抽出所有 `docker-compose <子命令> <服务名>` 的服务名引用，
      断言**每一个**都在 [1] 的集合内；并**打印实际抽到的引用清单**（抽不到即可见）。
      · 注释行（`#`）与行内注释不参与——否则「注释里提到旧服务名」会误报。
      · shell 元字符（`|&;<>()`）截断命令——避免把 `... redis | grep` 的 `grep` 当服务名。
      · `down/up/build/ps/logs/...` 等**子命令本身**绝不当作服务名；服务名只来自
        **位置参数**（见 `test_global_subcommands_not_services` 的显式对照，非「不出错就绿」）。
  [3] 鉴别力自证：临时副本里把某服务名改回 `api` → 锁必变红；只改注释 → 锁仍绿。

环境变量（内部用，防递归）：
  DEPLOY_SVCNAMES_CHILD=1  标记变异自证子进程（跳过自证自身，防递归）

退出码：0 = 全部通过；1 = 有失败。

    python tests/test_deploy_service_names.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = os.path.join(ROOT, "docker-compose.yml")
DEPLOY = os.path.join(ROOT, "deploy.sh")

IS_CHILD = os.environ.get("DEPLOY_SVCNAMES_CHILD") == "1"

# docker-compose.yml 的 services 期望集合（本仓库事实；变更需同步本锁）
EXPECTED_SERVICES = {"apiserver", "redis", "mongodb", "playwright"}

# 已知的 docker-compose 子命令（用于把「子命令」与「服务名」显式区分开）
KNOWN_SUBCMDS = {
    "up", "down", "build", "ps", "logs", "restart", "stop", "start", "rm",
    "kill", "pause", "unpause", "pull", "push", "create", "top", "port",
    "exec", "run", "scale", "events", "images", "config", "version", "help",
    "cp", "ls", "wait", "watch", "publish",
}
# 这些全局选项带一个「值」，其值不能被误当位置参数（服务名）
VALUE_FLAGS = {"-f", "--file", "-p", "--project-name", "--project-directory",
               "--env-file", "--profile", "--ansi", "--log-level"}

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
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# [1] 解析 docker-compose.yml 的 services
# ---------------------------------------------------------------------------
def _minimal_services_parse(text):
    """最小缩进解析：定位顶层 `services:`，取其下 2 空格缩进的键。"""
    services = set()
    in_services = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if re.match(r"^services:\s*$", raw):
            in_services = True
            continue
        if in_services:
            # 顶层键（无缩进）出现 → services 段结束
            if re.match(r"^\S", raw):
                break
            m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", raw)
            if m:
                services.add(m.group(1))
    return services


def parse_compose_services(text):
    """优先 PyYAML；缺库/失败回退最小缩进解析。返回 (services_set, how)。"""
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
        svc = data.get("services", {}) or {}
        return set(svc.keys()), "yaml"
    except Exception:
        return _minimal_services_parse(text), "minimal"


def test_compose_services():
    print("\n[1] 解析 docker-compose.yml 的 services（恰为 4 个）")
    text = read_text(COMPOSE)
    services, how = parse_compose_services(text)
    print("  · 解析方式 = %s" % how)
    print("  · services = %s" % sorted(services))
    check("解析到恰好 4 个服务（防空集真空通过）", len(services) == 4,
          "got=%d %s" % (len(services), sorted(services)))
    check("services 集合 == 期望（apiserver/redis/mongodb/playwright）",
          services == EXPECTED_SERVICES,
          "got=%s expect=%s" % (sorted(services), sorted(EXPECTED_SERVICES)))
    # 缺库回退路径必须与 yaml 等价（独立断言，防止「有 yaml 时绿、无 yaml 时崩/空集」）
    minimal = _minimal_services_parse(text)
    print("  · 最小缩进解析 = %s" % sorted(minimal))
    check("最小缩进解析 == 期望集合（缺库回退可用）",
          minimal == EXPECTED_SERVICES,
          "minimal=%s expect=%s" % (sorted(minimal), sorted(EXPECTED_SERVICES)))
    return services


# ---------------------------------------------------------------------------
# [2] 从 deploy.sh 抽出服务名引用
# ---------------------------------------------------------------------------
def _code_lines(text):
    """返回 [(lineno, 去除行内注释后的代码文本)]，跳过整行注释与空行。"""
    out = []
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        # 去行内注释（# 之后；本文件无字符串内含 # 的情况）
        code = raw.split("#", 1)[0]
        if code.strip():
            out.append((i, code))
    return out


_META_RE = re.compile(r"[|&;<>()`]")


def extract_compose_service_refs(text):
    """抽出所有 docker-compose <子命令> <位置参数...> 中的位置参数（服务名候选）。

    Returns:
        list[(lineno, subcmd, name)]

    解析规则（显式区分「子命令」「全局选项」「服务名」）：
      · 子命令 = 跳过**前置全局选项**后的第一个词；不在 KNOWN_SUBCMDS 则不是命令。
      · 前置全局选项里，`-f/--file` 等**带值**，连带吞掉其值；其余只吞自身。
      · 子命令之后的 `-x/--xx` 一律视为**无值开关**（如 `logs -f` 的 follow），
        绝不吞后面的服务名（这是 compose 的语义：`-f` 在子命令后不再表 file）。
      · 服务名只来自**位置参数**；子命令本身永不当作服务名。
    """
    refs = []
    for lineno, code in _code_lines(text):
        for m in re.finditer(r"\bdocker-compose\b", code):
            rest = code[m.end():]
            # shell 元字符截断（避免把 `| grep` 等卷入）
            cmd = _META_RE.split(rest)[0].strip()
            toks = [t.strip("\"'") for t in cmd.split() if t.strip("\"'")]
            if not toks:
                continue

            # 阶段1：吞掉前置全局选项（带值者连值一起吞），定位子命令
            i = 0
            while i < len(toks) and toks[i].startswith("-"):
                i += 2 if toks[i] in VALUE_FLAGS else 1
            if i >= len(toks):
                continue
            subcmd = toks[i]
            if subcmd not in KNOWN_SUBCMDS:
                # 不是合法子命令（例如 `command -v docker-compose &>` 的残留）→ 跳过
                continue

            # 阶段2：子命令之后，无值开关跳过，其余位置参数即服务名候选
            for a in toks[i + 1:]:
                if a.startswith("-"):
                    continue  # 子命令后的开关一律无值（如 logs -f）
                name = a.split("=", 1)[0]  # 兼容 --scale redis=2
                refs.append((lineno, subcmd, name))
    return refs


def test_deploy_refs(services):
    print("\n[2] deploy.sh 的服务名引用 ⊆ compose services")
    text = read_text(DEPLOY)
    refs = extract_compose_service_refs(text)

    print("  · 从 deploy.sh 抽到的服务名引用（%d 个）：" % len(refs))
    for lineno, subcmd, name in refs:
        print("      L%-4d docker-compose %-9s %s" % (lineno, subcmd, name))

    check("至少抽到 1 个服务名引用（防「抽不到→真空通过」）", len(refs) >= 1,
          "got=%d" % len(refs))

    bad = [(ln, sc, n) for (ln, sc, n) in refs if n not in services]
    check("每个引用都在 compose services 内（无不存在服务名）", not bad,
          "越界引用=%s" % bad)
    for lineno, subcmd, name in bad:
        check("L%d docker-compose %s %s 存在" % (lineno, subcmd, name),
              False, "%s 不在 %s" % (name, sorted(services)))


def test_global_subcommands_not_services():
    print("\n[2b] 显式对照：全局子命令/带服务参数 不被误判")
    globals_sample = (
        "docker-compose down\n"
        "docker-compose build\n"
        "docker-compose up -d\n"
        "docker-compose ps\n"
        "docker-compose logs -f\n"
        "docker-compose restart\n"
    )
    got = extract_compose_service_refs(globals_sample)
    print("  · 全局子命令样本 -> 抽出 %s（应为空）" % got)
    check("全局子命令（down/build/up -d/ps/logs -f/restart）抽出为空", got == [],
          "got=%s" % got)

    with_service = "docker-compose ps redis\ndocker-compose logs -f apiserver\n"
    got2 = extract_compose_service_refs(with_service)
    names = sorted({n for (_l, _s, n) in got2})
    print("  · 带服务参数样本 -> %s（应为 ['apiserver','redis']）" % names)
    check("带服务参数时抽出正确服务名", names == ["apiserver", "redis"],
          "got=%s" % names)

    # shell 管道不得把后续命令卷入
    piped = "docker-compose ps redis | grep -q \"Up\"\n"
    got3 = extract_compose_service_refs(piped)
    check("管道 `| grep` 不被当成服务名", [n for (_l, _s, n) in got3] == ["redis"],
          "got=%s" % got3)

    # 注释里的旧服务名不得被抽到
    commented = "# docker-compose ps celery-worker\ndocker-compose ps apiserver\n"
    got4 = extract_compose_service_refs(commented)
    check("注释行里的旧服务名不被抽到", [n for (_l, _s, n) in got4] == ["apiserver"],
          "got=%s" % got4)


# ---------------------------------------------------------------------------
# [3] 鉴别力自证（仅父进程；子进程跳过防递归）
# ---------------------------------------------------------------------------
_MIN_FILES = ["docker-compose.yml", "deploy.sh", "tests/test_deploy_service_names.py"]


def _copy_min(dst):
    for rel in _MIN_FILES:
        src = os.path.join(ROOT, rel)
        tgt = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        shutil.copy2(src, tgt)


def _run_child(tree):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["DEPLOY_SVCNAMES_CHILD"] = "1"
    proc = subprocess.run(
        [sys.executable, os.path.join(tree, "tests", "test_deploy_service_names.py")],
        cwd=tree, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def test_selfproof():
    print("\n[3] 鉴别力自证：改回 api -> 红；只改注释 -> 绿")

    # 对照：未变异 -> 绿
    ctrl = tempfile.mkdtemp(prefix="depsvc_ctl_")
    try:
        _copy_min(ctrl)
        rc, out = _run_child(ctrl)
        check("对照：未变异副本 -> 绿(rc=0)", rc == 0,
              "rc=%s 末行=%s" % (rc, out.strip().splitlines()[-1:]))
    finally:
        shutil.rmtree(ctrl, ignore_errors=True)

    # 变异：把 `docker-compose ps apiserver` 改成不存在的 `api` -> 红
    work = tempfile.mkdtemp(prefix="depsvc_mut_")
    try:
        _copy_min(work)
        dpath = os.path.join(work, "deploy.sh")
        src = read_text(dpath)
        old = "docker-compose ps apiserver"
        check("变异靶点存在且唯一", src.count(old) == 1, "count=%d" % src.count(old))
        write_text(dpath, src.replace(old, "docker-compose ps api", 1))
        rc, out = _run_child(work)
        check("变异[改回 api] -> 锁变红(rc!=0)", rc != 0,
              "rc=%s 末行=%s" % (rc, out.strip().splitlines()[-1:]))
        check("红时文案点名 api/不存在",
              "api" in out and ("不存在" in out or "越界" in out),
              out.strip().splitlines()[-3:])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 无害：只改注释 -> 仍绿
    work2 = tempfile.mkdtemp(prefix="depsvc_cmt_")
    try:
        _copy_min(work2)
        dpath = os.path.join(work2, "deploy.sh")
        src = read_text(dpath)
        marker = "#!/bin/bash"
        check("注释变异靶点存在", marker in src)
        write_text(dpath, src.replace(marker, "#!/bin/bash  # 注释变异", 1))
        rc, out = _run_child(work2)
        check("变异[只改注释] -> 仍绿(rc=0)", rc == 0,
              "rc=%s 末行=%s" % (rc, out.strip().splitlines()[-1:]))
    finally:
        shutil.rmtree(work2, ignore_errors=True)


def main():
    print("=" * 66)
    print("deploy.sh 服务名接线锁  [mode=%s]" % ("CHILD" if IS_CHILD else "FULL"))
    print("=" * 66)

    services = test_compose_services()
    test_deploy_refs(services)
    test_global_subcommands_not_services()
    if not IS_CHILD:
        test_selfproof()

    print("\n" + "=" * 66)
    print("结果: %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    for f in FAILED:
        print("  [FAIL] %s" % f)
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
