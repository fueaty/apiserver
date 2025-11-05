"""
采集引擎核心调度器
基于Python脚本的网站信息采集引擎
"""

import asyncio
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.utils.logger import logger
from app.utils.yaml_loader import load_yaml_config
from .robots_checker import robots_checker


class CollectionEngine:
    """采集引擎核心调度器"""
    
    def __init__(self):
        self.site_factory = SiteFactory()
        self.plugin_manager = PluginManager()
        self.sites_config = self._load_sites_config()
        self.rate_limiters = self._init_rate_limiters()
        
    def _init_rate_limiters(self) -> Dict[str, Any]:
        """初始化站点级限流器"""
        limiters = {}
        
        for site_code, site_config in self.sites_config.items():
            if site_config.get("enabled", True):
                limiters[site_code] = AsyncRateLimiter(
                    max_calls=site_config.get("rate_limit", 5),
                    period=60  # 1分钟
                )
        return limiters
    
    def _load_sites_config(self) -> Dict[str, Any]:
        """加载站点配置"""
        config_path = settings.SITES_CONFIG_FILE
        config_data = load_yaml_config(config_path)
        sites_config = config_data.get("sites", {}) if isinstance(config_data, dict) else {}
        
        if not sites_config:
            logger.warning("站点配置为空，将使用默认配置")
            sites_config = {
                "weibo": {
                    "enabled": True,
                    "rate_limit": 5,
                    "timeout": 10
                }
            }
        
        return sites_config
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        执行采集任务
        
        Args:
            params: 采集参数，包含date、site_code等筛选条件
            
        Returns:
            结构化的采集结果
        """
        # 1. 解析采集参数
        target_date = params.get("date") or self._get_default_date()
        target_sites = self._get_target_sites(params.get("site_code"))
        logger.debug(f"目标站点列表: {target_sites}")
        
        # 2. 并发执行多站点采集
        results = []
        tasks = []
        
        for site_code in target_sites:
            site_config = self.sites_config.get(site_code, {})
            
            # 检查速率限制
            rate_limiter = self.rate_limiters.get(site_code)
            if rate_limiter:
                await rate_limiter.acquire()
                
            # 创建采集任务
            tasks.append(self._collect_single_site(site_code, target_date, params, site_config))
        
        # 3. 等待所有任务完成
        site_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 4. 处理采集结果
        for result in site_results:
            if isinstance(result, Exception):
                logger.error(f"采集任务失败: {str(result)}")
            elif result:
                results.append(result)
                
        return results
    
    async def _collect_single_site(self, site_code: str, date: str, params: Dict[str, Any], site_config: Dict[str, Any]) -> Dict[str, Any]:
        """采集单个站点数据"""
        site = None
        try:
            # 获取站点实例
            site = self.site_factory.create_site(site_code, site_config)
            if not site:
                logger.warning(f"站点配置不存在或加载失败: {site_code}")
                return None
                
            # 执行前置插件
            context = {
                "site_code": site_code,
                "date": date,
                "params": params,
                "site_config": site_config
            }
            await self.plugin_manager.apply_pre_plugins(site, context)
            
            # 执行采集
            logger.info(f"开始采集站点: {site_code}, 日期: {date}")
            start_time = asyncio.get_event_loop().time()
            
            site_params = self._prepare_site_params(params, site_code, site_config)
            data = await site.collect(site_params)
            
            # 执行后置插件
            processed_data = await self.plugin_manager.apply_post_plugins(data, context)
            
            # 记录性能指标
            cost_time = asyncio.get_event_loop().time() - start_time
            logger.info(f"站点采集完成: {site_code}, 耗时: {cost_time:.2f}s, 数据量: {len(processed_data)}")
            
            return {
                "site_code": site_code,
                "collect_time": self._get_current_time(),
                "data_count": len(processed_data),
                "news": processed_data
            }
            
        except Exception as e:
            logger.error(f"站点采集失败: {site_code}, 错误: {str(e)}", exc_info=True)
            return None
        finally:
            # 清理资源
            if site:
                await site.cleanup()
    
    def _get_target_sites(self, site_code_input = None) -> List[str]:
        """获取目标站点列表"""
        all_sites = [code for code, cfg in self.sites_config.items() if cfg.get("enabled", True)]
        
        if not site_code_input:
            return all_sites
        
        # 处理不同类型的输入
        if isinstance(site_code_input, str):
            # 字符串格式："site1,site2"
            target_sites = [code.strip() for code in site_code_input.split(",")]
        elif isinstance(site_code_input, list):
            # 列表格式：["site1", "site2"]
            target_sites = site_code_input
        else:
            # 其他类型转换为字符串处理
            target_sites = [str(site_code_input).strip()]
            
        return [code for code in target_sites if code in all_sites]
    
    def _prepare_site_params(self, base_params: Dict[str, Any], site_code: str, site_config: Dict[str, Any]) -> Dict[str, Any]:
        """准备站点特定参数"""
        site_params = base_params.copy()
        site_specific_params = site_config.get("params", {})
        site_params.update(site_specific_params)
        return site_params
    
    def _get_default_date(self) -> str:
        """获取默认日期（当天）"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
    
    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def get_available_sites(self) -> List[Dict[str, Any]]:
        """获取可用站点列表"""
        available_sites = []
        
        for site_code, config in self.sites_config.items():
            if config.get("enabled", True):
                available_sites.append({
                    "site_code": site_code,
                    "name": config.get("name", site_code),
                    "rate_limit": config.get("rate_limit", 5),
                    "timeout": config.get("timeout", 10)
                })
        
        return available_sites


