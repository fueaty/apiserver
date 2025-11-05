"""
知乎热榜采集脚本
使用基础HTTP请求方式采集数据

获取知乎认证Token的方法：
1. 登录知乎网站 (https://www.zhihu.com)
2. 打开浏览器开发者工具 (F12)
3. 切换到 Network (网络) 标签
4. 刷新页面或访问知乎热榜页面 (https://www.zhihu.com/hot)
5. 查找请求 "hot-lists" 的API调用
6. 点击该请求，在 Headers 部分找到 "Authorization" 头
7. 复制 "Bearer" 后面的token值
8. 将token值填入配置文件 /root/apiserver/config/zhihu.yaml 中 access_token 或 authorization 字段

或者将token设置为环境变量:
export ZHIHU_TOKEN="your_token_here"
"""

import json
import time
import re
import os
import yaml
from typing import List, Dict, Any
from datetime import datetime
from .base import BaseSite
# 导入统一的ID生成函数
from ....utils.id_generator import generate_content_id


class ZhihuSite(BaseSite):
    """知乎热榜采集站点"""
    
    def __init__(self, site_code: str, config: Dict[str, Any]):
        super().__init__(site_code, config)
        self.load_zhihu_config()
    
    def load_zhihu_config(self):
        """加载知乎专用配置"""
        try:
            config_path = "/root/apiserver/config/zhihu.yaml"
            with open(config_path, 'r', encoding='utf-8') as f:
                self.zhihu_config = yaml.safe_load(f)
        except Exception as e:
            print(f"加载知乎配置文件失败: {e}")
            self.zhihu_config = {}
    
    async def collect(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集知乎热榜数据"""
        results = []
        
        try:
            # 知乎热榜API
            base_url = self.zhihu_config.get('api', {}).get('base_url', 'https://www.zhihu.com')
            endpoint = self.zhihu_config.get('api', {}).get('hotlist_endpoint', '/api/v3/feed/topstory/hot-lists/total')
            url = f"{base_url}{endpoint}"
            
            # 设置请求头
            headers = {
                'User-Agent': self.zhihu_config.get('web', {}).get('headers', {}).get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'),
                'Accept': 'application/json',
                'Accept-Language': self.zhihu_config.get('web', {}).get('headers', {}).get('accept_language', 'zh-CN,zh;q=0.9,en;q=0.8'),
                'Referer': self.zhihu_config.get('web', {}).get('headers', {}).get('referer', 'https://www.zhihu.com/hot'),
            }
            
            # 添加认证信息
            # 方法1: 从配置文件获取完整Authorization头
            auth_header = self.zhihu_config.get('authorization')
            if auth_header and auth_header.strip() != "" and auth_header.strip() != "Bearer your_token_here":
                headers['Authorization'] = auth_header
            
            # 方法2: 从配置文件获取access_token
            access_token = self.zhihu_config.get('access_token')
            if access_token and access_token.strip() != "" and 'Authorization' not in headers:
                headers['Authorization'] = f'Bearer {access_token}'
            
            # 方法3: 从环境变量获取认证信息
            env_token = os.environ.get('ZHIHU_TOKEN')
            if env_token and env_token.strip() != "" and 'Authorization' not in headers:
                headers['Authorization'] = f'Bearer {env_token}'
            
            # 添加Cookie信息（如果配置了）
            cookie_auth = self.zhihu_config.get('cookie', {}).get('auth')
            if cookie_auth and cookie_auth.strip() != "":
                headers['Cookie'] = cookie_auth
            
            # 发送请求
            # 创建新的session以避免复用问题
            timeout = self.zhihu_config.get('collection', {}).get('timeout', 10)
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # 解析热榜数据
                        hot_list = data.get('data', [])
                        for index, item in enumerate(hot_list, 1):
                            try:
                                target = item.get('target', {})
                                title = target.get('title', '')
                                hot_value = item.get('detail_text', '')
                                answer_count = target.get('answer_count', 0)
                                follower_count = target.get('follower_count', 0)
                                
                                # 解析热度值
                                hot_num = 0
                                if hot_value:
                                    # 处理类似"12.5 万热度"的格式
                                    hot_value = hot_value.replace('热度', '')
                                    if '万' in hot_value:
                                        try:
                                            num = float(hot_value.replace('万', ''))
                                            hot_num = int(num * 10000)
                                        except ValueError:
                                            hot_num = 0
                                    else:
                                        try:
                                            hot_num = int(float(hot_value))
                                        except ValueError:
                                            hot_num = 0
                                
                                # 如果没有热度值，使用回答数和关注数综合计算
                                if hot_num == 0:
                                    hot_num = answer_count * 10 + follower_count
                                
                                # 构造链接
                                question_id = target.get('id', '')
                                url = f"https://www.zhihu.com/question/{question_id}" if question_id else ''
                                
                                # 只有当标题不为空时才添加到结果中
                                if title.strip():
                                    results.append({
                                        "fields": {
                                            "id": generate_content_id(),  # 使用统一的ID生成函数
                                            "title": title.strip(),
                                            "hot": str(hot_num),
                                            "rank": str(index),
                                            "url": url,
                                            "content": target.get('excerpt', ''),
                                            "published_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                            "collected_at": self._get_current_time(),  # 使用统一的时间获取方法
                                            "site_code": self.site_code,  # 添加site_code字段
                                            "platform": "zhihu"
                                        }
                                    })
                                    
                            except Exception as e:
                                print(f"解析知乎热榜单项数据时出错: {e}")
                                continue
                        
                        # 限制返回数量
                        results = results[:self.zhihu_config.get('collection', {}).get('result_limit', 50)]
                        
                        if results:
                            return results
                    else:
                        print(f"知乎API请求失败，状态码: {response.status}")
                            
        except Exception as e:
            print(f"知乎基础HTTP请求采集出错: {e}")
            import traceback
            traceback.print_exc()
        
        return results
    
    async def cleanup(self):
        """清理资源"""
        pass


# 导出类
__all__ = ['ZhihuSite']