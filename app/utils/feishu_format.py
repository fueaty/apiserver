"""飞书格式转换器"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional


class FeishuFormatter:
    """飞书格式转换器"""
    
    @staticmethod
    def format_hotspot_data(hotspot_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化热点数据为飞书格式
        
        Args:
            hotspot_data: 热点数据
            
        Returns:
            飞书格式的热点数据
        """
        try:
            # 构建飞书表格格式
            feishu_data = {
                "fields": {
                    "id": {"text": hotspot_data.get("id", "")},
                    "platform": {"text": hotspot_data.get("platform", "")},
                    "title": {"text": hotspot_data.get("title", "")},
                    "hot": {"text": str(hotspot_data.get("hot", 0))},
                    "rank": {"text": str(hotspot_data.get("rank", 0))},
                    "url": {"text": hotspot_data.get("url", "")},
                    "date": {"text": hotspot_data.get("date", "")},
                    "category": {"text": hotspot_data.get("category", "")},
                    "source": {"text": hotspot_data.get("source", "")}
                }
            }
            
            return feishu_data
            
        except Exception as e:
            raise ValueError(f"格式化热点数据失败: {e}")
    
    @staticmethod
    def format_selection_results(selection_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化选材结果为飞书格式
        
        Args:
            selection_results: 选材结果（新格式：包含selections数组）
            
        Returns:
            飞书格式的选材结果
        """
        try:
            # 构建飞书消息卡片格式
            feishu_data = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True,
                        "enable_forward": True
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "📊 智能选材分析结果"
                        },
                        "template": "blue"
                    },
                    "elements": []
                }
            }
            
            # 处理新的选材结果格式（selections数组）
            selections_list = selection_results.get("selections", [])
            
            # 按平台分组显示结果
            platform_groups = {}
            for selection in selections_list:
                fields = selection.get("fields", {})
                platform = fields.get("platform", "未知平台")
                if platform not in platform_groups:
                    platform_groups[platform] = []
                platform_groups[platform].append(fields)
            
            # 添加平台选材结果
            for platform, selections in platform_groups.items():
                platform_section = {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**📱 {platform.upper()} 平台选材结果**\n"
                    }
                }
                feishu_data["card"]["elements"].append(platform_section)
                
                for selection in selections:
                    selection_text = (
                        f"**标题**: {selection.get('title', '')}\n"
                        f"**匹配度**: {selection.get('suitability_score', 0):.2f}\n"
                        f"**内容角度**: {selection.get('content_angle', '')}\n"
                        f"**推荐策略**: {selection.get('recommended_strategy', '')}\n"
                        f"**推荐理由**: {selection.get('reason', '')}\n"
                    )
                    
                    selection_element = {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": selection_text
                        }
                    }
                    feishu_data["card"]["elements"].append(selection_element)
            
            # 添加分析统计信息
            criteria = selection_results.get("selection_criteria", {})
            stats_text = (
                f"**📈 分析统计**\n"
                f"• 分析热点数: {criteria.get('total_hotspots_analyzed', 0)}\n"
                f"• 分析平台数: {len(criteria.get('platforms_analyzed', []))}\n"
                f"• 分析时间: {criteria.get('selection_timestamp', '')}\n"
                f"• 使用策略: {criteria.get('strategy_used', '')}\n"
            )
            
            stats_element = {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": stats_text
                }
            }
            feishu_data["card"]["elements"].append(stats_element)
            
            return feishu_data
            
        except Exception as e:
            raise ValueError(f"格式化选材结果失败: {e}")
    
    @staticmethod
    def format_content_data(content_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化内容数据为飞书格式
        
        Args:
            content_data: 内容数据
            
        Returns:
            飞书格式的内容数据
        """
        try:
            # 构建飞书文档格式
            feishu_data = {
                "title": content_data.get("title", "内容数据"),
                "content": []
            }
            
            # 添加标题
            if content_data.get("title"):
                feishu_data["content"].append({
                    "tag": "heading",
                    "attrs": {"level": 1},
                    "content": [{"tag": "text", "text": content_data["title"]}]
                })
            
            # 添加元数据
            metadata = content_data.get("metadata", {})
            if metadata:
                meta_text = f"**来源**: {metadata.get('source', '')} | **分类**: {metadata.get('category', '')} | **发布时间**: {metadata.get('publish_time', '')}"
                feishu_data["content"].append({
                    "tag": "paragraph",
                    "content": [{"tag": "text", "text": meta_text}]
                })
            
            # 添加正文内容
            body = content_data.get("body", "")
            if body:
                # 简单的段落分割
                paragraphs = body.split('\n\n')
                for paragraph in paragraphs:
                    if paragraph.strip():
                        feishu_data["content"].append({
                            "tag": "paragraph",
                            "content": [{"tag": "text", "text": paragraph.strip()}]
                        })
            
            # 添加图片（如果有）
            images = content_data.get("images", [])
            for img_url in images:
                feishu_data["content"].append({
                    "tag": "image",
                    "attrs": {"src": img_url}
                })
            
            # 添加标签
            tags = content_data.get("tags", [])
            if tags:
                tag_text = "**标签**: " + ", ".join(tags)
                feishu_data["content"].append({
                    "tag": "paragraph",
                    "content": [{"tag": "text", "text": tag_text}]
                })
            
            return feishu_data
            
        except Exception as e:
            raise ValueError(f"格式化内容数据失败: {e}")
    
    @staticmethod
    def format_publication_results(publish_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化发布结果为飞书格式
        
        Args:
            publish_results: 发布结果
            
        Returns:
            飞书格式的发布结果
        """
        try:
            # 构建飞书通知格式
            feishu_data = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True,
                        "enable_forward": True
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "✅ 内容发布结果"
                        },
                        "template": "green" if publish_results.get("status") == "published" else "red"
                    },
                    "elements": []
                }
            }
            
            # 添加发布基本信息
            info_elements = [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**平台**: {publish_results.get('platform', '')}"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**状态**: {publish_results.get('status', '')}"
                    }
                }
            ]
            
            # 添加发布ID和链接（如果发布成功）
            if publish_results.get("publication_id"):
                info_elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**发布ID**: {publish_results.get('publication_id')}"
                    }
                })
            
            if publish_results.get("url"):
                info_elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**链接**: [查看内容]({publish_results.get('url')})"
                    }
                })
            
            # 添加发布时间
            if publish_results.get("publish_time"):
                info_elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**发布时间**: {publish_results.get('publish_time')}"
                    }
                })
            
            feishu_data["card"]["elements"].extend(info_elements)
            
            # 添加错误信息（如果发布失败）
            if publish_results.get("status") == "failed" and publish_results.get("error"):
                error_element = {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**错误信息**: {publish_results.get('error')}"
                    }
                }
                feishu_data["card"]["elements"].append(error_element)
            
            return feishu_data
            
        except Exception as e:
            raise ValueError(f"格式化发布结果失败: {e}")
    
    @staticmethod
    def format_error_message(error_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化错误信息为飞书格式
        
        Args:
            error_info: 错误信息
            
        Returns:
            飞书格式的错误信息
        """
        try:
            feishu_data = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True,
                        "enable_forward": True
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "❌ 系统错误"
                        },
                        "template": "red"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**错误类型**: {error_info.get('error_type', '未知错误')}"
                            }
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**错误信息**: {error_info.get('message', '')}"
                            }
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**发生时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            }
                        }
                    ]
                }
            }
            
            # 添加堆栈信息（如果提供）
            if error_info.get("stack_trace"):
                feishu_data["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**堆栈信息**: {error_info.get('stack_trace')}"
                    }
                })
            
            return feishu_data
            
        except Exception as e:
            raise ValueError(f"格式化错误信息失败: {e}")
    
    @staticmethod
    def format_batch_results(batch_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        格式化批量结果为飞书格式
        
        Args:
            batch_results: 批量结果列表
            
        Returns:
            飞书格式的批量结果
        """
        try:
            # 统计成功和失败数量
            success_count = sum(1 for result in batch_results if result.get("status") == "success")
            failed_count = len(batch_results) - success_count
            
            feishu_data = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True,
                        "enable_forward": True
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "📊 批量操作结果"
                        },
                        "template": "green" if failed_count == 0 else "yellow"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**总操作数**: {len(batch_results)}"
                            }
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**成功数**: {success_count}"
                            }
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**失败数**: {failed_count}"
                            }
                        }
                    ]
                }
            }
            
            # 添加失败详情（如果有）
            if failed_count > 0:
                failed_details = "**失败详情**:\n"
                for i, result in enumerate(batch_results):
                    if result.get("status") == "failed":
                        failed_details += f"{i+1}. {result.get('error', '未知错误')}\n"
                
                feishu_data["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": failed_details
                    }
                })
            
            return feishu_data
            
        except Exception as e:
            raise ValueError(f"格式化批量结果失败: {e}")