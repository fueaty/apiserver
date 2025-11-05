"""
内容发布管理器
基于策略模式的多平台内容发布器
"""

import asyncio
from typing import Dict, Any, List
from pathlib import Path
import importlib.util

from app.core.config import settings
from app.utils.logger import logger
from app.utils.yaml_loader import load_yaml_config
from app.services.feishu.feishu_service import FeishuService
from app.core.config import config_manager


class PublicationManager:
    """内容发布管理器"""
    
    def __init__(self):
        self.platform_factory = PlatformFactory(self)
        self.plugin_manager = PluginManager()
        self.platforms_config = self._load_platforms_config()
        self.feishu_service = FeishuService()
        
    def _load_platforms_config(self) -> Dict[str, Any]:
        """加载平台配置"""
        config_path = settings.PLATFORMS_CONFIG_FILE
        config_data = load_yaml_config(config_path)
        platforms_config = config_data.get("platforms", {}) if isinstance(config_data, dict) else {}
        
        if not platforms_config:
            logger.warning("平台配置为空，将使用默认配置")
            platforms_config = {
                "zhihu": {
                    "enabled": True,
                    "rate_limit": 10,
                    "timeout": 15
                }
            }
        
        return platforms_config
    
    async def publish(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行内容发布
        
        Args:
            request_data: 发布请求数据，包含platform、platform_credentials、content等
            
        Returns:
            发布结果
        """
        # 1. 解析请求参数
        platform_code = request_data.get('platform')
        credentials = request_data.get('platform_credentials', {})
        content = request_data.get('content', {})
        
        if not platform_code:
            return self._create_error_response("缺少平台标识(platform)")
        
        # 2. 获取平台实例
        platform_config = self.platforms_config.get(platform_code, {})
        if not platform_config.get("enabled", True):
            return self._create_error_response(f"平台暂未启用: {platform_code}")
        
        platform = self.platform_factory.create_platform(platform_code, platform_config)
        if not platform:
            return self._create_error_response(f"不支持的平台: {platform_code}")
        
        try:
            # 3. 设置认证信息
            platform.set_credentials(credentials)
            
            # 4. 执行前置插件
            context = {
                'platform_code': platform_code,
                'content_type': content.get('type', 'article'),
                'platform_config': platform_config
            }
            processed_content = await self.plugin_manager.apply_pre_plugins(content, context)
            
            # 5. 执行发布
            logger.info(f"开始发布到平台: {platform_code}")
            start_time = asyncio.get_event_loop().time()
            
            result = await platform.publish(processed_content, platform_config)
            
            # 6. 执行后置插件
            final_result = await self.plugin_manager.apply_post_plugins(result, context)
            final_result["platform_config"] = platform_config
            
            # 7. 记录性能指标
            cost_time = asyncio.get_event_loop().time() - start_time
            logger.info(
                "平台发布完成",
                extra={
                    "platform": platform_code,
                    "duration": f"{cost_time:.2f}s",
                    "success": result['success']
                }
            )
            
            # 8. 将发布结果存储到飞书表格
            if result['success']:
                await self._store_publish_result_to_feishu(platform_code, content, result)
            
            return self._format_response(final_result, platform_config)
            
        except Exception as e:
            error_msg = f"发布失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return self._create_error_response(error_msg)
        finally:
            # 9. 清理资源（确保敏感信息被销毁）
            if platform:
                await platform.cleanup()
    
    async def _store_publish_result_to_feishu(self, platform_code: str, content: Dict[str, Any], result: Dict[str, Any]):
        """
        将发布结果存储到飞书表格
        
        Args:
            platform_code: 平台代码
            content: 发布的内容
            result: 发布结果
        """
        try:
            # 获取飞书配置
            creds = config_manager.get_credentials()
            app_token = creds.get("feishu", {}).get("tables", {}).get("publish_tasks", {}).get("app_token")
            table_id = creds.get("feishu", {}).get("tables", {}).get("publish_tasks", {}).get("table_id")
            
            if not app_token or not table_id:
                logger.warning("飞书配置缺失，无法存储发布结果")
                return
            
            # 构造飞书记录
            feishu_record = {
                "fields": {
                    "task_id": result.get("publication_id", ""),
                    "platform_id": platform_code,
                    "content_id": content.get("id", ""),
                    "task_status": "完成" if result['success'] else "失败",
                    "actual_publish_time": result.get("publish_time", ""),
                    "publish_result": "成功" if result['success'] else "失败",
                    "publish_link": result.get("url", ""),
                    "error_message": result.get("error_message", "") if not result['success'] else ""
                }
            }
            
            # 确保表格字段同步
            from app.services.feishu.field_rules import TABLE_PLANS
            required_fields = TABLE_PLANS["publish_tasks"]["fields"]
            await self.feishu_service.ensure_table_fields(app_token, table_id, required_fields)
            
            # 插入记录
            await self.feishu_service.batch_add_records(app_token, table_id, [feishu_record])
            logger.info(f"发布结果已存储到飞书表格: {platform_code}")
            
        except Exception as e:
            logger.error(f"存储发布结果到飞书表格失败: {str(e)}")
    
    def _format_response(self, result: Dict[str, Any], platform_config: Dict[str, Any]) -> Dict[str, Any]:
        """格式化响应结果"""
        return {
            "code": 200 if result['success'] else 500,
            "message": "success" if result['success'] else result.get('error_message', '发布失败'),
            "data": {
                "platform": result['platform'],
                "publication_id": result.get('publication_id'),
                "url": result.get('url'),
                "status": result['status'],
                "constraints": platform_config.get('constraints', {})
            }
        }
    
    def _create_error_response(self, error_msg: str) -> Dict[str, Any]:
        """创建错误响应"""
        return {
            "code": 400,
            "message": error_msg,
            "data": None
        }
    
    def get_available_platforms(self) -> List[Dict[str, Any]]:
        """获取可用平台列表"""
        available_platforms = []
        
        for platform_code, config in self.platforms_config.items():
            available_platforms.append({
                "platform_code": platform_code,
                "name": config.get("name", platform_code),
                "rate_limit": config.get("rate_limit", 5),
                "timeout": config.get("timeout", 10)
            })
        
        return available_platforms


class PlatformFactory:
    """平台工厂类"""
    
    def __init__(self, manager: PublicationManager):
        self.platforms_dir = Path(__file__).parent / "platforms"
        self._loaded_platforms = {}
        self.manager = manager
        
    def create_platform(self, platform_code: str, platform_config: Dict[str, Any]):
        """创建平台实例"""
        if platform_code not in self._loaded_platforms:
            self._load_platform_module(platform_code)
        
        platform_class = self._loaded_platforms.get(platform_code)
        if platform_class:
            return platform_class(platform_code, platform_config)
        
        return None
    
    def _load_platform_module(self, platform_code: str):
        """动态加载平台模块"""
        platform_file = self.platforms_dir / f"{platform_code}.py"
        
        if not platform_file.exists():
            logger.warning(f"平台文件不存在: {platform_file}")
            return
        
        try:
            spec = importlib.util.spec_from_file_location(f"platforms.{platform_code}", platform_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 查找平台类（约定类名为 {PlatformCode}Platform）
            platform_class_name = f"{platform_code.capitalize()}Platform"
            platform_class = getattr(module, platform_class_name, None)
            
            if platform_class:
                self._loaded_platforms[platform_code] = platform_class
                logger.info(f"成功加载平台模块: {platform_code}")
            else:
                logger.warning(f"平台模块中未找到类: {platform_class_name}")
                
        except Exception as e:
            logger.error(f"加载平台模块失败: {platform_code}, 错误: {str(e)}")


class PluginManager:
    """插件管理器"""
    
    async def apply_pre_plugins(self, content: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """应用前置插件"""
        # 这里应该加载并执行前置插件
        # 简化实现，直接返回内容
        return content
    
    async def apply_post_plugins(self, result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """应用后置插件"""
        # 这里应该加载并执行后置插件
        # 简化实现，直接返回结果
        return result