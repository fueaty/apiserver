"""
小红书平台发布实现
"""

import json
import time
from typing import Dict, Any
from app.services.publication.platforms.base import BasePlatform


class XiaohongshuPlatform(BasePlatform):
    """小红书平台发布类"""

    def __init__(self, platform_code: str, config: Dict[str, Any]):
        super().__init__(platform_code, config)
        self.access_token = None

    async def publish(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """发布内容到小红书"""
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
                params=self._build_query_params(platform_config),
                json=request_data
            ) as response:
                raw_response = await response.text()

                if response.status == 200:
                    result_data = json.loads(raw_response)

                    # 小红书网关同时存在 success 布尔与 code(0 为成功) 两种约定，二者取或
                    if result_data.get('success') or result_data.get('code') == 0:
                        data = result_data.get('data') or {}
                        note_id = data.get('note_id') or result_data.get('note_id')
                        article_url = (
                            result_data.get('url')
                            or (f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else None)
                        )

                        return self._create_result(
                            True,
                            publication_id=note_id,
                            url=article_url,
                            raw_response=result_data
                        )
                    else:
                        error_msg = (
                            result_data.get('error_message')
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
        """构建小红书API请求数据"""
        request_data = {
            'title': content.get('title', ''),
            'desc': content.get('content') or content.get('body', ''),
            'image_urls': content.get('image_urls') or content.get('images', []),
            'tags': content.get('tags', []),
            'publish_time': content.get('publish_time', int(time.time()))
        }

        # 小红书图文笔记的必填项：至少一张配图
        if 'cover_url' in content:
            request_data['cover_url'] = content['cover_url']
        if 'location' in content:
            request_data['location'] = content['location']

        return request_data

    def _build_query_params(self, platform_config: Dict[str, Any]) -> Dict[str, str]:
        """构建URL查询参数（部分网关要求 token 走 query）"""
        return {'access_token': self.access_token} if self.access_token else {}

    def _build_headers(self, platform_config: Dict[str, Any]) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        # 小红书开放接口通常还要求 cookie / 签名头，凭据中存在时一并带上
        if self.credentials:
            cookie = self.credentials.get('cookie')
            if cookie:
                headers['Cookie'] = cookie

        # 添加配置中的额外头信息
        config_headers = platform_config.get('request', {}).get('headers', {})
        headers.update(config_headers)

        return headers

    def _validate_content(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> tuple:
        """验证小红书内容格式"""
        # 基础验证
        is_valid, error_msg = super()._validate_content(content, platform_config)
        if not is_valid:
            return False, error_msg

        # 小红书特定验证
        constraints = platform_config.get('constraints', {})

        title = content.get('title', '')
        if len(title) > constraints.get('max_title_length', 50):
            return False, f"标题长度超过限制: {len(title)} > {constraints.get('max_title_length', 50)}"

        body = content.get('body', '')
        if len(body) > constraints.get('max_body_length', 1000):
            return False, f"内容长度超过限制: {len(body)} > {constraints.get('max_body_length', 1000)}"

        # 检查图片数量（小红书图文笔记必须至少 1 张、最多 9 张）
        images = content.get('image_urls') or content.get('images') or []
        max_images = constraints.get('max_images', 9)
        if len(images) > max_images:
            return False, f"图片数量超过限制: {len(images)} > {max_images}"
        if len(images) < 1:
            return False, "小红书图文笔记至少需要 1 张配图"

        return True, "验证通过"
