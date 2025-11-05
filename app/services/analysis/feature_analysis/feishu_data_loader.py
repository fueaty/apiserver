from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from ...feishu.feishu_service import FeishuService
from ....core.config import config_manager

logger = logging.getLogger(__name__)


class FeishuDataLoader:
    """飞书表格数据加载器，用于从飞书表格读取热点数据"""
    
    def __init__(self):
        # 从配置中读取飞书表格信息
        self.config = config_manager.get_config().get('feature_analysis', {})
        self.app_token = self.config.get('feishu', {}).get('app_token', 'EhSmbB0x0aujxXsNgPncjIyLntc')
        self.table_id = self.config.get('feishu', {}).get('table_id', 'tblOkYEu3bc87Tuo')
        self.timeout = self.config.get('feishu', {}).get('timeout', 30)
        self.retry_count = self.config.get('feishu', {}).get('retry_count', 3)
        
        # 初始化飞书客户端
        self.feishu_service = FeishuService()
    
    async def get_top_hotspots(self, date: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        从飞书表格获取排名靠前的热点数据
        
        Args:
            date: 日期过滤，格式YYYY-MM-DD，默认为当天
            limit: 返回的热点数量限制
            
        Returns:
            热点数据列表，每个热点包含url、标题、排名等信息
        """
        logger.info(f"正在获取热点数据，日期: {date}, 限制: {limit}")
        
        try:
            # 如果没有指定日期，使用当天日期
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            
            # 获取所有热点数据（支持分页）
            all_records = await self._get_all_records()
            
            # 过滤指定日期的数据
            date_records = self._filter_by_date(all_records, date)
            
            # 按排名排序并限制数量
            sorted_records = sorted(date_records, key=lambda x: self._get_rank(x), reverse=False)
            
            # 返回前limit条记录
            top_records = sorted_records[:limit]
            
            # 转换为标准格式
            hotspots = [self._convert_to_hotspot_format(record) for record in top_records]
            
            logger.info(f"成功获取{len(hotspots)}条热点数据")
            return hotspots
            
        except Exception as e:
            logger.error(f"获取热点数据失败: {str(e)}")
            raise
    
    async def get_hotspots_by_date_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        获取日期范围内的热点数据
        
        Args:
            start_date: 开始日期，格式YYYY-MM-DD
            end_date: 结束日期，格式YYYY-MM-DD
            
        Returns:
            热点数据列表
        """
        logger.info(f"正在获取日期范围[{start_date}至{end_date}]的热点数据")
        
        try:
            # 获取所有热点数据
            all_records = await self._get_all_records()
            
            # 过滤日期范围内的数据
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            
            range_records = []
            for record in all_records:
                record_date_str = self._get_record_date(record)
                if record_date_str:
                    record_date = datetime.strptime(record_date_str, '%Y-%m-%d')
                    if start_date_obj <= record_date <= end_date_obj:
                        range_records.append(record)
            
            # 转换为标准格式
            hotspots = [self._convert_to_hotspot_format(record) for record in range_records]
            
            logger.info(f"成功获取{len(hotspots)}条热点数据")
            return hotspots
            
        except Exception as e:
            logger.error(f"获取日期范围热点数据失败: {str(e)}")
            raise
    
    async def _get_all_records(self) -> List[Dict[str, Any]]:
        """
        获取表格中的所有记录，处理分页
        
        Returns:
            所有记录的列表
        """
        all_records = []
        page_token = None
        page_size = 100  # 飞书API最大支持100条/页
        
        while True:
            logger.debug(f"正在获取第{len(all_records) // page_size + 1}页数据")
            response = await self.feishu_service.list_records(
                app_token=self.app_token,
                table_id=self.table_id,
                page_size=page_size,
                page_token=page_token
            )
            
            records = response.get('items', [])
            all_records.extend(records)
            
            page_token = response.get('page_token')
            if not page_token:
                break
        
        logger.debug(f"总共获取到{len(all_records)}条记录")
        return all_records
    
    def _filter_by_date(self, records: List[Dict[str, Any]], date: str) -> List[Dict[str, Any]]:
        """
        根据日期过滤记录
        
        Args:
            records: 记录列表
            date: 日期字符串，格式YYYY-MM-DD
            
        Returns:
            过滤后的记录列表
        """
        filtered = []
        for record in records:
            record_date = self._get_record_date(record)
            if record_date == date:
                filtered.append(record)
        return filtered
    
    def _get_record_date(self, record: Dict[str, Any]) -> Optional[str]:
        """
        从记录中提取日期
        
        Args:
            record: 飞书表格记录
            
        Returns:
            日期字符串，格式YYYY-MM-DD，或None
        """
        fields = record.get('fields', {})
        
        # 尝试不同可能的日期字段名
        date_fields = ['date', '日期', 'collected_at', '采集时间', 'hot_date']
        
        for field in date_fields:
            if field in fields:
                date_value = fields[field]
                # 处理不同格式的日期
                if isinstance(date_value, str):
                    # 尝试解析不同的日期格式
                    try:
                        # 尝试ISO格式 YYYY-MM-DD
                        if len(date_value) >= 10 and date_value[4] == '-' and date_value[7] == '-':
                            return date_value[:10]
                        # 尝试其他格式
                        parsed_date = datetime.strptime(date_value[:10], '%Y-%m-%d')
                        return parsed_date.strftime('%Y-%m-%d')
                    except:
                        continue
                elif isinstance(date_value, dict) and 'date' in date_value:
                    # 处理飞书日期对象格式
                    return date_value['date']
        
        return None
    
    def _get_rank(self, record: Dict[str, Any]) -> int:
        """
        从记录中提取排名
        
        Args:
            record: 飞书表格记录
            
        Returns:
            排名整数
        """
        fields = record.get('fields', {})
        
        # 尝试不同可能的排名字段名
        rank_fields = ['rank', '排名', 'hot_rank', '序号']
        
        for field in rank_fields:
            if field in fields:
                try:
                    return int(fields[field])
                except:
                    continue
        
        # 如果找不到排名，返回一个较大的数
        return 999
    
    def _convert_to_hotspot_format(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        将飞书表格记录转换为标准的热点格式
        
        Args:
            record: 飞书表格记录
            
        Returns:
            标准热点格式字典
        """
        fields = record.get('fields', {})
        
        # 提取关键字段，尝试不同的可能字段名
        url = None
        url_fields = ['url', '链接', 'hot_url', '热点链接']
        for field in url_fields:
            if field in fields:
                url = fields[field]
                break
        
        title = None
        title_fields = ['title', '标题', 'hot_title', '热点标题']
        for field in title_fields:
            if field in fields:
                title = fields[field]
                break
        
        # 构建标准格式
        hotspot = {
            'id': record.get('record_id', ''),
            'url': url,
            'title': title,
            'rank': self._get_rank(record),
            'date': self._get_record_date(record),
            'raw_fields': fields  # 保留原始字段，以便后续处理
        }
        
        # 尝试提取其他可能有用的字段
        for key, value in fields.items():
            if key not in ['id', 'url', 'title', 'rank', 'date', 'raw_fields']:
                # 使用英文键名
                english_key = self._get_english_key(key)
                hotspot[english_key] = value
        
        return hotspot
    
    def _get_english_key(self, chinese_key: str) -> str:
        """
        将中文键名转换为英文键名
        
        Args:
            chinese_key: 中文键名
            
        Returns:
            英文键名
        """
        key_mapping = {
            '热度': 'hot_value',
            '来源': 'source',
            '平台': 'platform',
            '发布时间': 'publish_time',
            '采集时间': 'collected_at',
            '摘要': 'summary',
            '关键词': 'keywords'
        }
        
        return key_mapping.get(chinese_key, chinese_key.lower())