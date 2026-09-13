#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
澎湃新闻热榜采集测试脚本

包含两部分：
  1) 离线截断守卫断言（默认执行、不联网）：证明 collect() 在“排序/排名分支抛异常
     被 except 吞掉”时，返回结果仍被无条件截断到 MAX_RESULTS（补⑥ 回归）；
  2) 端到端网络采集（加 --e2e 才执行）：需要外网与真实 aiohttp；判定为**真断言**
     （空跑 len==0 / 超 MAX_RESULTS / 落盘异常 均置 FAIL，影响退出码）。

aiohttp 采用**条件桩**：依赖齐全时用真实包（--e2e 才真能联网），
仅当 ImportError 时才补桩（使未装依赖的干净环境也能直跑离线断言）。
见下方“依赖桩”块内的合法性判据说明。

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
#
# 桩的合法性判据（团队统一口径，勿违反）：
#   桩的合法性 = **被桩模块的行为是否被断言依赖**。
#   · aiohttp：其行为**不被离线断言依赖**，只有"模块级 import / def 时注解"
#     需要那个**名字** → 可桩。
#   · 反例（本仓库 test_publication_platforms.py 的 yaml）：yaml.safe_load 的
#     **解析结果就是断言的输入** → 打桩会让断言退回与伪造配置比对 → **不可桩**。
#
# 因此这里必须**条件桩**，而不是无条件覆盖：
#   · 依赖齐全（真 aiohttp 可导入）→ 保留真实包，--e2e 才能真发网络请求；
#   · 仅 ImportError → 才补桩，使未装依赖的干净环境亦能直跑离线断言。
# 早期版本"无条件覆盖 aiohttp.ClientSession = object"会把 --e2e 变成
# 「任一次联网都必抛错 → 被 collect() 吞掉 → 打印 0 条 → 仍 RC=0」的**永远绿空跑**，
# 比它要修的 print-only 更隐蔽，故此处必须条件化。
try:
    import aiohttp  # noqa: F401  依赖齐全 → 用真实包，--e2e 才真能联网
except ImportError:
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
    site = ThepaperSite("thepaper", {"timeout": 15})
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
    """端到端网络采集（--e2e；需要外网 + 真实 aiohttp）。

    判定全部走 check()、真实影响退出码（不再是"只 print 不置 FAILED"）：
      · collect() 抛异常 / 未返回 list            → FAIL
      · 返回 0 条（空跑：网络不可达或站点结构已变）→ FAIL
      · 返回条数 > MAX_RESULTS（容量上界被突破）   → FAIL
      · 结果 JSON 落盘异常                          → FAIL
    过去该段只 print、不置 FAILED，导致 --e2e 无论空跑还是异常都 RC=0，
    比它本想修的 print-only 更隐蔽，故改为真断言。
    """
    print("\n[2] 端到端网络采集（--e2e，需要外网 + 真实 aiohttp）")

    # 构造口径必须与线上 SiteFactory.create_site(site_code, site_config) 一致：
    # base.get_session() 会读 self.config.get("timeout", 10)，config 为 None 时
    # 直接抛 AttributeError → 被 collect() 的 except 吞掉 → 静默返回 []（空跑）。
    # 故此处显式传 dict；timeout 取 config/sites.yaml 中 thepaper 的实际值 15。
    thepaper_collector = ThepaperSite("thepaper", {"timeout": 15})

    results = None
    try:
        results = await thepaper_collector.collect({})
        check("e2e: collect() 无异常返回", True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("e2e: collect() 无异常返回", False, f"{type(e).__name__}: {e}")

    if not isinstance(results, list):
        check("e2e: collect() 返回 list",
              False, f"type={type(results).__name__}")
        return

    print(f"\n采集完成，共获取 {len(results)} 条数据")

    # —— 核心真断言 ——
    check("e2e: 实际采到数据（空跑视为失败）",
          len(results) > 0,
          "len=0 —— 网络不可达 / 站点结构变化 / aiohttp 不可用导致空跑")
    check(f"e2e: 条数 <= MAX_RESULTS({MAX_RESULTS})",
          len(results) <= MAX_RESULTS,
          f"len={len(results)} 突破容量上界")

    # 预览与字段统计（仅展示，不参与判定）
    print("\n前5条数据预览:")
    for i, item in enumerate(results[:5]):
        print(f"{i+1}. 标题: {item.get('title', 'N/A')}")
        print(f"   链接: {item.get('url', 'N/A')}")
        print(f"   热度: {item.get('hot', 'N/A')}")
        print(f"   排名: {item.get('rank', 'N/A')}")
        print("-" * 50)

    required_fields = ['title', 'url', 'hot', 'rank']
    valid_count = sum(
        1 for it in results if all(it.get(f) for f in required_fields))
    print(f"\n有效数据: {valid_count}/{len(results)} 条")

    hot_values = [int(it['hot']) for it in results
                  if str(it.get('hot', '')).isdigit()]
    if hot_values:
        is_sorted = all(hot_values[i] >= hot_values[i + 1]
                        for i in range(len(hot_values) - 1))
        print(f"热度排序: {'正确' if is_sorted else '错误'}")

    # 页面内容落盘：尽力而为，非判定项
    if getattr(thepaper_collector, 'page_content', None):
        try:
            with open('thepaper_page.html', 'w', encoding='utf-8') as f:
                f.write(thepaper_collector.page_content)
            print("页面内容已保存到 thepaper_page.html 文件")
        except Exception as e:
            print(f"页面内容保存失败（非判定项）: {e}")

    # 结果落盘：异常必须置 FAIL
    try:
        with open('thepaper_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        check("e2e: 结果可落盘 thepaper_results.json", True)
        print("结果已保存到 thepaper_results.json 文件")
    except Exception as e:
        check("e2e: 结果可落盘 thepaper_results.json",
              False, f"{type(e).__name__}: {e}")


async def main():
    print("=" * 66)
    print("澎湃新闻采集测试：离线截断守卫 + 端到端（--e2e）")
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
