"""
今日头条平台发布实现
"""

import json
import time
from typing import Dict, Any
from app.services.publication.platforms.base import BasePlatform


class ToutiaoPlatform(BasePlatform):
    """今日头条平台发布类"""

    def __init__(self, platform_code: str, config: Dict[str, Any]):
        super().__init__(platform_code, config)
        self.access_token = None

    async def publish(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """发布内容到今日头条"""
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

                    # 头条开放平台约定 code == 0 成功；兼容部分网关的 success 布尔
                    if result_data.get('code') == 0 or result_data.get('success'):
                        data = result_data.get('data') or {}
                        article_id = (
                            data.get('article_id')
                            or data.get('pgc_id')
                            or result_data.get('article_id')
                        )
                        article_url = (
                            result_data.get('url')
                            or (f"https://www.toutiao.com/article/{article_id}/" if article_id else None)
                        )

                        return self._create_result(
                            True,
                            publication_id=article_id,
                            url=article_url,
                            raw_response=result_data
                        )
                    else:
                        error_msg = (
                            result_data.get('message')
                            or result_data.get('msg')
                            or result_data.get('error')
                            or '发布失败'
                        )
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
        """构建今日头条API请求数据"""
        request_data = {
            'title': content.get('title', ''),
            'content': content.get('content') or content.get('body', ''),
            'image_urls': content.get('image_urls') or content.get('images', []),
            'tags': content.get('tags', []),
            'publish_time': content.get('publish_time', int(time.time()))
        }

        # 头条可选字段
        if 'summary' in content:
            request_data['abstract'] = content['summary']
        if 'category' in content:
            request_data['category'] = content['category']
        if 'cover_url' in content:
            request_data['cover_url'] = content['cover_url']

        return request_data

    def _build_headers(self, platform_config: Dict[str, Any]) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://mp.toutiao.com/'
        }

        # 添加认证头
        if self.access_token:
            headers['X-Toutiao-Token'] = self.access_token
            headers['Cookie'] = self.credentials.get('cookie', '') if self.credentials else ''

        if not headers.get('Cookie'):
            headers.pop('Cookie', None)

        # 添加配置中的额外头信息
        config_headers = platform_config.get('request', {}).get('headers', {})
        headers.update(config_headers)

        return headers

    def _validate_content(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> tuple:
        """验证今日头条内容格式"""
        # 基础验证
        is_valid, error_msg = super()._validate_content(content, platform_config)
        if not is_valid:
            return False, error_msg

        # 今日头条特定验证
        constraints = platform_config.get('constraints', {})

        title = content.get('title', '')
        if len(title) > constraints.get('max_title_length', 30):
            return False, f"标题长度超过限制: {len(title)} > {constraints.get('max_title_length', 30)}"

        body = content.get('body', '')
        if len(body) > constraints.get('max_body_length', 5000):
            return False, f"内容长度超过限制: {len(body)} > {constraints.get('max_body_length', 5000)}"

        # 检查图片数量
        images = content.get('image_urls') or content.get('images') or []
        max_images = constraints.get('max_images', 5)
        if len(images) > max_images:
            return False, f"图片数量超过限制: {len(images)} > {max_images}"

        return True, "验证通过"
