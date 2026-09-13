# -*- coding: utf-8 -*-
"""
正文抽取纯逻辑层（需求②）

设计约束（务必遵守）：
  - 只用 Python 标准库 ``html.parser``，**零第三方依赖**（禁止 bs4 / lxml），
    以保证在生产（可能未装库）与本机（离线）都能 import 与测试。
  - 纯逻辑、无 I/O：输入 HTML 字符串，输出归一化正文文本。便于"依赖桩 +
    断言计数器"风格的离线测试。

抽取策略（与架构 §3.4 一致）：
  1. 站点选择器优先：命中 ``selector`` 的容器子树文本 → ``extractor='site_selector'``；
  2. 未配置选择器 / 选择器未命中 / 命中但内容为空 → 通用兜底（收集 BLOCK_TAGS
     文本、跳过 SKIP_TAGS）→ ``extractor='generic'``；
  3. 两者都为空 → ``extractor='none'``、``text=''``。
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple


# HTML 空元素（无闭合标签），维护嵌套深度/栈时需要忽略，避免栈失衡。
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


@dataclass
class ExtractResult:
    """正文抽取结果。"""

    text: str          # 归一化后的正文
    extractor: str     # 'site_selector' | 'generic' | 'none'
    matched: bool      # 是否命中站点选择器


class _HtmlCollector(HTMLParser):
    """内部解析器：支持"目标容器模式"与"通用模式"。

    - 目标容器模式（mode='selector'）：命中选择器的元素（及其子树）文本会被收集；
    - 通用模式（mode='generic'）：收集 BLOCK_TAGS 文本，跳过 SKIP_TAGS；
    - 两种模式都会跳过 SKIP_TAGS 子树（script/style/nav/...）。
    """

    def __init__(self, selector: Optional[str] = None, mode: str = "generic"):
        super().__init__(convert_charrefs=True)
        self.selector = selector
        self.mode = mode
        self.parts: List[str] = []
        self.matched = False
        # 跳过区（SKIP_TAGS）状态
        self._skip_name: Optional[str] = None
        self._skip_depth = 0
        # 选择器模式下的"目标容器"状态
        self._selecting = False
        self._open: List[str] = []

    # -- 跳过区辅助 --------------------------------------------------------
    def _handle_skip_start(self, tag: str) -> bool:
        """处于/进入跳过区时返回 True（表示本次事件已被跳过逻辑消费）。"""
        if self._skip_name is not None:
            # 已在跳过区内：只跟踪同名嵌套深度
            if tag == self._skip_name:
                self._skip_depth += 1
            return True
        if tag in ContentExtractor.SKIP_TAGS:
            self._skip_name = tag
            self._skip_depth = 1
            return True
        return False

    # -- HTMLParser 回调 --------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = (tag or "").lower()
        if self._handle_skip_start(tag):
            return

        attrs_dict: Dict[str, str] = {}
        for key, value in attrs or []:
            attrs_dict[str(key).lower()] = value if value is not None else ""

        if self.mode == "selector":
            if not self._selecting and self.selector:
                if ContentExtractor.match_selector(tag, attrs_dict, self.selector):
                    self._selecting = True
                    self.matched = True
            if self._selecting and tag not in _VOID_TAGS:
                self._open.append(tag)
        else:  # generic
            if tag in ContentExtractor.BLOCK_TAGS:
                self.parts.append("\n")
            if tag == "br":
                self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        # 自闭合标签（如 <br/>、<img/>）走与 starttag 相同分支，但不入栈。
        tag = (tag or "").lower()
        if self._handle_skip_start(tag):
            return
        if self.mode == "generic" and tag in ("br",):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = (tag or "").lower()
        if self._skip_name is not None:
            if tag == self._skip_name:
                self._skip_depth -= 1
                if self._skip_depth <= 0:
                    self._skip_name = None
            return

        if self.mode == "selector" and self._selecting:
            if tag in self._open:
                # 弹出到匹配的标签（容忍轻微的标签错配）
                while self._open:
                    if self._open.pop() == tag:
                        break
                if not self._open:
                    self._selecting = False

    def handle_data(self, data: str) -> None:
        if self._skip_name is not None:
            return
        if self.mode == "selector":
            if self._selecting:
                self.parts.append(data)
        else:
            self.parts.append(data)

    # -- 结果 -------------------------------------------------------------
    def text(self) -> str:
        return ContentExtractor.normalize_text("".join(self.parts))


class ContentExtractor:
    """HTML → 正文文本 抽取器（纯逻辑，零第三方依赖）。"""

    # 块级标签：用于通用兜底时插入换行分隔，保留段落感。
    BLOCK_TAGS = {"p", "div", "article", "section", "li", "br", "h1", "h2", "h3"}
    # 需整段跳过的标签（导航/脚本/样式等非正文内容）。
    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript"}

    def extract(self, html: str, selector: Optional[str] = None) -> ExtractResult:
        """抽取正文。

        Args:
            html: 原始 HTML 字符串
            selector: 可选的站点正文选择器（支持 '#id' / 'tag' / '.class' /
                'tag.class' / 'tag#id'）

        Returns:
            ExtractResult(text, extractor, matched)
        """
        if not html or not html.strip():
            return ExtractResult(text="", extractor="none", matched=False)

        # 1) 站点选择器优先
        if selector:
            collector = _HtmlCollector(selector=selector, mode="selector")
            try:
                collector.feed(html)
                collector.close()
            except Exception:
                collector.matched = False
            site_text = collector.text()
            if collector.matched and site_text:
                return ExtractResult(text=site_text, extractor="site_selector", matched=True)

        # 2) 通用兜底
        generic_text = self._strip(html)
        if generic_text:
            return ExtractResult(text=generic_text, extractor="generic", matched=False)

        # 3) 都为空
        return ExtractResult(text="", extractor="none", matched=False)

    @staticmethod
    def _strip(html: str) -> str:
        """通用兜底：收集块级文本、跳过 script/style 等，返回归一化文本。"""
        collector = _HtmlCollector(mode="generic")
        try:
            collector.feed(html)
            collector.close()
        except Exception:
            pass
        return collector.text()

    @staticmethod
    def match_selector(tag: str, attrs: Dict[str, str], selector: str) -> bool:
        """判断元素是否命中简易选择器。

        支持形式：``#id`` | ``tag`` | ``.class`` | ``tag.class`` | ``tag#id``
        （class 支持以 ``.`` 连接多个：``tag.a.b``）。
        """
        if not selector:
            return False
        selector = selector.strip()
        if not selector:
            return False

        tag = (tag or "").lower()
        norm_attrs: Dict[str, str] = {}
        for key, value in (attrs or {}).items():
            norm_attrs[str(key).lower()] = value if value is not None else ""

        # 解析标签名（选择器前缀的字母段）
        match = re.match(r"^([a-zA-Z][a-zA-Z0-9]*)", selector)
        sel_tag = match.group(1).lower() if match else None
        rest = selector[match.end():] if match else selector

        sel_id: Optional[str] = None
        sel_classes: List[str] = []
        if rest:
            if rest.startswith("#"):
                sel_id = rest[1:].strip().lower()
            elif rest.startswith("."):
                sel_classes = [c.lower() for c in rest[1:].split(".") if c]
            else:
                # 不支持的选择器形式：不命中
                return False

        if sel_tag and sel_tag != tag:
            return False

        if sel_id is not None:
            if norm_attrs.get("id", "").strip().lower() != sel_id:
                return False

        if sel_classes:
            class_attr = norm_attrs.get("class", "")
            classes = [c.lower() for c in re.split(r"\s+", class_attr.strip()) if c]
            for cls in sel_classes:
                if cls not in classes:
                    return False

        return True

    @staticmethod
    def normalize_text(s: str) -> str:
        """折叠空白：去首尾、把行内连续空白压成单空格、丢弃空行。"""
        if not s:
            return ""
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        lines: List[str] = []
        for line in s.split("\n"):
            line = re.sub(r"[ \t\f\v\u00a0]+", " ", line).strip()
            if line:
                lines.append(line)
        return "\n".join(lines).strip()


__all__ = ["ContentExtractor", "ExtractResult"]