class SiteFactory:
    """站点工厂类"""
    
    def __init__(self):
        self.sites_dir = Path(__file__).parent / "sites"
        self._loaded_sites = {}
        
    def create_site(self, site_code: str, site_config: Dict[str, Any]):
        """创建站点实例"""
        if site_code not in self._loaded_sites:
            self._load_site_module(site_code)
        
        site_class = self._loaded_sites.get(site_code)
        if site_class:
            return site_class(site_code, site_config)
        
        return None
    
    def _load_site_module(self, site_code: str):
        """动态加载站点模块"""
        site_file = self.sites_dir / f"{site_code}.py"
        
        if not site_file.exists():
            logger.warning(f"站点文件不存在: {site_file}")
            return
        
        try:
            spec = importlib.util.spec_from_file_location(f"app.services.collection.sites.{site_code}", site_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 查找站点类（约定类名为 {SiteCode}Site）
            # 处理下划线命名，将下划线后的首字母大写
            site_class_name = "".join(word.capitalize() for word in site_code.split("_")) + "Site"
            
            # 处理特殊命名规则
            if site_code == "weibo_advanced":
                site_class_name = "WeiboAdvancedSite"
            
            site_class = getattr(module, site_class_name, None)
            
            if site_class:
                self._loaded_sites[site_code] = site_class
                logger.info(f"成功加载站点模块: {site_code}")
            else:
                logger.warning(f"站点模块中未找到类: {site_class_name}")
                
        except Exception as e:
            logger.error(f"加载站点模块失败: {site_code}, 错误: {str(e)}")


class PluginManager:
    """插件管理器"""
    
    async def apply_pre_plugins(self, site, context: Dict[str, Any]):
        """应用前置插件"""
        # 这里应该加载并执行前置插件
        # 简化实现，直接返回
        pass
    
    async def apply_post_plugins(self, data: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """应用后置插件"""
        # 这里应该加载并执行后置插件
        # 简化实现，直接返回数据
        return data


class AsyncRateLimiter:
    """异步速率限制器"""
    
    def __init__(self, max_calls: int, period: int):
        self.max_calls = max_calls
        self.period = period
        self.semaphore = asyncio.Semaphore(max_calls)
        
    async def acquire(self):
        """获取许可"""
        await self.semaphore.acquire()
        # 简化实现，实际应该使用令牌桶算法
        await asyncio.sleep(self.period / self.max_calls)