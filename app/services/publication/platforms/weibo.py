"""
微博平台发布实现
"""

import json
import time
from typing import Dict, Any
from app.services.publication.platforms.base import BasePlatform


class WeiboPlatform(BasePlatform):
    """微博平台发布类"""
    
    def __init__(self, platform_code: str, config: Dict[str, Any]):
        super().__init__(platform_code, config)
        self.access_token = None
        
    async def publish(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """发布内容到微博"""
        try:
            # 验证内容格式
            is_valid, error_msg = self._validate_content(content, platform_config)
            if not is_valid:
                return self._create_result(False, error_msg=error_msg)
            
            # 映射内容字段
            mapped_content = self._map_content(content, platform_config)
            
            # 获取认证信息
            if not self.credentials:
                return self._create_result(False, error_msg="未设置认证信息")
                
            self.access_token = self.credentials.get('access_token')
            if not self.access_token:
                return self._create_result(False, error_msg="缺少access_token")
            
            # 构建请求数据
            request_data = self._build_request_data(mapped_content, platform_config)
            
            # 发送发布请求
            session = await self.get_session()
            headers = self._build_headers(platform_config)
            
            async with session.post(
                platform_config['request']['url'],
                headers=headers,
                json=request_data
            ) as response:
                raw_response = await response.text()
                
                if response.status == 200:
                    result_data = json.loads(raw_response)
                    
                    if result_data.get('error_code') == 0:
                        article_id = result_data.get('id')
                        article_url = f"https://weibo.com/ttarticle/p/show?id={article_id}"
                        
                        return self._create_result(
                            True,
                            publication_id=article_id,
                            url=article_url,
                            raw_response=result_data
                        )
                    else:
                        error_msg = result_data.get('error', '发布失败')
                        return self._create_result(False, error_msg=error_msg, raw_response=result_data)
                else:
                    return self._create_result(
                        False, 
                        error_msg=f"HTTP错误: {response.status}",
                        raw_response=raw_response
                    )
                    
        except Exception as e:
            return self._create_result(False, error_msg=f"发布异常: {str(e)}")
    
    def _build_request_data(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """构建微博API请求数据"""
        request_data = {
            'access_token': self.access_token,
            'title': content.get('title', ''),
            'content': content.get('body', ''),
            'tags': content.get('tags', ''),
            'publish_time': content.get('publish_time', int(time.time()))
        }
        
        # 微博文章特有字段
        if 'summary' in content:
            request_data['summary'] = content['summary']
        if 'cover_url' in content:
            request_data['cover_url'] = content['cover_url']
            
        return request_data
    
    def _build_headers(self, platform_config: Dict[str, Any]) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # 添加配置中的额外头信息
        config_headers = platform_config.get('request', {}).get('headers', {})
        headers.update(config_headers)
        
        return headers
    
    def _validate_content(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> tuple:
        """验证微博内容格式"""
        # 基础验证
        is_valid, error_msg = super()._validate_content(content, platform_config)
        if not is_valid:
            return False, error_msg
        
        # 微博特定验证
        constraints = platform_config.get('constraints', {})
        
        body = content.get('body', '')
        if len(body) > constraints.get('max_text_length', 2000):
            return False, f"正文长度超过限制: {len(body)} > {constraints.get('max_text_length', 2000)}"
        
        return True, "验证通过"