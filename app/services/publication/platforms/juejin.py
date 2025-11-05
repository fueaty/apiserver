"""
掘金平台发布实现
"""

import json
import time
from typing import Dict, Any
from app.services.publication.platforms.base import BasePlatform


class JuejinPlatform(BasePlatform):
    """掘金平台发布类"""
    
    def __init__(self, platform_code: str, config: Dict[str, Any]):
        super().__init__(platform_code, config)
        self.access_token = None
        
    async def publish(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """发布内容到掘金"""
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
                    
                    if result_data.get('err_no') == 0:
                        article_data = result_data.get('data', {})
                        article_id = article_data.get('article_id')
                        article_url = f"https://juejin.cn/post/{article_id}"
                        
                        return self._create_result(
                            True,
                            publication_id=article_id,
                            url=article_url,
                            raw_response=result_data
                        )
                    else:
                        error_msg = result_data.get('err_msg', '发布失败')
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
        """构建掘金API请求数据"""
        request_data = {
            'title': content.get('title', ''),
            'content': content.get('body', ''),
            'tag_ids': content.get('tag_ids', []),
            'category_id': content.get('category_id', 1),
            'mark_content': content.get('summary', ''),
            'brief_content': content.get('brief_content', ''),
            'cover_image': content.get('cover_image', ''),
            'is_english': False,
            'is_private': False,
            'is_markdown': True
        }
        
        # 添加认证信息
        if self.access_token:
            request_data['aid'] = self.credentials.get('aid')
            request_data['uuid'] = self.credentials.get('uuid')
            request_data['user_id'] = self.credentials.get('user_id')
            
        return request_data
    
    def _build_headers(self, platform_config: Dict[str, Any]) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://juejin.cn/'
        }
        
        # 添加认证头
        if self.access_token:
            headers['X-Juejin-Token'] = self.access_token
            headers['X-Juejin-Src'] = 'web'
        
        # 添加配置中的额外头信息
        config_headers = platform_config.get('request', {}).get('headers', {})
        headers.update(config_headers)
        
        return headers
    
    def _validate_content(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> tuple:
        """验证掘金内容格式"""
        # 基础验证
        is_valid, error_msg = super()._validate_content(content, platform_config)
        if not is_valid:
            return False, error_msg
        
        # 掘金特定验证
        constraints = platform_config.get('constraints', {})
        
        title = content.get('title', '')
        if len(title) > constraints.get('max_title_length', 100):
            return False, f"标题长度超过限制: {len(title)} > {constraints.get('max_title_length', 100)}"
        
        body = content.get('body', '')
        if len(body) > constraints.get('max_body_length', 50000):
            return False, f"内容长度超过限制: {len(body)} > {constraints.get('max_body_length', 50000)}"
        
        # 检查标签数量
        tags = content.get('tags', [])
        if len(tags) > constraints.get('max_tags', 5):
            return False, f"标签数量超过限制: {len(tags)} > {constraints.get('max_tags', 5)}"
        
        # 检查图片数量
        images = content.get('image_urls', [])
        if len(images) > constraints.get('max_images', 10):
            return False, f"图片数量超过限制: {len(images)} > {constraints.get('max_images', 10)}"
        
        return True, "验证通过"