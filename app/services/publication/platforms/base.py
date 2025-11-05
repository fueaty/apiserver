"""
平台发布基类
定义所有平台发布实现的通用接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
import aiohttp


class BasePlatform(ABC):
    """平台发布基类"""
    
    def __init__(self, platform_code: str, config: Dict[str, Any]):
        self.platform_code = platform_code
        self.config = config
        self.session = None
        self.credentials = None
        
    def set_credentials(self, credentials: Dict[str, Any]):
        """设置平台认证信息"""
        self.credentials = credentials
        
    @abstractmethod
    async def publish(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """发布内容（必须实现）"""
        pass
    
    async def get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.config.get('timeout', 15))
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def cleanup(self):
        """清理资源，销毁敏感信息"""
        if self.session:
            await self.session.close()
        # 清除内存中的认证信息
        self.credentials = None
    
    def _validate_content(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Tuple[bool, str]:
        """验证内容格式"""
        required_fields = platform_config.get('required_fields', ['title', 'body'])
        for field in required_fields:
            if field not in content:
                return False, f"缺少必要字段: {field}"
        return True, "验证通过"
    
    def _map_content(self, content: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """映射内容字段到平台格式"""
        field_mapping = platform_config.get('request', {}).get('field_mapping', {})
        mapped = {}
        
        for target_field, source_info in field_mapping.items():
            if isinstance(source_info, dict) and 'source' in source_info:
                source_field = source_info['source']
                default = source_info.get('default')
                mapped[target_field] = content.get(source_field, default)
            elif isinstance(source_info, str):
                mapped[target_field] = content.get(source_info)
        
        # 添加未映射的额外字段
        for key, value in content.items():
            if key not in field_mapping.values():
                mapped[key] = value
                
        return mapped
    
    def _create_result(self, success: bool, **kwargs) -> Dict[str, Any]:
        """创建发布结果"""
        result = {
            'platform': self.platform_code,
            'success': success,
            'status': 'published' if success else 'failed',
            'publication_id': kwargs.get('publication_id'),
            'url': kwargs.get('url'),
            'error_message': kwargs.get('error_msg'),
            'raw_response': kwargs.get('raw_response')
        }
        return result