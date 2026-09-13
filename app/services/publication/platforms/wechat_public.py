"""
微信公众号平台发布实现
"""

import json
from typing import Dict, Any
from app.services.publication.platforms.base import BasePlatform


class WechatPublicPlatform(BasePlatform):
    """微信公众号平台发布类"""

    def __init__(self, platform_code: str, config: Dict[str, Any]):
        super().__init__(platform_code, config)
        self.access_token = None

    async def publish(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """发布内容到微信公众号（新增永久图文素材）"""
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

            # 发送发布请求（微信 access_token 走 URL query，不走请求头）
            session = await self.get_session()
            headers = self._build_headers(platform_config)

            async with session.post(
                platform_config['request']['url'],
                headers=headers,
                params={'access_token': self.access_token},
                json=request_data
            ) as response:
                raw_response = await response.text()

                if response.status == 200:
                    result_data = json.loads(raw_response)

                    # 微信接口约定：有 media_id 即成功；有非 0 errcode 即失败
                    errcode = result_data.get('errcode', 0)
                    if errcode in (0, None) and result_data.get('media_id'):
                        media_id = result_data.get('media_id')
                        return self._create_result(
                            True,
                            publication_id=media_id,
                            # 永久素材 media_id 本身不携带可访问 URL，
                            # 群发/发布后需再调 freepublish 或 GET 素材接口换取链接；
                            # 若上游网关已返回 url 则直接采用。
                            url=result_data.get('url'),
                            raw_response=result_data
                        )
                    else:
                        error_msg = result_data.get('errmsg') or f"微信接口错误: errcode={errcode}"
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
        """构建微信公众号新增图文素材请求数据

        微信 add_news 的请求体是 {"articles": [ {...}, ... ]}，至少一篇。
        """
        article = {
            'title': content.get('title', ''),
            'content': content.get('content') or content.get('body', ''),
            'author': content.get('author', ''),
            'digest': content.get('digest') or content.get('summary', ''),
            'content_source_url': content.get('content_source_url', ''),
            'show_cover_pic': content.get('show_cover_pic', 1),
        }

        # thumb_media_id 是 add_news 的必填封面素材 ID，凭据或内容中提供时带上
        thumb_media_id = content.get('thumb_media_id')
        if not thumb_media_id and self.credentials:
            thumb_media_id = self.credentials.get('thumb_media_id')
        if thumb_media_id:
            article['thumb_media_id'] = thumb_media_id

        return {'articles': [article]}

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
        """验证微信公众号内容格式"""
        # 基础验证
        is_valid, error_msg = super()._validate_content(content, platform_config)
        if not is_valid:
            return False, error_msg

        # 微信公众号特定验证
        constraints = platform_config.get('constraints', {})

        title = content.get('title', '')
        if len(title) > constraints.get('max_title_length', 64):
            return False, f"标题长度超过限制: {len(title)} > {constraints.get('max_title_length', 64)}"

        body = content.get('body', '')
        if len(body) > constraints.get('max_body_length', 20000):
            return False, f"内容长度超过限制: {len(body)} > {constraints.get('max_body_length', 20000)}"

        return True, "验证通过"
