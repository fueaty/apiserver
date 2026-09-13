#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多平台内容发布器回归测试

覆盖缺陷：config/platforms.yaml 声明 6 个平台，但 platforms/ 目录只有 3 个实现，
且 PlatformFactory 用 str.capitalize() 拼类名，对 wechat_public 永远取不到类
（"wechat_public".capitalize() == "Wechat_public" → Wechat_publicPlatform）。

本脚本验证：
  1. 6 个平台模块都能被 PlatformFactory 动态加载并实例化
  2. 类名解析对下划线平台码正确（wechat_public → WechatPublicPlatform）
  3. 命名约定失配时的兜底扫描可用（并且多实现时不误判）
  4. 各平台 _validate_content 的约束分支（长度/图片数）
  5. _map_content 字段映射
  6. publish() 在缺少凭据时优雅失败（不发网络请求）
  7. publish() 对成功/失败响应的解析与 URL 拼装

自带部分第三方依赖桩（aiohttp / app.core.config / app.utils.logger 等），不联网。
但 **PyYAML 不可桩**：`_load_yaml_config` 用真实 `yaml.safe_load` 解析真实
`config/platforms.yaml`，断言依赖的正是**真实配置内容**——给它打桩会让断言退回
与伪造配置比对（把测试弄坏，而非修好）。因此本测试**需已安装 PyYAML（见
requirements.txt）** 方能运行，不保证在未装依赖的干净环境可跑：

    python tests/test_publication_platforms.py
