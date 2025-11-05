from typing import Dict, Any, List, Optional
import logging
import json
import asyncio
from datetime import datetime

from ....core.config import config_manager

logger = logging.getLogger(__name__)


class LLMProcessor:
    """大模型处理器，用于使用大模型分析热点特征"""
    
    def __init__(self):
        # 从配置中读取大模型相关信息
        self.config = config_manager.get_config().get('feature_analysis', {})
        self.llm_config = self.config.get('llm', {})
        self.provider = self.llm_config.get('provider', 'openai')
        self.model_name = self.llm_config.get('model_name', 'gpt-4-turbo')
        self.temperature = self.llm_config.get('temperature', 0.3)
        self.max_tokens = self.llm_config.get('max_tokens', 2000)
        
        # 初始化大模型客户端
        self.llm_client = self._initialize_llm_client()
    
    def _initialize_llm_client(self):
        """
        初始化大模型客户端
        
        Returns:
            大模型客户端实例
        """
        # 这里根据不同的provider初始化不同的客户端
        # 目前返回一个模拟客户端，实际实现时需要替换为真实的SDK调用
        logger.info(f"初始化大模型客户端: {self.provider} - {self.model_name}")
        return LLMMockClient(provider=self.provider, model_name=self.model_name)
    
    async def analyze_hotspot(self, hotspot: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析单个热点的特征
        
        Args:
            hotspot: 热点数据字典，包含url、title等信息
            
        Returns:
            分析结果，包含实体、关键词、情感等特征
        """
        logger.info(f"正在分析热点: {hotspot.get('title', 'Unknown')}")
        
        try:
            # 准备分析提示
            prompt = self._prepare_analysis_prompt(hotspot)
            
            # 调用大模型
            response = await self.llm_client.generate(prompt, self.temperature, self.max_tokens)
            
            # 解析结果
            analysis_result = self._parse_analysis_result(response)
            
            # 合并结果
            full_result = {
                'hotspot_id': hotspot.get('id'),
                'url': hotspot.get('url'),
                'title': hotspot.get('title'),
                'analysis_time': datetime.now().isoformat(),
                'analysis_result': analysis_result
            }
            
            logger.info(f"热点分析完成: {hotspot.get('title', 'Unknown')}")
            return full_result
            
        except Exception as e:
            logger.error(f"热点分析失败: {str(e)}")
            # 返回错误结果
            return {
                'hotspot_id': hotspot.get('id'),
                'url': hotspot.get('url'),
                'title': hotspot.get('title'),
                'analysis_time': datetime.now().isoformat(),
                'error': str(e),
                'analysis_result': None
            }
    
    async def batch_analyze_hotspots(self, hotspots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量分析多个热点
        
        Args:
            hotspots: 热点数据列表
            
        Returns:
            分析结果列表
        """
        logger.info(f"开始批量分析{len(hotspots)}个热点")
        
        # 使用并发处理提高效率
        tasks = [self.analyze_hotspot(hotspot) for hotspot in hotspots]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                hotspot = hotspots[i]
                error_result = {
                    'hotspot_id': hotspot.get('id'),
                    'url': hotspot.get('url'),
                    'title': hotspot.get('title'),
                    'analysis_time': datetime.now().isoformat(),
                    'error': str(result),
                    'analysis_result': None
                }
                processed_results.append(error_result)
            else:
                processed_results.append(result)
        
        logger.info(f"批量分析完成，成功分析{sum(1 for r in processed_results if 'error' not in r)}个热点")
        return processed_results
    
    def _prepare_analysis_prompt(self, hotspot: Dict[str, Any]) -> str:
        """
        准备分析提示词
        
        Args:
            hotspot: 热点数据
            
        Returns:
            格式化的提示词
        """
        title = hotspot.get('title', '')
        url = hotspot.get('url', '')
        summary = hotspot.get('summary', '')
        
        prompt = f"""
        请对以下新闻热点进行全面分析，并以JSON格式返回分析结果。
        
        【热点标题】
        {title}
        
        【热点链接】
        {url}
        
        【热点摘要】
        {summary}
        
        请按照以下格式返回分析结果，确保JSON格式正确：
        {{
            "entities": [
                {{
                    "name": "实体名称",
                    "type": "实体类型(人物/地点/组织/事件等)",
                    "importance": "重要性(高/中/低)"
                }}
                // 可以有多个实体
            ],
            "keywords": [
                {{
                    "word": "关键词",
                    "relevance": "相关度(1-5)"
                }}
                // 可以有多个关键词
            ],
            "sentiment": "情感倾向(积极/中性/消极)",
            "title_attractiveness": "标题吸引力评分(1-10)",
            "virality_score": "传播潜力评分(1-10)",
            "topic_category": "主题分类",
            "sub_category": "子分类",
            "summary": "核心内容总结(50字以内)",
            "potential_impact": "潜在影响分析(高/中/低)"
        }}
        
        请确保返回的是有效的JSON格式，不要包含任何其他无关的文字。
        """
        
        return prompt.strip()
    
    def _parse_analysis_result(self, response: str) -> Dict[str, Any]:
        """
        解析大模型返回的分析结果
        
        Args:
            response: 大模型返回的文本
            
        Returns:
            解析后的结果字典
        """
        try:
            # 尝试直接解析JSON
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            # 如果JSON解析失败，尝试提取JSON部分
            logger.warning(f"JSON解析失败，尝试提取JSON部分: {response[:100]}...")
            
            # 尝试查找JSON格式的部分
            import re
            json_match = re.search(r'\{[^}]*\}', response)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    return result
                except:
                    pass
            
            # 返回默认结果
            return {
                'entities': [],
                'keywords': [],
                'sentiment': '中性',
                'title_attractiveness': 5,
                'virality_score': 5,
                'topic_category': '未分类',
                'sub_category': '未分类',
                'summary': '无法解析分析结果',
                'potential_impact': '中'
            }
    
    def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """
        提取文本中的实体
        
        Args:
            text: 待分析文本
            
        Returns:
            实体列表
        """
        # 这里可以调用专门的实体识别接口，或者使用当前的大模型
        prompt = f"""
        请从以下文本中提取所有实体，并以JSON格式返回。
        
        【文本】
        {text}
        
        【格式要求】
        {{
            "entities": [
                {{
                    "name": "实体名称",
                    "type": "实体类型(人物/地点/组织/事件等)",
                    "importance": "重要性(高/中/低)"
                }}
            ]
        }}
        
        请确保返回的是有效的JSON格式。
        """
        
        # 同步调用，这里仅作为示例
        response = self.llm_client.generate_sync(prompt, 0.1, 1000)
        try:
            result = json.loads(response)
            return result.get('entities', [])
        except:
            return []
    
    def analyze_title_attractiveness(self, title: str) -> int:
        """
        分析标题吸引力
        
        Args:
            title: 标题文本
            
        Returns:
            吸引力评分(1-10)
        """
        prompt = f"""
        请对以下标题的吸引力进行评分(1-10分)，只返回数字评分。
        
        【标题】
        {title}
        
        【评分说明】
        1分: 非常平淡，无法引起兴趣
        10分: 极具吸引力，让人忍不住想点击查看
        
        请只返回数字评分，不要包含任何其他文字。
        """
        
        try:
            response = self.llm_client.generate_sync(prompt, 0.1, 10)
            # 提取数字
            import re
            score_match = re.search(r'\d+', response)
            if score_match:
                score = int(score_match.group())
                return max(1, min(10, score))  # 限制在1-10范围内
        except:
            pass
        
        return 5  # 默认评分


class LLMMockClient:
    """
    大模型客户端的模拟实现
    实际使用时需要替换为真实的API调用
    """
    
    def __init__(self, provider: str = 'openai', model_name: str = 'gpt-4-turbo'):
        self.provider = provider
        self.model_name = model_name
        logger.info(f"创建模拟大模型客户端: {provider} - {model_name}")
    
    async def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        """
        异步生成文本
        """
        # 模拟延迟
        await asyncio.sleep(1)
        
        # 模拟返回结果
        return self._mock_response(prompt)
    
    def generate_sync(self, prompt: str, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        """
        同步生成文本
        """
        # 模拟延迟
        import time
        time.sleep(0.5)
        
        # 模拟返回结果
        return self._mock_response(prompt)
    
    def _mock_response(self, prompt: str) -> str:
        """
        生成模拟响应
        """
        # 根据提示内容生成不同的模拟响应
        if '请对以下新闻热点进行全面分析' in prompt:
            # 提取标题信息
            import re
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
                "summary": f"关于{title}的热点新闻分析",
                "potential_impact": "中"
            }
            
            return json.dumps(mock_result, ensure_ascii=False)
        
        # 默认响应
        return "这是一个模拟响应"