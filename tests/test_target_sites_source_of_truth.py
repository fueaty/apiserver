#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""目标站点「单一事实来源」回归测试

覆盖事故：`config/sites.yaml` 里把站点设为 `enabled: true`，但
`script/collection_pipeline.py` 用一份**写死的 site_code 白名单**调用采集引擎，
导致新启用的站点（thepaper）静默 0 条入库、且不报错。

包含四部分：
  [A] 静态守卫（AST）：`collection_pipeline.py` 的 `collection_params` 字典
      不得再出现 `site_code` 的白名单字面量（防止有人把它写回来）。
  [B] 行为断言：直接驱动 `CollectionEngine._get_target_sites`，证明
      ① 传 None        → 返回全部 enabled（排除 enabled:false）；
      ② 传 ["a","bogus"] → 只返回 a，**且真的发出 warning**（含被丢弃的 code）；
      ③ enabled:false 的站点被排除；显式点名它 → 被丢弃（空）并升级为 error。
  [D] 真配置交叉验证：读取真实 `config/sites.yaml`，断言
      `_get_target_sites(None)` 恰好等于 enabled 集合，且**包含 'thepaper'**。

全部为真断言，退出码 = 1 if FAILED else 0。

    python tests/test_target_sites_source_of_truth.py
"""

import ast
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------------------
# 被测对象：直接驱动 CollectionEngine 的方法。
# 用 object.__new__ 绕过 __init__（避免拉 pydantic/yaml/文件等重依赖），
# 手工塞入受控的 sites_config —— 但要测的 _get_target_sites 行为本身**不打桩**。
# ---------------------------------------------------------------------------
def _engine_with(sites_config):
    from app.services.collection.engine import CollectionEngine
    eng = object.__new__(CollectionEngine)
    eng.sites_config = sites_config
    return eng


def _capture_engine_logs():
    """在 engine 模块使用的 logger 上挂一个内存 handler。

    返回 (records, detach)。records 是 logging.LogRecord 列表；调用 detach() 还原。
    """
    import app.services.collection.engine as engine_mod

    records = []

    class _MemHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _MemHandler()
    handler.setLevel(logging.DEBUG)
    lg = engine_mod.logger
    prev_level, prev_prop = lg.level, lg.propagate
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False

    def detach():
        lg.removeHandler(handler)
        lg.setLevel(prev_level)
        lg.propagate = prev_prop

    return records, detach


# ---------------------------------------------------------------------------
# [A] 静态守卫
# ---------------------------------------------------------------------------
def test_static_guard():
    print("\n[A] 静态守卫：collection_pipeline.py 不得写死 site_code 白名单")
    path = os.path.join(ROOT, "script", "collection_pipeline.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)

    cp_dict = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "collection_params" \
                        and isinstance(node.value, ast.Dict):
                    cp_dict = node.value

    check("A1 找到 collection_params 字典字面量", cp_dict is not None, "未找到")

    if cp_dict is None:
        return

    keys = [
        (k.value if isinstance(k, ast.Constant) else "<%s>" % type(k).__name__)
        for k in cp_dict.keys
    ]
    check("A2 collection_params 键里没有 'site_code'（禁止把白名单写回来）",
          "site_code" not in keys, f"keys={keys}")
    check("A3 collection_params 保留 'format' 键", "format" in keys, f"keys={keys}")

    bad = []
    for k, v in zip(cp_dict.keys, cp_dict.values):
        if isinstance(k, ast.Constant) and k.value == "site_code" and isinstance(v, ast.List):
            bad.append(ast.dump(v)[:80])
    check("A4 不存在 site_code=<list 字面量>", not bad, f"bad={bad}")


# ---------------------------------------------------------------------------
# [B] 行为断言
# ---------------------------------------------------------------------------
def test_behavior():
    print("\n[B] 行为：_get_target_sites 的收窄/丢弃/告警")
    cfg = {
        "weibo": {"enabled": True},
        "baidu": {"enabled": True},
        "zhihu": {"enabled": False},
    }
    eng = _engine_with(cfg)

    got1 = eng._get_target_sites(None)
    check("B1 传 None → 返回全部 enabled（排除 enabled:false）",
          got1 == ["weibo", "baidu"], f"got={got1}")

    records2, detach2 = _capture_engine_logs()
    try:
        got2 = eng._get_target_sites(["weibo", "bogus"])
    finally:
        detach2()
    check("B2 传 ['weibo','bogus'] → 只返回 weibo", got2 == ["weibo"], f"got={got2}")
    warn_hit = any(
        r.levelno >= logging.WARNING and "bogus" in r.getMessage() for r in records2
    )
    check("B2 被丢弃的 code **真的发出了 warning**（含该 code）",
          warn_hit, f"records={[(r.levelname, r.getMessage()) for r in records2]}")

    records3, detach3 = _capture_engine_logs()
    try:
        got3 = eng._get_target_sites(["zhihu"])
    finally:
        detach3()
    check("B3 显式点名 enabled:false 的站点 → 被排除（返回空）", got3 == [], f"got={got3}")
    err_hit = any(r.levelno >= logging.ERROR for r in records3)
    check("B3 目标全不匹配 → 升级为 error 日志",
          err_hit, f"records={[r.levelname for r in records3]}")

    # 字符串输入形式也应收窄
    records4, detach4 = _capture_engine_logs()
    try:
        got4 = eng._get_target_sites("weibo,baidu")
    finally:
        detach4()
    check("B4 字符串输入 'weibo,baidu' → ['weibo','baidu']",
          got4 == ["weibo", "baidu"], f"got={got4}")


# ---------------------------------------------------------------------------
# [D] 真配置交叉验证
# ---------------------------------------------------------------------------
def test_real_config():
    print("\n[D] 用真实 config/sites.yaml 交叉验证")
    import yaml

    cfg_path = os.path.join(ROOT, "config", "sites.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    sites = data.get("sites", {}) or {}
    enabled = [k for k, v in sites.items() if (v or {}).get("enabled", True)]

    check("D0 真实 sites.yaml 解析出 sites 段", bool(sites), "sites 段为空")

    eng = _engine_with(sites)
    got = eng._get_target_sites(None)
    check("D1 _get_target_sites(None) 恰等于 sites.yaml 的 enabled 集合",
          set(got) == set(enabled),
          f"got={sorted(got)} enabled={sorted(enabled)}")
    check("D2 enabled 集合包含 'thepaper'（(g) 不会再漏采的前提）",
          "thepaper" in enabled and "thepaper" in got,
          f"enabled={sorted(enabled)}")

    expected = {
        "people_daily", "xinhua", "cctv", "thepaper", "weibo",
        "baidu", "zhihu", "tech_36kr", "xiaohongshu",
    }
    check("D3 enabled 顶层采集站点恰为设计中的 9 个",
          set(enabled) == expected,
          f"enabled={sorted(enabled)} expected={sorted(expected)}")


def main():
    print("=" * 66)
    print("目标站点单一事实来源回归测试")
    print("=" * 66)
    test_static_guard()
    test_behavior()
    test_real_config()
    print("\n" + "=" * 66)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