"""

import sys
import os
import types
import json
import asyncio
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(ROOT, "app", "services", "publication")
PLATFORMS_DIR = os.path.join(PKG_DIR, "platforms")

# ---------------------------------------------------------------------------
# 1. 第三方依赖桩
# ---------------------------------------------------------------------------
aiohttp_stub = types.ModuleType("aiohttp")
aiohttp_stub.ClientSession = object
aiohttp_stub.ClientTimeout = lambda total=None, **kw: ("timeout", total)
sys.modules["aiohttp"] = aiohttp_stub

# app 包骨架（避免执行 app/__init__.py 的重量级导入）
for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.utils", os.path.join(ROOT, "app", "utils")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.publication", PKG_DIR),
    ("app.services.publication.platforms", PLATFORMS_DIR),
    ("app.services.feishu", os.path.join(ROOT, "app", "services", "feishu")),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m


class _Logger:
    def __init__(self):
        self.records = []

    def _log(self, level, msg, *a, **kw):
        self.records.append((level, str(msg)))

    def info(self, msg, *a, **kw):
        self._log("INFO", msg)

    def warning(self, msg, *a, **kw):
        self._log("WARNING", msg)

    def error(self, msg, *a, **kw):
        self._log("ERROR", msg)

    def debug(self, msg, *a, **kw):
        self._log("DEBUG", msg)

    def critical(self, msg, *a, **kw):
        self._log("CRITICAL", msg)


LOGGER = _Logger()
logger_stub = types.ModuleType("app.utils.logger")
logger_stub.logger = LOGGER
sys.modules["app.utils.logger"] = logger_stub

config_stub = types.ModuleType("app.core.config")
config_stub.settings = types.SimpleNamespace(PLATFORMS_CONFIG_FILE="config/platforms.yaml")
config_stub.config_manager = types.SimpleNamespace(get_credentials=lambda: {})
sys.modules["app.core.config"] = config_stub

yaml_loader_stub = types.ModuleType("app.utils.yaml_loader")


def _load_yaml_config(path):
    import yaml
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


yaml_loader_stub.load_yaml_config = _load_yaml_config
sys.modules["app.utils.yaml_loader"] = yaml_loader_stub

feishu_svc_stub = types.ModuleType("app.services.feishu.feishu_service")
feishu_svc_stub.FeishuService = type("FeishuService", (), {})
sys.modules["app.services.feishu.feishu_service"] = feishu_svc_stub

# ---------------------------------------------------------------------------
# 2. 直接加载真实源码
# ---------------------------------------------------------------------------
def _load(module_name, rel_path):
    path = os.path.join(ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


base_mod = _load("app.services.publication.platforms.base",
                 os.path.join("app", "services", "publication", "platforms", "base.py"))
manager_mod = _load("app.services.publication.manager",
                    os.path.join("app", "services", "publication", "manager.py"))

BasePlatform = base_mod.BasePlatform
PlatformFactory = manager_mod.PlatformFactory

# ---------------------------------------------------------------------------
# 3. 假会话
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text


class _FakeCtx:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """记录 post 调用的假 aiohttp 会话"""

    def __init__(self, status=200, text="{}"):
        self.resp = FakeResponse(status, text)
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        return _FakeCtx(self.resp)

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# 4. 断言框架
# ---------------------------------------------------------------------------
PASSED = 0
FAILED = []


def check(cond, label, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print("  [PASS] %s" % label)
    else:
        FAILED.append(label + (" :: " + detail if detail else ""))
        print("  [FAIL] %s %s" % (label, (":: " + detail) if detail else ""))


CONFIG = _load_yaml_config("config/platforms.yaml")
PUBLISH_PLATFORMS = CONFIG["publish_platforms"]
EXPECTED_CODES = ["zhihu", "weibo", "juejin", "xiaohongshu", "wechat_public", "toutiao"]

print("=" * 78)
print("多平台内容发布器回归测试")
print("=" * 78)

# ---------------------------------------------------------------------------
print("\n[1] 配置声明 vs 实现文件对齐")
declared = list(PUBLISH_PLATFORMS.keys())
check(declared == EXPECTED_CODES, "platforms.yaml 声明 6 个平台且顺序一致", str(declared))
for code in EXPECTED_CODES:
    fpath = os.path.join(PLATFORMS_DIR, code + ".py")
    check(os.path.exists(fpath), "实现文件存在: %s.py" % code)

# ---------------------------------------------------------------------------
print("\n[2] 类名解析：str.capitalize() 缺陷复现")
check("wechat_public".capitalize() == "Wechat_public",
      "证实 capitalize() 只大写首字母（缺陷根因）",
      repr("wechat_public".capitalize()))

def pascal(code):
    return "".join(part.capitalize() for part in code.split("_"))

for code in EXPECTED_CODES:
    expected_class = pascal(code) + "Platform"
    mod = _load("platforms.%s" % code,
                os.path.join("app", "services", "publication", "platforms", code + ".py"))
    check(hasattr(mod, expected_class),
          "模块 %s 提供类 %s" % (code + ".py", expected_class))

# ---------------------------------------------------------------------------
print("\n[3] PlatformFactory 端到端加载（真实 manager.py 逻辑）")
factory = PlatformFactory(manager=types.SimpleNamespace())
loaded = {}
for code in EXPECTED_CODES:
    cfg = dict(PUBLISH_PLATFORMS.get(code, {}))
    inst = factory.create_platform(code, cfg)
    loaded[code] = inst
    check(inst is not None, "create_platform('%s') 返回实例" % code)
    if inst is not None:
        check(type(inst).__name__ == pascal(code) + "Platform",
              "实例类型正确: %s" % type(inst).__name__,
              "expect=%s" % (pascal(code) + "Platform"))
        check(inst.platform_code == code, "platform_code 正确: %s" % code)

check(len(factory._loaded_platforms) == len(EXPECTED_CODES),
      "6 个平台全部进入实例缓存",
      "cached=%d" % len(factory._loaded_platforms))

# ---------------------------------------------------------------------------
print("\n[4] 兜底扫描：命名约定失配 + 多实现不误判")
fake_mod = types.ModuleType("platforms._fake_single")
fake_mod.__name__ = "platforms._fake_single"
FakeOne = type("WhateverName", (BasePlatform,), {
    "publish": lambda self, c, p: None,
    "__module__": "platforms._fake_single",
})
fake_mod.WhateverName = FakeOne
hit = PlatformFactory._find_platform_class(fake_mod)
check(hit is FakeOne, "唯一子类且命名失配时兜底命中")

fake_mod2 = types.ModuleType("platforms._fake_multi")
fake_mod2.__name__ = "platforms._fake_multi"
A = type("A", (BasePlatform,), {"publish": lambda self, c, p: None,
                               "__module__": "platforms._fake_multi"})
B = type("B", (BasePlatform,), {"publish": lambda self, c, p: None,
                               "__module__": "platforms._fake_multi"})
fake_mod2.A = A
fake_mod2.B = B
check(PlatformFactory._find_platform_class(fake_mod2) is None,
      "存在多个子类时不误判（返回 None）")

# ---------------------------------------------------------------------------
print("\n[5] _validate_content 约束分支")
async def t_validate():
    # (platform, good_content, expected_bad_overrides)
    cases = [
        ("xiaohongshu",
         {"title": "标题", "body": "正文", "image_urls": ["u1"]},
         [({"image_urls": []}, "至少 1 张配图"),
          ({"title": "x" * 51}, "标题超长"),
          ({"body": "x" * 1001}, "正文超长"),
          ({"image_urls": ["u"] * 10}, "图片超量")]),
        ("wechat_public",
         {"title": "标题", "body": "正文"},
         [({"title": "x" * 65}, "标题超长"),
          ({"body": "x" * 20001}, "正文超长")]),
        ("toutiao",
         {"title": "标题", "body": "正文"},
         [({"title": "x" * 31}, "标题超长"),
          ({"body": "x" * 5001}, "正文超长"),
          ({"image_urls": ["u"] * 6}, "图片超量")]),
    ]
    for code, good, bads in cases:
        inst = loaded[code]
        cfg = PUBLISH_PLATFORMS[code]
        ok, msg = inst._validate_content(good, cfg)
        check(ok, "[%s] 合法内容通过校验" % code, msg)
        for override, label in bads:
            payload = dict(good)
            payload.update(override)
            ok2, msg2 = inst._validate_content(payload, cfg)
            check(not ok2, "[%s] 拒绝: %s" % (code, label), "msg=%s" % msg2)

    # 缺字段
    ok, msg = loaded["toutiao"]._validate_content({"title": "只有标题"}, PUBLISH_PLATFORMS["toutiao"])
    check(not ok and "body" in msg, "缺少 body 时被拒绝", msg)

asyncio.run(t_validate())

# ---------------------------------------------------------------------------
print("\n[6] _map_content 字段映射")
mapped = loaded["xiaohongshu"]._map_content(
    {"title": "T", "body": "B", "images": ["i1"], "tags": ["t1"]},
    PUBLISH_PLATFORMS["xiaohongshu"])
check(mapped.get("content") == "B", "xiaohongshu: content <- body", str(mapped.get("content")))
check(mapped.get("image_urls") == ["i1"], "xiaohongshu: image_urls <- images")
check(mapped.get("tags") == ["t1"], "xiaohongshu: tags <- tags")

mapped_w = loaded["wechat_public"]._map_content(
    {"title": "T", "body": "B", "summary": "S", "author": "A"},
    PUBLISH_PLATFORMS["wechat_public"])
check(mapped_w.get("digest") == "S", "wechat_public: digest <- summary", str(mapped_w.get("digest")))
check(mapped_w.get("author") == "A", "wechat_public: author <- author")

# ---------------------------------------------------------------------------
print("\n[7] publish() 缺凭据时优雅失败（不发网络请求）")
async def t_nocreds():
    for code in EXPECTED_CODES:
        inst = loaded[code]
        sess = FakeSession()
        inst.session = sess
        res = await inst.publish({"title": "T", "body": "B", "image_urls": ["u"]},
                                 PUBLISH_PLATFORMS[code])
        check(res["success"] is False and res["status"] == "failed",
              "[%s] 缺凭据返回失败结构" % code, json.dumps(res, ensure_ascii=False))
        check(len(sess.calls) == 0, "[%s] 未发出任何 HTTP 请求" % code)

asyncio.run(t_nocreds())

# ---------------------------------------------------------------------------
print("\n[8] publish() 响应解析与 URL 拼装")
SUCCESS_CASES = {
    "zhihu": ('{"success": true, "id": "ZH1"}', "https://zhuanlan.zhihu.com/p/ZH1", "ZH1"),
    "weibo": ('{"error_code": 0, "id": "WB1"}', "https://weibo.com/ttarticle/p/show?id=WB1", "WB1"),
    "juejin": ('{"err_no": 0, "data": {"article_id": "JJ1"}}', "https://juejin.cn/post/JJ1", "JJ1"),
    "xiaohongshu": ('{"success": true, "data": {"note_id": "XHS1"}}',
                    "https://www.xiaohongshu.com/explore/XHS1", "XHS1"),
    "wechat_public": ('{"media_id": "WX1"}', None, "WX1"),
    "toutiao": ('{"code": 0, "data": {"article_id": "TT1"}}',
                "https://www.toutiao.com/article/TT1/", "TT1"),
}
FAILURE_CASES = {
    "zhihu": '{"success": false, "error_message": "boom"}',
    "weibo": '{"error_code": 100, "error": "boom"}',
    "juejin": '{"err_no": 1, "err_msg": "boom"}',
    "xiaohongshu": '{"success": false, "msg": "boom"}',
    "wechat_public": '{"errcode": 40001, "errmsg": "boom"}',
    "toutiao": '{"code": 1, "message": "boom"}',
}
HTTP_ERROR_CASE = 500

async def t_publish():
    for code, (body, exp_url, exp_id) in SUCCESS_CASES.items():
        inst = loaded[code]
        cfg = PUBLISH_PLATFORMS[code]
        creds = {"access_token": "TOKEN"}
        if code == "wechat_public":
            creds["thumb_media_id"] = "THUMB"
        inst.set_credentials(creds)
        inst.session = FakeSession(200, body)
        res = await inst.publish({"title": "T", "body": "B", "image_urls": ["u"],
                                  "publish_time": 1}, cfg)
        check(res["success"] is True, "[%s] 成功响应被识别" % code,
              json.dumps(res, ensure_ascii=False))
        check(res["publication_id"] == exp_id, "[%s] publication_id=%s" % (code, exp_id),
              str(res["publication_id"]))
        check(res["url"] == exp_url, "[%s] url=%s" % (code, exp_url), str(res["url"]))

        # 凭据在请求中的落点
        call = inst.session.calls[0]
        if code == "wechat_public":
            check(call["kwargs"].get("params", {}).get("access_token") == "TOKEN",
                  "[wechat_public] access_token 走 query")
            arts = call["kwargs"]["json"].get("articles")
            check(isinstance(arts, list) and len(arts) == 1
                  and arts[0].get("thumb_media_id") == "THUMB",
                  "[wechat_public] 请求体为 articles[] 且含封面素材 ID")
        else:
            # 各平台 token 落点不同（历史实现差异，均为既有设计）：
            #   zhihu / weibo  -> 请求体 access_token
            #   juejin         -> 请求头 X-Juejin-Token
            #   xiaohongshu    -> query access_token
            #   toutiao        -> 请求头 X-Toutiao-Token
            # 断言只需确认 token 确实出现在三者之一，不能静默丢失。
            hdrs = call["kwargs"].get("headers", {}) or {}
            body = call["kwargs"].get("json", {}) or {}
            params = call["kwargs"].get("params", {}) or {}
            token_carried = (
                "TOKEN" in hdrs.values()
                or params.get("access_token") == "TOKEN"
                or body.get("access_token") == "TOKEN"
            )
            check(token_carried, "[%s] access_token 已随请求下发" % code,
                  "headers=%s params=%s body_keys=%s"
                  % (sorted(hdrs.keys()), sorted(params.keys()), sorted(body.keys())))

    for code, body in FAILURE_CASES.items():
        inst = loaded[code]
        creds = {"access_token": "TOKEN"}
        if code == "wechat_public":
            creds["thumb_media_id"] = "THUMB"
        inst.set_credentials(creds)
        inst.session = FakeSession(200, body)
        res = await inst.publish({"title": "T", "body": "B", "image_urls": ["u"]},
                                 PUBLISH_PLATFORMS[code])
        check(res["success"] is False, "[%s] 业务失败响应被识别" % code,
              json.dumps(res, ensure_ascii=False))
        check(res["error_message"] and "boom" in res["error_message"],
              "[%s] 错误信息被透传" % code, str(res["error_message"]))

    for code in EXPECTED_CODES:
        inst = loaded[code]
        creds = {"access_token": "TOKEN"}
        if code == "wechat_public":
            creds["thumb_media_id"] = "THUMB"
        inst.set_credentials(creds)
        inst.session = FakeSession(HTTP_ERROR_CASE, "internal error")
        res = await inst.publish({"title": "T", "body": "B", "image_urls": ["u"]},
                                 PUBLISH_PLATFORMS[code])
        check(res["success"] is False and "HTTP" in (res["error_message"] or ""),
              "[%s] HTTP 500 被识别为失败" % code, str(res["error_message"]))

    # cleanup 会关闭会话并清空凭据
    inst = loaded["toutiao"]
    inst.set_credentials({"access_token": "X"})
    inst.session = FakeSession()
    await inst.cleanup()
    check(inst.session.closed and inst.credentials is None,
          "cleanup() 关闭会话并销毁凭据")

asyncio.run(t_publish())

# ---------------------------------------------------------------------------
print("\n[9] 平台不支持时的错误响应")
check(factory.create_platform("nonexistent_platform", {}) is None,
      "未知平台返回 None")

print("\n" + "=" * 78)
print("PASSED: %d    FAILED: %d" % (PASSED, len(FAILED)))
if FAILED:
    print("-" * 78)
    for f in FAILED:
        print("  FAILED -> %s" % f)
print("=" * 78)
sys.exit(1 if FAILED else 0)
