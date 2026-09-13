#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正文抽取纯逻辑回归测试（需求②）

覆盖 ContentExtractor：
  - 站点选择器命中（div.article-content / #content / article）→ extractor='site_selector'
  - 选择器未命中 → 通用兜底 → extractor='generic'
  - 纯空页 → extractor='none'、text=''
  - 跳过 script / style
  - 空白归一化（normalize_text）
  - match_selector 的 5 种形式

零第三方依赖、不联网，直接运行：

    python tests/test_content_extractor.py
"""

import os
import sys
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

spec = importlib.util.spec_from_file_location(
    "content_extractor",
    os.path.join(ROOT, "app", "services", "collection", "content_extractor.py"),
)
ce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ce)

ContentExtractor = ce.ContentExtractor
ExtractResult = ce.ExtractResult

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s" % name)
    else:
        FAILED.append(name + (" :: " + str(detail) if detail else ""))
        print("  [FAIL] %s  %s" % (name, detail))


# ---------------------------------------------------------------------------
# 内联 HTML 夹具
# ---------------------------------------------------------------------------
HTML_ARTICLE = """
<html><head><title>标题</title>
<style>.hidden{display:none}</style></head>
<body>
  <header>站点导航栏</header>
  <nav>首页 / 新闻 / 体育</nav>
  <div class="article-content">
    <h1>正文大标题</h1>
    <p>第一段正文。</p>
    <p>第二段正文。</p>
    <script>console.log("不该出现-1")</script>
  </div>
  <footer>版权信息</footer>
</body></html>
"""

HTML_ID = """
<html><body>
  <div id="content"><p>主内容甲</p><p>主内容乙</p></div>
  <aside>侧边广告</aside>
  <div>无关的其他块</div>
</body></html>
"""

HTML_ARTICLE_TAG = """
<html><body>
  <article><p>article 正文一段</p><p>article 正文二段</p></article>
  <div>页脚块</div>
</body></html>
"""

HTML_NO_SELECTOR = """
<html><body>
  <div><p>兜底段落。</p></div>
  <script>console.log("不该出现-2")</script>
