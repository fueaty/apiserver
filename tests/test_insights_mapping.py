#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_insights 字段映射纯逻辑回归测试（需求③）

覆盖 InsightsService 的纯函数 build_insight_fields 与字段规划一致性：
  - 返回**恰好 14 个键**且 ⊇ TABLE_PLANS['ai_insights']
  - AI_INSIGHT_FIELDS == TABLE_PLANS['ai_insights']
  - content 空 → 退化为 title + '\n' + summary
  - tags 列表 → 逗号文本
  - category 回退逻辑
  - status 固定 'generated'；published_at 取 headline

自带第三方依赖桩（httpx / lark_oapi / app.core.config），不联网、不安装依赖：

    python tests/test_insights_mapping.py
"""

import os
import sys
import types
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.join(ROOT, "app", "services", "analysis")
FA_DIR = os.path.join(ANALYSIS_DIR, "feature_analysis")
FEISHU_DIR = os.path.join(ROOT, "app", "services", "feishu")

# ---------------------------------------------------------------------------
# 1. 第三方依赖桩
# ---------------------------------------------------------------------------
httpx_stub = types.ModuleType("httpx")
httpx_stub.AsyncClient = object
httpx_stub.Client = object
sys.modules["httpx"] = httpx_stub

lark_stub = types.ModuleType("lark_oapi")
lark_stub.__path__ = []
lark_stub.LogLevel = types.SimpleNamespace(INFO=1, DEBUG=2)
sys.modules["lark_oapi"] = lark_stub
for name in ("lark_oapi.api", "lark_oapi.api.bitable", "lark_oapi.api.bitable.v1"):
    m = types.ModuleType(name)
    m.__path__ = []
    sys.modules[name] = m
sys.modules["lark_oapi.api.bitable.v1"].__dict__["*"] = None

for name, path in (
    ("app", os.path.join(ROOT, "app")),
    ("app.core", os.path.join(ROOT, "app", "core")),
    ("app.utils", os.path.join(ROOT, "app", "utils")),
    ("app.services", os.path.join(ROOT, "app", "services")),
    ("app.services.analysis", ANALYSIS_DIR),
    ("app.services.analysis.feature_analysis", FA_DIR),
    ("app.services.feishu", FEISHU_DIR),
):
    m = types.ModuleType(name)
    m.__path__ = [path]
    sys.modules[name] = m

config_stub = types.ModuleType("app.core.config")
config_stub.config_manager = types.SimpleNamespace(
    get_config=lambda force_reload=False: {},
    get_credentials=lambda force_reload=False: {},
)
sys.modules["app.core.config"] = config_stub


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


llm_clients = _load("app.services.analysis.feature_analysis.llm_clients",
                    os.path.join(FA_DIR, "llm_clients.py"))
field_rules = _load("app.services.feishu.field_rules",
                    os.path.join(FEISHU_DIR, "field_rules.py"))
_load("app.services.feishu.limits", os.path.join(FEISHU_DIR, "limits.py"))
_load("app.services.feishu.feishu_service", os.path.join(FEISHU_DIR, "feishu_service.py"))
insights_service = _load("app.services.analysis.insights_service",
                         os.path.join(ANALYSIS_DIR, "insights_service.py"))

build_insight_fields = insights_service.build_insight_fields
AI_INSIGHT_FIELDS = insights_service.AI_INSIGHT_FIELDS
GENERATABLE = insights_service.GENERATABLE
TABLE_PLANS = field_rules.TABLE_PLANS

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s" % name)
    else:
        FAILED.append(name + (" :: " + str(detail) if detail else ""))
        print("  [FAIL] %s  %s" % (name, detail))


def run():
    print("=" * 72)
    print("ai_insights 字段映射纯逻辑回归测试")
    print("=" * 72)

    plan = set(TABLE_PLANS['ai_insights']['fields'])

    # [1] 字段规划一致性
    print("\n[1] 字段规划一致性")
    check("AI_INSIGHT_FIELDS 恰好 14 个", len(AI_INSIGHT_FIELDS) == 14, len(AI_INSIGHT_FIELDS))
    check("AI_INSIGHT_FIELDS == TABLE_PLANS['ai_insights']",
          set(AI_INSIGHT_FIELDS) == plan,
          "ai=%s plan=%s" % (sorted(AI_INSIGHT_FIELDS), sorted(plan)))
    check("GENERATABLE 是 7 个", GENERATABLE == {'summary', 'tags', 'sentiment', 'seo_title',
                                                'seo_description', 'seo_keywords', 'category'},
          sorted(GENERATABLE))

    # [2] 完整映射：恰好 14 键、⊇ 规划
    print("\n[2] build_insight_fields 键集")
    headline = {
        'title': '热点标题',
        'url': 'https://ex.com/a',
        'content': '正文内容一段',
        'author': '作者甲',
        'category': '原分类',
        'published_at': '2025-01-01 12:00:00',
    }
    llm_out = {
        'summary': '深度摘要',
        'tags': ['热点', '科技', '观察'],
        'sentiment': '积极',
        'seo_title': 'SEO 标题',
        'seo_description': 'SEO 描述',
        'seo_keywords': 'kw1, kw2',
        'category': 'LLM分类',
    }
    fields = build_insight_fields(headline, llm_out, set(GENERATABLE), 'ins-0001')
    check("恰好 14 个键", len(fields) == 14, len(fields))
    check("键集 ⊆ 规划（无多余）", set(fields.keys()) - plan == set(), sorted(set(fields.keys()) - plan))
    check("键集 ⊇ 规划（无缺失）", plan - set(fields.keys()) == set(), sorted(plan - set(fields.keys())))
    check("id == insight_id", fields.get('id') == 'ins-0001', fields.get('id'))
    check("title 直传", fields.get('title') == '热点标题', fields.get('title'))
    check("url 直传", fields.get('url') == 'https://ex.com/a', fields.get('url'))
    check("author 直传", fields.get('author') == '作者甲', fields.get('author'))
    check("content 取 headline.content", fields.get('content') == '正文内容一段', fields.get('content'))
    check("published_at 取 headline", fields.get('published_at') == '2025-01-01 12:00:00', fields.get('published_at'))
    check("status == 'generated'", fields.get('status') == 'generated', fields.get('status'))

    # [3] tags / category
    print("\n[3] tags 与 category")
    check("tags 列表 -> 逗号文本", fields.get('tags') == '热点, 科技, 观察', fields.get('tags'))
    check("category 取 LLM（在 generate_set 内）", fields.get('category') == 'LLM分类', fields.get('category'))

    no_cat = build_insight_fields(headline, llm_out, set(GENERATABLE) - {'category'}, 'ins-0002')
    check("category 不在 generate_set -> 回退 headline.category",
          no_cat.get('category') == '原分类', no_cat.get('category'))

    empty_llm_cat = build_insight_fields(headline, {'category': ''}, {'category'}, 'ins-0003')
    check("LLM category 为空 -> 回退 headline.category",
          empty_llm_cat.get('category') == '原分类', empty_llm_cat.get('category'))

    # [4] content 退化（仅 summary 非空时才退化）
    print("\n[4] content 退化")
    no_content = dict(headline)
    no_content['content'] = ''
    degraded = build_insight_fields(no_content, {'summary': '摘要X'}, set(GENERATABLE), 'ins-0004')
    deg_text = degraded.get('content') or ''
    check("content 空 -> title+summary", '热点标题' in deg_text and '摘要X' in deg_text, repr(deg_text))
    ws_content = dict(headline)
    ws_content['content'] = '   '
    degraded2 = build_insight_fields(ws_content, {'summary': '摘要Y'}, set(GENERATABLE), 'ins-0005')
    deg2_text = degraded2.get('content') or ''
    check("content 全空白也退化", '摘要Y' in deg2_text, repr(deg2_text))

    # [4b] Fix1：summary 也为空时，content 必须明确置空，不得退化成恰好 == title
    #      （否则下游无法区分“有正文”与“没正文”，等于用兜底掩盖数据缺失）
    print("\n[4b] content 不掩盖数据缺失（summary 空 -> content 置空）")
    only_title = build_insight_fields({'title': '只有标题'}, {}, set(), 'ins-0008')
    check("content == ''", only_title.get('content') == '', repr(only_title.get('content')))
    check("content != title", only_title.get('content') != only_title.get('title'),
          "content=%r title=%r" % (only_title.get('content'), only_title.get('title')))
    check("仍保留 content 键", 'content' in only_title)
    check("仍恰好 14 键", len(only_title) == 14, len(only_title))

    # [4c] Fix1：summary 非空时退化仍生效
    t_s = build_insight_fields({'title': 'T'}, {'summary': 'S'}, set(), 'ins-0009')
    check("content == 'T\\nS'", t_s.get('content') == 'T\nS', repr(t_s.get('content')))

    # [5] 缺失字段兜底为空串
    print("\n[5] LLM 缺字段 -> 空串")
    sparse = build_insight_fields(headline, {'summary': '仅有摘要'}, set(GENERATABLE), 'ins-0006')
    check("缺失 sentiment -> ''", sparse.get('sentiment') == '', repr(sparse.get('sentiment')))
    check("缺失 seo_title -> ''", sparse.get('seo_title') == '', repr(sparse.get('seo_title')))
    check("缺失 tags -> ''", sparse.get('tags') == '', repr(sparse.get('tags')))
    check("仍有 14 键", len(sparse) == 14, len(sparse))

    # [6] tags 已是字符串
    print("\n[6] tags 字符串输入")
    str_tags = build_insight_fields(headline, {'tags': 'a, b'}, set(GENERATABLE), 'ins-0007')
    check("tags 字符串原样", str_tags.get('tags') == 'a, b', repr(str_tags.get('tags')))

    print("\n" + "=" * 72)
    print("PASSED: %d    FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("-" * 72)
        for f in FAILED:
            print("  FAILED -> %s" % f)
    print("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(run())
