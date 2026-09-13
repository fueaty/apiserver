#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
澎湃新闻热榜采集测试脚本

包含两部分：
  1) 离线截断守卫断言（默认执行、不联网）：证明 collect() 在“排序/排名分支抛异常
     被 except 吞掉”时，返回结果仍被无条件截断到 MAX_RESULTS（补⑥ 回归）；
  2) 端到端网络采集（加 --e2e 才执行）：需要外网与真实站点。

    python tests/test_thepaper_collection.py            # 只跑离线断言
    python tests/test_thepaper_collection.py --e2e      # 额外跑真实采集
"""

import asyncio
import json
import sys
import os
import types

# ---------------------------------------------------------------------------
# 依赖桩（照仓库其他离线测试 test_feishu_capacity.py 的写法）
#
# thepaper → .base 在**模块级** `import aiohttp`，且 base.get_session 的类型注解
# `-> aiohttp.ClientSession` 会在 def 时求值 → 即使本测试全程走桩 session，
# 模块导入本身也需要 aiohttp 这个"名字"存在。
# 这里**无条件**打桩（不要 try/except 真实 import），使本测试在
# **未安装项目依赖的干净环境也能直跑** —— 复现性优先于复用真实包。
_aiohttp_stub = types.ModuleType("aiohttp")
_aiohttp_stub.ClientSession = object
_aiohttp_stub.ClientTimeout = object
_aiohttp_stub.TCPConnector = object
sys.modules["aiohttp"] = _aiohttp_stub
# ---------------------------------------------------------------------------

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.collection.sites.thepaper import ThepaperSite, MAX_RESULTS

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}")


def _make_offline_site(items):
    """构造一个不联网的 ThepaperSite：主页解析直接返回 items，并跳过分类页循环。

    跳过 category_urls 是必要的：否则 collect() 会对 7 个分类页做
    2+3+...+8 秒的 sleep，测试会拖到 35s。
    """
    site = ThepaperSite()
    site.category_urls = []

    class _FakeResp:
        status = 200

        async def text(self):
            return "<html></html>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def get(self, *args, **kwargs):
            return _FakeResp()

        async def close(self):
            return None

    async def _fake_get_session():
        return _FakeSession()

    site.get_session = _fake_get_session
    site._parse_thepaper_hot_ranking = lambda text: list(items)
    site._parse_category_page = lambda text, url: []
    return site


async def test_truncation_guard_offline():
    """离线：制造 hot 非数字/缺失，令排序/排名分支抛异常，断言返回仍被截断。

    回归点（补⑥）：截断原先只写在 try 块内、results.sort(...) 之后；
    一旦 int(x.get('hot')) 抛 ValueError 或 int(item['hot']) 抛 KeyError，
    异常被 except 吞掉 → 会返回**未经截断的全量列表**，使 limits.py 容量预算
    依赖的 thepaper 上界（MAX_RESULTS）静默失效。改为 return 前无条件截断后，
    两条异常路径都必须返回 len <= MAX_RESULTS。
    """
    print("\n[1] collect() 异常路径下的截断守卫（离线）")
    over = MAX_RESULTS + 50

    def _items(kind):
        out = []
        for i in range(over):
            item = {
                'id': f"x{i}",
                'title': f"T{i}",
                'url': f"https://www.thepaper.cn/newsDetail_forward_{i}",
                'rank': str(i + 1),
                'site_code': 'thepaper',
            }
            if kind == "nonnumeric":
                item['hot'] = "not-a-number"   # sort 的 int(...) 抛 ValueError
            # kind == "missing"：故意不给 hot，排名循环 item['hot'] 抛 KeyError
            out.append(item)
        return out

    for kind, label in (("nonnumeric", "hot 非数字(ValueError)"),
                        ("missing", "hot 缺失(KeyError)")):
        site = _make_offline_site(_items(kind))
        result = await site.collect({})
        check(f"{label}：返回条数 <= MAX_RESULTS",
              len(result) <= MAX_RESULTS,
              f"len={len(result)} cap={MAX_RESULTS}")
        check(f"{label}：异常被吞后仍截断（< 注入量 {over}）",
              len(result) < over,
              f"len={len(result)}")


async def test_thepaper_collection():
    """测试澎湃新闻热榜采集功能（端到端，需要外网）"""
    print("开始测试澎湃新闻热榜采集功能...")

    # 创建澎湃新闻采集器实例
    thepaper_collector = ThepaperSite()

    try:
        # 执行采集
        results = await thepaper_collector.collect({})

        print(f"\n采集完成，共获取 {len(results)} 条数据")

        # 保存页面内容供分析
        if hasattr(thepaper_collector, 'page_content') and thepaper_collector.page_content:
            with open('thepaper_page.html', 'w', encoding='utf-8') as f:
                f.write(thepaper_collector.page_content)
            print("页面内容已保存到 thepaper_page.html 文件")

        # 显示前5条数据预览
        print("\n前5条数据预览:")
        for i, item in enumerate(results[:5]):
            print(f"{i+1}. 标题: {item.get('title', 'N/A')}")
            print(f"   链接: {item.get('url', 'N/A')}")
            print(f"   热度: {item.get('hot', 'N/A')}")
            print(f"   排名: {item.get('rank', 'N/A')}")
            print("-" * 50)

        # 数据验证
        print("\n数据验证:")
        if results:
            required_fields = ['title', 'url', 'hot', 'rank']
            valid_count = 0
            for item in results:
                if all(field in item and item[field] for field in required_fields):
                    valid_count += 1

            print(f"有效数据: {valid_count}/{len(results)} 条")

            # 容量约束：collect() 返回的条数不得超过模块常量 MAX_RESULTS
            # （该常量参与 limits.py 的容量预算，见 thepaper.py 顶部说明）
            print(f"容量上限校验: MAX_RESULTS = {MAX_RESULTS}")
            if len(results) <= MAX_RESULTS:
                print(f"条数校验: {len(results)} <= MAX_RESULTS({MAX_RESULTS}) [OK]")
            else:
                print(f"条数校验: {len(results)} > MAX_RESULTS({MAX_RESULTS}) [FAIL]")

            # 检查热度值是否正确排序
            hot_values = [int(item['hot']) for item in results if 'hot' in item and item['hot'].isdigit()]
            if hot_values:
                is_sorted = all(hot_values[i] >= hot_values[i+1] for i in range(len(hot_values)-1))
                print(f"热度排序: {'正确' if is_sorted else '错误'}")

        # 保存结果到JSON文件
        with open('thepaper_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("结果已保存到 thepaper_results.json 文件")

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("=" * 66)
    print("澎湃新闻采集：离线截断守卫断言")
    print("=" * 66)

    await test_truncation_guard_offline()

    if "--e2e" in sys.argv:
        print("\n" + "-" * 66)
        await test_thepaper_collection()

    print("\n" + "=" * 66)
    print(f"结果: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    for f in FAILED:
        print(f"  [FAIL] {f}")
    print("=" * 66)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
