# -*- coding: utf-8 -*-
"""大模型客户端与工厂（需求③：ai_insights 深度内容生成）

本模块集中定义三种 LLM 客户端，供 ``llm_processor`` 与 ``insights_service`` 共享：

  - ``BaseLLMClient``        ：抽象接口；``generate``(async) 与 ``generate_sync`` 为**硬契约**
                               （llm_processor.py 第 56/251/282 行依赖这两个方法，签名不可改）。
  - ``OpenAICompatClient``   ：走 OpenAI 兼容协议（httpx），真实调用。
  - ``LLMMockClient``        ：由 llm_processor.py 原样迁入的模拟实现（行为不变）。

  - ``build_llm_client()``   ：按 ``api_key`` / ``base_url`` 是否有值选择 real / mock。

安全约定（务必遵守）：
  - ``api_key`` 只从 ``config/credentials.yaml`` 的 ``llm`` 段读取，**绝不硬编码**；
  - **日志/异常绝不打印 api_key**，仅记录 provider / model。

兼容性：Python 3.9（一律 ``typing.*``；禁 ``X|Y`` / ``match`` / 内建泛型）。
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------
class BaseLLMClient:
    """大模型客户端抽象基类。

    ``generate`` 为异步接口，``generate_sync`` 为同步接口，二者签名必须保持一致，
    因为调用方（``llm_processor``）同时依赖两者。
    """

    async def generate(self, prompt: str, temperature: float = 0.7,
                       max_tokens: int = 1000) -> str:
        """异步生成文本。子类必须实现。"""
        raise NotImplementedError

    def generate_sync(self, prompt: str, temperature: float = 0.7,
                      max_tokens: int = 1000) -> str:
        """同步生成文本。子类必须实现。"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 真实客户端：OpenAI 兼容协议
# ---------------------------------------------------------------------------
class OpenAICompatClient(BaseLLMClient):
    """OpenAI 兼容协议客户端（httpx）。

    请求：``POST {base_url}/chat/completions``
    body ：``{"model", "messages": [{"role":"user","content":prompt}], "temperature", "max_tokens"}``
    解析：``choices[0].message.content``；非 200 或解析失败直接 raise（由上层转 error_code）。
    """

    def __init__(self, provider: str, model_name: str, base_url: str,
                 api_key: str, timeout: int = 30):
        self.provider = provider
        self.model_name = model_name
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        # ⚠️ 只记 provider/model，绝不打印 api_key
        logger.info("初始化 OpenAI 兼容客户端: provider=%s model=%s", provider, model_name)

    # -- 内部构造 ---------------------------------------------------------
    def _endpoint(self) -> str:
        return "%s/chat/completions" % self.base_url

    def _headers(self) -> dict:
        return {
            "Authorization": "Bearer %s" % self.api_key,
            "Content-Type": "application/json",
        }

    def _payload(self, prompt: str, temperature: float, max_tokens: int) -> dict:
        return {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    @staticmethod
    def _extract_content(data: dict) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("LLM 响应解析失败: %s" % exc)
        if content is None:
            raise ValueError("LLM 响应内容为空")
        return content

    # -- 接口实现 ---------------------------------------------------------
    async def generate(self, prompt: str, temperature: float = 0.7,
                       max_tokens: int = 1000) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoint(),
                headers=self._headers(),
                json=self._payload(prompt, temperature, max_tokens),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        return self._extract_content(data)

    def generate_sync(self, prompt: str, temperature: float = 0.7,
                      max_tokens: int = 1000) -> str:
        with httpx.Client() as client:
            response = client.post(
                self._endpoint(),
                headers=self._headers(),
                json=self._payload(prompt, temperature, max_tokens),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        return self._extract_content(data)


# ---------------------------------------------------------------------------
# 模拟客户端（自 llm_processor.py 原样迁入，行为不变）
# ---------------------------------------------------------------------------
class LLMMockClient(BaseLLMClient):
    """
    大模型客户端的模拟实现
    实际使用时需要替换为真实的API调用
    """

    def __init__(self, provider: str = 'openai', model_name: str = 'gpt-4-turbo'):
        self.provider = provider
        self.model_name = model_name
        logger.info("创建模拟大模型客户端: %s - %s" % (provider, model_name))

    async def generate(self, prompt: str, temperature: float = 0.7,
                       max_tokens: int = 1000) -> str:
        """异步生成文本"""
        # 模拟延迟
        await asyncio.sleep(1)
        # 模拟返回结果
        return self._mock_response(prompt)

    def generate_sync(self, prompt: str, temperature: float = 0.7,
                      max_tokens: int = 1000) -> str:
        """同步生成文本"""
        # 模拟延迟
        time.sleep(0.5)
        # 模拟返回结果
        return self._mock_response(prompt)

    def _mock_response(self, prompt: str) -> str:
        """生成模拟响应"""
        # 根据提示内容生成不同的模拟响应
        if '请对以下新闻热点进行全面分析' in prompt:
            # 提取标题信息
            title_match = re.search(r'【热点标题】\n(.*?)\n', prompt)
            title = title_match.group(1) if title_match else '未知标题'

            # 模拟分析结果
            mock_result = {
                "entities": [
                    {
                        "name": "示例实体1",
                        "type": "组织",
                        "importance": "高"
                    },
                    {
                        "name": "示例实体2",
                        "type": "人物",
                        "importance": "中"
                    }
                ],
                "keywords": [
                    {
                        "word": "关键词1",
                        "relevance": 5
                    },
                    {
                        "word": "关键词2",
                        "relevance": 4
                    }
                ],
                "sentiment": "中性",
                "title_attractiveness": 7,
                "virality_score": 6,
                "topic_category": "科技",
                "sub_category": "AI",
                "summary": "关于%s的热点新闻分析" % title,
                "potential_impact": "中"
            }

            return json.dumps(mock_result, ensure_ascii=False)

        # 针对 ai_insights 生成提示的模拟返回（保持 JSON 结构可被解析）
        if 'AI_INSIGHTS_JSON' in prompt:
            title_match = re.search(r'标题[:：]\s*(.*)', prompt)
            title = title_match.group(1).strip() if title_match else '未知标题'
            mock_insight = {
                "summary": "关于%s的深度摘要" % title,
                "tags": ["热点", "科技", "观察"],
                "sentiment": "中性",
                "seo_title": "%s - 深度解读" % title,
                "seo_description": "围绕%s的背景、影响与看点解读。" % title,
                "seo_keywords": "%s,热点,解读" % title,
                "category": "科技",
            }
            return json.dumps(mock_insight, ensure_ascii=False)

        # 默认响应
        return "这是一个模拟响应"


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
def build_llm_client(provider: str, model_name: str,
                     base_url: Optional[str] = None,
                     api_key: Optional[str] = None,
                     timeout: int = 30) -> Tuple[BaseLLMClient, str]:
    """按配置构建 LLM 客户端。

    - 有 ``api_key`` 且 ``base_url`` → ``(OpenAICompatClient, 'real')``
    - 否则 → ``(LLMMockClient, 'mock')``（无外部依赖，链路仍可跑通）

    Returns:
        (client, mode)，mode ∈ {'real', 'mock'}
    """
    if api_key and base_url:
        client = OpenAICompatClient(
            provider=provider,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        return client, "real"
    return LLMMockClient(provider=provider, model_name=model_name), "mock"


__all__ = [
    "BaseLLMClient",
    "OpenAICompatClient",
    "LLMMockClient",
    "build_llm_client",
]