</body></html>
"""

HTML_EMPTY = "<html><head></head><body></body></html>"
HTML_SCRIPT_ONLY = "<html><body><script>var a=1;</script><style>.a{}</style></body></html>"


def run():
    print("=" * 70)
    print("正文抽取纯逻辑回归测试")
    print("=" * 70)
    ex = ContentExtractor()

    # [1] 站点选择器：div.article-content 命中
    print("\n[1] 站点选择器命中 -> site_selector")
    r = ex.extract(HTML_ARTICLE, "div.article-content")
    check("extractor=site_selector", r.extractor == "site_selector", r.extractor)
    check("matched=True", r.matched is True, r.matched)
    check("含第一段正文", "第一段正文" in r.text, r.text)
    check("含 h1 标题文本", "正文大标题" in r.text, r.text)
    check("不含导航栏（header 跳过）", "站点导航栏" not in r.text, r.text)
    check("不含 script 内容", "不该出现-1" not in r.text, r.text)
    check("不含 footer 内容", "版权信息" not in r.text, r.text)

    # [2] #content 命中
    print("\n[2] #id 选择器命中")
    r = ex.extract(HTML_ID, "#content")
    check("extractor=site_selector", r.extractor == "site_selector", r.extractor)
    check("含主内容甲", "主内容甲" in r.text, r.text)
    check("不含 aside 广告", "侧边广告" not in r.text, r.text)
    check("不含无关块", "无关的其他块" not in r.text, r.text)

    # [3] article 标签选择器命中
    print("\n[3] tag 选择器命中")
    r = ex.extract(HTML_ARTICLE_TAG, "article")
    check("extractor=site_selector", r.extractor == "site_selector", r.extractor)
    check("含 article 正文", "article 正文一段" in r.text, r.text)
    check("不含页脚块", "页脚块" not in r.text, r.text)

    # [4] 选择器未命中 -> 通用兜底
    print("\n[4] 选择器未命中 -> generic")
    r = ex.extract(HTML_ID, "#not-exist")
    check("extractor=generic", r.extractor == "generic", r.extractor)
    check("matched=False", r.matched is False, r.matched)
    check("兜底仍拿到正文", "主内容甲" in r.text, r.text)

    # [5] 未配置选择器 -> 通用兜底 + 跳过 script/style
    print("\n[5] 无选择器 -> generic，且跳过 script/style")
    r = ex.extract(HTML_NO_SELECTOR, None)
    check("extractor=generic", r.extractor == "generic", r.extractor)
    check("含兜底段落", "兜底段落" in r.text, r.text)
    check("跳过 script", "不该出现-2" not in r.text, r.text)

    # [6] 空页 -> none
    print("\n[6] 纯空页 -> none")
    r = ex.extract(HTML_EMPTY, None)
    check("extractor=none", r.extractor == "none", r.extractor)
    check("text 为空", r.text == "", repr(r.text))
    r2 = ex.extract("", None)
    check("空字符串输入 -> none", r2.extractor == "none" and r2.text == "", r2)
    r3 = ex.extract(HTML_SCRIPT_ONLY, "div.article-content")
    check("只有 script/style -> none", r3.extractor == "none" and r3.text == "", r3)

    # [7] 空白归一化
    print("\n[7] normalize_text 空白折叠")
    check("行内多空格折叠", ContentExtractor.normalize_text("  hello   world  ") == "hello world",
          repr(ContentExtractor.normalize_text("  hello   world  ")))
    check("连续换行合并（丢空行）",
          ContentExtractor.normalize_text("a\n\n\n   \nb") == "a\nb",
          repr(ContentExtractor.normalize_text("a\n\n\n   \nb")))
    check("制表符折叠", ContentExtractor.normalize_text("x\t\ty") == "x y",
          repr(ContentExtractor.normalize_text("x\t\ty")))
    check("空输入 -> 空串", ContentExtractor.normalize_text("") == "")
    check("None -> 空串", ContentExtractor.normalize_text(None) == "")

    # [8] match_selector 五种形式
    print("\n[8] match_selector 五种形式")
    attrs = {"id": "main", "class": "article-content wide"}
    check("#id 命中", ContentExtractor.match_selector("div", attrs, "#main") is True)
    check("#id 未命中", ContentExtractor.match_selector("div", attrs, "#other") is False)
    check("tag 命中", ContentExtractor.match_selector("div", attrs, "div") is True)
    check("tag 未命中", ContentExtractor.match_selector("span", attrs, "div") is False)
    check(".class 命中", ContentExtractor.match_selector("div", attrs, ".article-content") is True)
    check(".class 未命中", ContentExtractor.match_selector("div", attrs, ".missing") is False)
    check("tag.class 命中", ContentExtractor.match_selector("div", attrs, "div.article-content") is True)
    check("tag.class 标签不符未命中",
          ContentExtractor.match_selector("p", attrs, "div.article-content") is False)
    check("tag#id 命中", ContentExtractor.match_selector("div", attrs, "div#main") is True)
    check("tag#id 标签不符未命中",
          ContentExtractor.match_selector("p", attrs, "div#main") is False)
    check("空选择器不命中", ContentExtractor.match_selector("div", attrs, "") is False)

    # [9] 零第三方依赖守卫：AST 层面不得 import bs4 / lxml
    #      （用 AST 而非文本匹配，避免文档里"禁止 bs4/lxml"的说明造成误报）
    print("\n[9] 零第三方依赖守卫（AST）")
    import ast
    src = open(os.path.join(ROOT, "app", "services", "collection", "content_extractor.py"),
               encoding="utf-8").read()
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0].lower())
    check("未 import bs4", "bs4" not in imported, sorted(imported))
    check("未 import lxml", "lxml" not in imported, sorted(imported))
    check("仅依赖标准库 html.parser",
          all(mod in {"html", "re", "dataclasses", "typing"} for mod in imported),
          sorted(imported))

    print("\n" + "=" * 70)
    print("PASSED: %d    FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("-" * 70)
        for f in FAILED:
            print("  FAILED -> %s" % f)
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(run())
