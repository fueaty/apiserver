一、需求分析与功能定义

🎯 核心业务目标

基于智能体工作流平台的调用需求，本接口服务器旨在提供轻量级、高安全性、易维护的原子能力服务，实现"信息采集→智能选材→内容发布"的完整自动化流程闭环。

🔄 业务流程设计

智能体工作流平台交互流程：
扣子平台工作流
    ↓
调用热点采集API(apiserver) → 返回飞书格式数据
    ↓  
扣子飞书插件 → 写入飞书热点库
    ↓
调用智能选材API(apiserver) → 返回平台差异化选材结果
    ↓
调用内容采集API(apiserver) → 返回飞书格式内容数据
    ↓
扣子飞书插件 → 写入飞书内容库
    ↓
扣子插件 → AI生成 → 写入飞书内容库
    ↓
扣子插件 → 调用内容发布API(apiserver)
    ↓
扣子飞书插件 → 写入飞书发布库

触发执行：工作流平台根据定时规则或外部事件触发工作流实例
身份认证：调用身份验证接口获取临时访问凭证（authkey）
信息采集：使用authkey调用网站信息采集接口，获取结构化内容数据
智能选材：调用智能选材API分析内容与平台匹配度，返回差异化选材结果
内容处理：工作流平台对采集内容进行AI润色、格式转换等加工处理
多平台发布：调用内容发布接口，将加工后的内容分发到指定平台
结果处理：根据发布结果进行日志记录、重试或告警处理

📊 性能与资源要求

服务器环境约束：2核2G Rocky Linux服务器

性能指标	目标值	关键设计决策
响应时间	采集接口≤5秒，选材接口≤3秒，发布接口≤8秒	异步非阻塞I/O处理
吞吐量	10-20 QPS稳定运行	无状态服务设计，连接池优化
资源利用率	CPU平均<70%，内存<1.2G	合理缓存策略，日志轮转机制
可用性	99.9%（单机部署）	systemd进程守护，自动重启

🔧 核心功能模块

1. 网站信息采集引擎

功能：实时采集目标网站内容并进行数据清洗
配置驱动：通过YAML文件定义网站编码、URL规则、解析规则（XPath/正则）
ID生成：使用统一的ID生成机制，所有飞书表格记录ID采用时间戳+5位随机字符格式

2. 智能选材引擎

功能：分析内容与平台匹配度，提供差异化选材结果
配置驱动：通过YAML文件定义平台配置、评分规则
数据来源：可从接口输入或从飞书多维表格读取当日采集数据

3. 多平台内容发布器

功能：支持向多个内容平台发布内容
配置驱动：通过YAML文件定义平台参数、发布规则
安全机制：平台认证信息由调用方传递，服务端不存储

4. 身份认证服务

功能：提供接口调用的身份验证机制
实现方式：JWT令牌机制，令牌存储在[/root/apiserver/secret/auth_key.json](file:///root/apiserver/secret/auth_key.json)文件中
安全机制：禁止外部申请令牌，所有令牌必须通过本地脚本生成

5. 飞书集成服务

功能：与飞书多维表格集成，实现数据存储和管理
字段管理：所有字段均为文本类型，确保兼容性
ID生成：使用统一的ID生成函数，确保格式一致性
目录规范：所有飞书相关功能脚本存放于[/root/apiserver/app/services/feishu/function](file:///root/apiserver/app/services/feishu/function)目录下

🔒 安全设计

1. 认证机制
- 使用JWT标准格式令牌
- 令牌有效期一年
- 令牌存储在本地JSON文件中
- 禁止通过API接口申请令牌
- 仅加载状态为"active"的令牌

2. ID生成机制
- 所有飞书表格记录ID采用统一格式：时间戳+5位随机字符
- 使用[/root/apiserver/secret/generate_auth_key.py](file:///root/apiserver/secret/generate_auth_key.py)中的[generate_content_id()](file:///root/apiserver/secret/generate_auth_key.py#L21-L28)函数生成
- 确保ID的全局唯一性和时间有序性

3. 数据安全
- 不存储平台认证信息
- 服务器仅存储密钥和日志
- 所有敏感配置通过加密方式存储

🔄 数据流设计

1. 采集流程
采集请求 → 调用采集脚本 → 获取原始数据 → 数据清洗 → 生成统一ID → 存入飞书表格 → 返回结果

2. 选材流程
选材请求 → 获取数据源（接口或飞书表格） → 执行选材算法 → 生成结果 → 返回或存入飞书表格

3. 发布流程
发布请求 → 获取内容数据 → 调用平台适配器 → 执行发布操作 → 记录发布状态 → 存入飞书表格 → 返回结果

📦 项目架构

采用模块化设计，主要包含以下组件：

1. API层：提供RESTful接口
2. 服务层：实现核心业务逻辑
3. 工具层：提供通用工具函数
4. 配置层：管理项目配置
5. 测试层：提供单元测试和集成测试

所有模块之间通过明确定义的接口进行交互，确保系统的可维护性和可扩展性。

二、系统架构设计

架构设计原则

基于2核2G Rocky Linux服务器的资源约束，本系统采用轻量级无状态架构，核心设计原则包括：

资源优化优先：所有组件设计必须满足CPU<70%、内存<1.2G的硬性指标
异步非阻塞：采用异步I/O模型避免资源阻塞，确保10-20 QPS的稳定并发
配置驱动扩展：通过YAML配置文件实现业务规则热更新，支持快速接入新网站和平台

整体架构分层

1. 接入层（API Gateway）

协议支持：HTTPS（TLS 1.2+）端到端加密传输
认证网关：统一处理JWT临时令牌验证，有效期1-2小时
请求路由：基于FastAPI框架实现异步请求分发
限流保护：内置频率限制，防止恶意请求耗尽资源

2. 业务逻辑层

身份验证服务

基于预置全局密钥生成短期authkey
JWT签名密钥仅服务端持有，内存中临时存储
无状态设计，支持多实例负载均衡

网站信息采集引擎

YAML配置驱动的实时采集规则
支持编码识别、URL解析、XPath/正则提取
严格遵守robots.txt协议，内置请求间隔控制
采集结果实时返回，服务端不落地存储

智能选材引擎

python
class SelectionEngine:
    def __init__(self):
        self.platform_profiles = self._load_platform_profiles()
        self.content_strategies = self._load_content_strategies()
    
    def _load_platform_profiles(self):
        """Load platform user profiles and preferences"""
        return {
            "wechat_public": {
                "target_audience": ["职场人士", "知识型用户", "科技从业者"],
                "content_preferences": ["深度行业报告", "技术趋势分析", "AI工具评测", "互联网政策解读"],
                "content_style": "专业深度, 权威性内容, 结构清晰, 价值导向",
                "optimal_length": "2000-5000字",
                "best_post_times": ["08:00-10:00", "20:00-22:00"],
                "domain_focus": {
                    "primary": "科技",
                    "secondary": "政治",
                    "avoid_domains": ["娱乐八卦", "主观情绪化内容"]
                }
            },
            "zhihu": {
                "target_audience": ["高知人群", "学生群体", "职场人士"],
                "content_preferences": ["科技专业分析", "技术讨论", "实用技巧", "资源盘点"],
                "content_style": "专业分析, 问答形式, 数据驱动",
                "optimal_length": "1000-3000字",
                "best_post_times": ["20:00-23:00", "09:00-11:00"],
                "domain_focus": {
                    "primary": "科技",
                    "secondary": "生活",
                    "avoid_domains": ["未经证实的政治传闻", "极端观点"]
                }
            },
            "xiaohongshu": {
                "target_audience": ["年轻女性", "都市青年", "生活爱好者"],
                "content_preferences": ["视觉化干货", "穿搭攻略", "家居改造", "设计分享"],
                "content_style": "视觉导向, 情感共鸣, 个人故事, 实用性强",
                "optimal_length": "500-1000字",
                "best_post_times": ["19:00-22:00", "12:00-14:00"],
                "domain_focus": {
                    "primary": "生活",
                    "secondary": "科技",
                    "avoid_domains": ["政治", "社会争议话题"]
                }
            },
            "toutiao": {
                "target_audience": ["大众用户", "资讯消费者", "普通网民"],
                "content_preferences": ["实时政策快讯", "社会新闻摘要", "科技热点短讯"],
                "content_style": "简洁明了, 时效性强, 重点突出, 通俗易懂",
                "optimal_length": "500-1500字",
                "best_post_times": ["07:00-09:00", "12:00-14:00", "18:00-20:00"],
                "domain_focus": {
                    "primary": "政治",
                    "secondary": "科技",
                    "avoid_domains": ["专业术语过多的深度分析"]
                }
            }
        }
    
    def analyze_hotspot_suitability(self, hotspot, platform):
        """Analyze how suitable a hotspot is for specific platform"""
        # 计算内容匹配度、受众相关性、时效性和互动潜力
        # 返回综合评分和推荐策略


多平台内容发布器

动态接收平台认证信息（Token/Cookie）
请求结束后立即销毁敏感凭证，不落盘存储
通过配置文件快速扩展新平台适配
内置平台频率限制和内容规范检查

3. 基础设施层

进程管理

systemd守护进程，自动失败重启保障99.9%可用性
单应用部署模式，避免复杂依赖关系

日志系统

按日滚动日志，保留7天历史记录
logrotate自动管理磁盘空间
完整记录：时间、IP、authkey、接口耗时、错误堆栈

监控保障

健康检查端点：GET /health 返回服务状态
系统资源监控：CPU、内存、磁盘、网络使用情况
性能指标实时采集：接口响应时间、并发数、错误率

数据流架构

plaintext
智能体工作流平台 → HTTPS请求 → 认证网关 → 业务处理 → 实时响应


认证阶段：工作流平台通过 /auth 接口获取临时authkey
采集阶段：携带authkey调用 /collect ，服务端实时抓取并清洗数据
选材阶段：调用 /select 接口获取平台差异化选材结果
发布阶段：动态传入平台凭证调用 /publish ，完成多平台内容分发
结果处理：工作流平台负责重试、告警等后续流程，服务端无状态

三、RESTful API接口设计

🔐 认证机制设计

采用JWT令牌认证机制，但不提供外部接口申请令牌。所有API访问令牌必须通过本地脚本生成，并存储在预设文件中。

令牌生成与管理：
1. 使用本地脚本 `/root/apiserver/secret/generate_auth_key.py` 生成JWT令牌
2. 生成的令牌自动记录在 `/root/apiserver/secret/auth_key.json` 文件中
3. 服务端启动时加载该文件中的有效认证令牌
4. 客户端从该文件获取有效的JWT令牌用于API访问

使用令牌：所有业务接口需在Header携带

plaintext
Authorization: Bearer <authkey>


📊 核心业务接口规范

1. 网站信息采集接口

端点： GET /api/v1/collection

参数设计

参数	类型	必填	说明	示例
date	string	否	采集日期(YYYY-MM-DD)	2025-10-28
site_code	string	否	网站编码(逗号分隔)	weibo,baidu
category	string	否	分类筛选(配置驱动)	technology
keyword	string	否	关键词筛选(配置驱动)	AI

响应结构（飞书兼容格式）

json
{
  "code": 200,
  "message": "数据采集成功",
  "data": [
    {
      "site_code": "baidu",
      "collect_time": "2025-10-29 11:00:00",
      "data_count": 1,
      "news": [
        {
          "fields": {
            "hotspot_id": "baidu_20251029105040eLYQ9_2025-10-29_10_50_40",
            "title": "“十五五”规划建议发布",
            "source": "baidu",
            "platform": "baidu",
            "hot_value": 7904676,
            "hot_level": "爆款",
            "rank": 1,
            "url": "https://www.baidu.com/s?wd=%E2%80%9C%E5%8D%81%E4%BA%94%E4%BA%94%E2%80%9D%E8%A7%84%E5%88%92%E5%BB%BA%E8%AE%AE%E5%8F%91%E5%B8%83",
            "publish_time": "2025-10-29 10:50:40",
            "category": "政治",
            "keywords": ["十五五", "规划", "建议", "发布"],
            "collect_time": "2025-10-29 11:00:00",
            "summary": "爆款内容，排名第1位：“十五五”规划建议发布",
            "content_quality": {
              "score": 8.5,
              "level": "优质",
              "factors": ["标题长度：12字符", "热度值：7904676", "内容完整性：待分析"]
            }
          }
        }
      ]
    }
  ]
}


2. 智能选材接口

端点： POST /api/v1/selection

请求体

json
{
  "hotspots": [
    {
      "hotspot_id": "hotspot_001",
      "title": "今日热门旅游目的地趋势",
      "source": "微博",
      "hot_value": 850000,
      "category": "社会",
      "collect_time": "2024-01-15 10:30:00",
      "summary": "热门话题摘要内容..."
    }
  ],
  "platforms": ["xiaohongshu", "zhihu", "wechat_public"]
}


响应结构（飞书兼容格式）

json
{
  "code": 200,
  "message": "智能选材成功",
  "selections": [
    {
      "fields": {
        "platform": "xiaohongshu",
        "hotspot_id": "hotspot_001",
        "title": "热门旅游目的地趋势分析",
        "source": "baidu",
        "hot_level": "热门",
        "rank": 1,
        "suitability_score": 0.85,
        "content_angle": "个人旅行体验分享：热门目的地的实用技巧",
        "recommended_strategy": "情感共鸣策略",
        "reason": "内容视觉吸引力强，符合年轻女性用户兴趣偏好，匹配度很高",
        "detailed_scores": {
          "content_match": 0.9,
          "audience_relevance": 0.8,
          "timeliness": 0.7,
          "engagement_potential": 0.6
        },
        "platform_insights": {
          "target_audience": ["年轻女性", "都市青年"],
          "content_preferences": ["生活方式", "美妆", "旅行", "美食"],
          "optimal_post_time": "19:00-22:00"
        },
        "content_quality": {
          "score": 8.5,
          "level": "优质",
          "factors": ["标题长度：12字符", "热度值：850000", "内容完整性：待分析"]
        },
        "keywords_analysis": {
          "matched_keywords": ["旅游", "目的地"],
          "relevance_score": 0.8
        }
      }
    }
  ]
}


3. 多平台内容发布接口

端点： POST /api/v1/publication

请求体规范

json
{
  "platform": "zhihu",
  "platform_credentials": {
    "access_token": "动态传入的平台Token",
    "refresh_token": "刷新令牌(可选)"
  },
  "content": {
    "title": "发布标题",
    "body": "发布正文(支持HTML/Markdown)",
    "images": ["https://example.com/image1.jpg"],
    "tags": ["标签1", "标签2"],
    "category": "科技",
    "schedule_time": "2025-10-28 15:30:00"
  }
}


发布结果响应

json
{
  "code": 200,
  "message": "success",
  "data": {
    "platform": "zhihu",
    "publication_id": "123456789",
    "url": "https://zhihu.com/p/123456789",
    "status": "published"
  }
}


4. 增强版采集接口

为满足直接采集并入库以及选材并入库的需求，新增了增强版采集接口：

(1) 采集并存储接口

端点： GET /api/v1/enhanced-collection/collect-and-store

功能：采集指定网站的信息并直接存储到飞书多维表格

参数设计

参数	类型	必填	说明	示例
date	string	否	采集日期(YYYY-MM-DD)	2025-10-28
site_code	string	否	网站编码(逗号分隔)	weibo,baidu
category	string	否	分类筛选(配置驱动)	technology
keyword	string	否	关键词筛选(配置驱动)	AI

响应结构

json
{
  "code": 200,
  "message": "采集并存储成功",
  "data": {
    "collection_results": [
      // 采集结果数据
    ],
    "stored_records": 50
  }
}


(2) 选材并存储接口

端点： POST /api/v1/enhanced-collection/select-and-store

功能：从热点库提取数据进行选材分析，并将选材结果存储到飞书多维表格

请求体

json
{
  "platforms": ["xiaohongshu", "zhihu", "wechat_public"]
}


响应结构

json
{
  "code": 200,
  "message": "选材并存储成功",
  "data": {
    "selections": [
      // 选材结果数据
    ],
    "stored_records": 25
  }
}


四、智能选材引擎扩展设计

4.1 平台规则扩展机制

为支持新平台接入时快速配置选材规则，系统采用配置驱动的扩展设计：

平台配置文件结构（config/platforms.yaml）：

yaml
publish_platforms:
  xiaohongshu:
    name: "小红书"
    api_endpoint: "https://edith.xiaohongshu.com/api"
    content_format: "markdown"
    max_images: 9
    supported_categories: ["美妆", "旅行", "美食", "生活方式"]
    # 选材规则配置
    selection_rules:
      target_audience: ["年轻女性", "都市青年"]
      content_preferences: ["生活方式", "美妆", "旅行", "美食"]
      content_style: "视觉导向, 情感共鸣, 个人故事"
      optimal_length: "500-1000字"
      best_post_times: ["19:00-22:00", "12:00-14:00"]
      scoring_weights:
        content_match: 0.4
        audience_relevance: 0.3
        timeliness: 0.2
        engagement_potential: 0.1

  # 新增平台只需添加配置
  new_platform:
    name: "新平台名称"
    # ...其他配置


热加载机制：

python
class ConfigManager:
    def __init__(self):
        self._platform_configs = {}
        self._last_modified = 0
        self._config_path = "config/platforms.yaml"
        
    def get_platform_config(self, platform):
        """获取平台配置，支持热加载"""
        current_mtime = os.path.getmtime(self._config_path)
        
        # 检测配置文件是否更新
        if current_mtime > self._last_modified:
            self._reload_configs()
            self._last_modified = current_mtime
            
        return self._platform_configs.get(platform)
        
    def _reload_configs(self):
        """重新加载配置文件"""
        with open(self._config_path, 'r', encoding='utf-8') as f:
            self._platform_configs = yaml.safe_load(f)['publish_platforms']


4.2 新增平台接入流程

配置新增：在platforms.yaml中添加新平台的完整配置
规则验证：系统自动加载配置并验证完整性
测试验证：通过测试接口验证新平台的选材逻辑
正式启用：无需重启服务，配置自动生效

4.3 选材算法优化

系统采用加权评分模型计算内容与平台的匹配度：

python
def calculate_suitability_score(hotspot, platform_config):
    """计算内容与平台的匹配度得分"""
    # 1. 内容类型匹配度 (0-1)
    content_match = calculate_content_match(hotspot, platform_config)
    
    # 2. 受众相关性 (0-1)
    audience_score = calculate_audience_relevance(hotspot, platform_config)
    
    # 3. 时效性因子 (0-1)
    timeliness_score = calculate_timeliness(hotspot)
    
    # 4. 互动潜力 (0-1)
    engagement_score = calculate_engagement_potential(hotspot, platform_config)
    
    # 加权计算总分
    weights = platform_config.get('scoring_weights', {
        'content_match': 0.4,
        'audience_relevance': 0.3,
        'timeliness': 0.2,
        'engagement_potential': 0.1
    })
    
    total_score = (
        content_match * weights['content_match'] +
        audience_score * weights['audience_relevance'] +
        timeliness_score * weights['timeliness'] +
        engagement_score * weights['engagement_potential']
    )
    
    return round(total_score, 2)


五、后端实现方案

5.1 技术栈选型

核心技术组合：

Web框架：FastAPI（异步支持优秀，自动生成API文档）
异步运行时：Uvicorn（ASGI服务器，专为异步应用优化）
配置管理：YAML文件 + 内存缓存（零数据库依赖）
数据解析：BeautifulSoup（HTML解析）、PyYAML（配置解析）

5.2 智能选材服务实现

python
# app/services/selection/engine.py
class SelectionEngine:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.platform_profiles = {}
        self.content_strategies = {}
        self._load_configs()
        
    def _load_configs(self):
        """加载平台配置和内容策略"""
        platforms_config = self.config_manager.get_platform_configs()
        for platform, config in platforms_config.items():
            self.platform_profiles[platform] = config.get('selection_rules', {})
            
        # 加载内容策略
        self.content_strategies = {
            "emotional_appeal": {
                "applicable_platforms": ["xiaohongshu", "douyin"],
                "content_elements": ["个人故事", "情感触发", "视觉隐喻"],
                "strategy_name": "情感共鸣策略"
            },
            "knowledge_sharing": {
                "applicable_platforms": ["zhihu", "wechat_public"],
                "content_elements": ["数据支撑", "专家观点", "结构化分析"],
                "strategy_name": "知识分享策略"
            },
            # 其他策略...
        }
        
    async def analyze_hotspots(self, hotspots, platforms=None):
        """分析多个热点在指定平台的适用性"""
        if not platforms:
            platforms = list(self.platform_profiles.keys())
            
        results = {"selections": {}, "selection_criteria": {}}
        
        for platform in platforms:
            platform_results = []
            for hotspot in hotspots:
                suitability = self.analyze_hotspot_suitability(hotspot, platform)
                if suitability["total_score"] >= 0.6:  # 阈值过滤
                    platform_results.append(suitability)
                    
            if platform_results:
                results["selections"][platform] = platform_results
                
        # 添加选择标准元数据
        results["selection_criteria"] = {
            "strategy_used": "platform_optimized",
            "total_hotspots_analyzed": len(hotspots),
            "selection_timestamp": datetime.now().isoformat()
        }
        
        return results


5.3 扩展性设计

系统采用插件化设计，支持功能模块的灵活扩展：

平台解析插件：每个平台的内容解析逻辑封装为独立插件
策略插件：不同的选材策略实现为可插拔模块
过滤插件：内容过滤和清洗规则可通过插件扩展

python
# 插件接口定义
class BasePlugin(ABC):
    @abstractmethod
    async def process(self, data, context):
        pass

# 插件管理器
class PluginManager:
    def __init__(self):
        self.plugins = {
            "pre_selection": [],
            "post_selection": [],
            "content_processing": []
        }
        
    def register_plugin(self, plugin_type, plugin):
        """注册插件"""
        if plugin_type in self.plugins:
            self.plugins[plugin_type].append(plugin)
            
    async def apply_plugins(self, plugin_type, data, context=None):
        """应用指定类型的所有插件"""
        context = context or {}
        for plugin in self.plugins[plugin_type]:
            data = await plugin.process(data, context)
        return data


这种设计确保新增功能或平台时，无需修改核心代码，只需添加相应的配置和插件即可。

七、热点特征分析模块设计

7.1 模块概述

热点特征分析模块是系统新增的核心功能，旨在通过大模型处理能力从飞书表格中的热点数据提取关键特征，为内容分析和决策提供支持。该模块具有以下特点：

- 从飞书多维表格"AI Headlines Pipeline"中获取热点数据
- 利用大模型技术对热点URL和内容进行深度特征提取
- 支持自动化分类、实体识别、情感分析等高级功能
- 结果可存储回飞书表格或系统数据库

7.2 飞书数据源配置

模块接入指定的飞书多维表格作为热点数据来源：

```python
# 飞书表格配置
FEISHU_CONFIG = {
    "app_name": "AI Headlines Pipeline",
    "app_token": "EhSmbB0x0aujxXsNgPncjIyLntc",
    "table_id": "tblOkYEu3bc87Tuo"
}
```

7.3 核心功能架构

7.3.1 模块组件设计

![模块架构图](模块架构示意图)

核心组件包括：

- **FeishuDataLoader**: 负责从飞书表格加载热点数据
- **LLMProcessor**: 封装大模型交互逻辑，处理特征提取任务
- **FeatureAnalyzer**: 整合数据加载和特征分析功能
- **HotspotClassifier**: 实现热点分类模型
- **AnalysisStorage**: 管理分析结果的存储

7.3.2 数据流程

1. **数据加载阶段**: 通过FeishuDataLoader从飞书表格获取热点数据
2. **特征提取阶段**: 利用LLMProcessor对热点内容进行深度分析
3. **分类处理阶段**: 使用HotspotClassifier进行热点分类
4. **结果存储阶段**: 通过AnalysisStorage保存分析结果

7.4 核心类实现

7.4.1 FeishuDataLoader

```python
# app/services/analysis/feature_analysis/feishu_data_loader.py
class FeishuDataLoader:
    """
    飞书数据加载器，负责从飞书表格获取热点数据
    """
    
    def __init__(self, app_token, table_id):
        """初始化飞书数据加载器"""
        self.app_token = app_token
        self.table_id = table_id
        # 初始化飞书客户端（复用现有的FeishuService）
        
    async def get_all_records(self, page_size=100):
        """获取表格中所有记录"""
        # 实现分页获取所有记录的逻辑
    
    async def get_records_by_date(self, date, page_size=100):
        """获取指定日期的记录"""
        # 按日期过滤并获取记录
    
    async def get_records_by_date_range(self, start_date, end_date, page_size=100):
        """获取指定日期范围的记录"""
        # 按日期范围过滤并获取记录
```

7.4.2 LLMProcessor

```python
# app/services/analysis/feature_analysis/llm_processor.py
class LLMProcessor:
    """
    大模型处理器，封装大模型交互逻辑
    """
    
    def __init__(self, model_name="gpt-4", timeout=30):
        """初始化大模型处理器"""
        self.model_name = model_name
        self.timeout = timeout
        # 初始化大模型客户端
    
    async def analyze_hotspot(self, hotspot_data):
        """分析单个热点的特征"""
        # 准备提示词
        # 调用大模型API
        # 解析结果
        # 返回结构化特征
    
    async def batch_analyze_hotspots(self, hotspots, batch_size=5):
        """批量分析多个热点"""
        # 实现批量分析逻辑，控制并发
    
    def prepare_prompt(self, hotspot_data):
        """准备大模型提示词"""
        # 构建有效的提示词
    
    def extract_entities(self, content):
        """从内容中提取实体"""
        # 实体提取逻辑
    
    def analyze_title_attraction(self, title):
        """分析标题吸引力"""
        # 标题吸引力分析逻辑
```

7.4.3 FeatureAnalyzer

```python
# app/services/analysis/feature_analysis/feature_analyzer.py
class FeatureAnalyzer:
    """
    特征分析器，整合数据加载和特征分析功能
    """
    
    def __init__(self, app_token, table_id, model_name="gpt-4"):
        """初始化特征分析器"""
        self.data_loader = FeishuDataLoader(app_token, table_id)
        self.llm_processor = LLMProcessor(model_name)
    
    async def analyze_top_hotspots(self, top_n=10, date=None):
        """分析指定数量的热门热点"""
        # 获取热点数据
        # 提取内容
        # 大模型分析
        # 返回结果
    
    async def analyze_hotspot_by_id(self, hotspot_id):
        """根据ID分析特定热点"""
        # 获取指定热点
        # 分析特征
        # 返回结果
    
    async def save_analysis_results(self, results, output_format="feishu"):
        """保存分析结果"""
        # 根据格式保存结果
```

7.4.4 HotspotClassifier

```python
# app/services/analysis/classification/hotspot_classifier.py
class HotspotClassifier:
    """
    热点分类器，实现热点分类模型
    """
    
    def __init__(self):
        """初始化分类器，加载分类体系和规则"""
        self.classification_rules = {}
        # 初始化分类规则和体系
    
    def classify_hotspot(self, hotspot_data, features):
        """对单个热点进行分类"""
        # 应用分类规则
        # 使用大模型增强分类
        # 返回分类结果和置信度
    
    def batch_classify(self, hotspots, features_list):
        """批量分类多个热点"""
        # 批量处理分类
    
    def validate_classification(self, classification_result):
        """验证分类结果"""
        # 验证分类的合理性
    
    def optimize_classification(self, classification_result):
        """优化分类结果"""
        # 根据规则和历史数据优化分类
```

7.4.5 AnalysisStorage

```python
# app/services/analysis/storage/analysis_storage.py
class AnalysisStorage:
    """
    分析结果存储管理器
    """
    
    def __init__(self):
        """初始化存储管理器"""
        # 初始化数据库会话等
    
    async def save_analysis_result(self, hotspot_id, features, classification):
        """保存单个分析结果"""
        # 保存特征和分类结果
    
    async def batch_save_results(self, results):
        """批量保存分析结果"""
        # 批量处理保存
    
    async def get_analysis_history(self, filters=None):
        """获取分析历史"""
        # 查询历史分析结果
```

7.5 API接口设计

7.5.1 热点分析接口

端点：POST /api/v1/analysis/hotspot

请求体：
```json
{
  "hotspot_id": "baidu_20251029105040eLYQ9_2025-10-29_10_50_40"
}
```

响应：
```json
{
  "code": 200,
  "message": "分析成功",
  "data": {
    "hotspot_id": "baidu_20251029105040eLYQ9_2025-10-29_10_50_40",
    "title": "示例热点标题",
    "features": {
      "entities": ["实体1", "实体2"],
      "keywords": ["关键词1", "关键词2"],
      "sentiment": "positive",
      "urgency_level": "high",
      "title_attraction": 0.95,
      "potential_impact": "广泛"
    },
    "classification": {
      "primary_category": "科技",
      "secondary_category": "人工智能",
      "confidence": 0.92
    },
    "analysis_time": "2025-10-29T12:30:45"
  }
}
```

7.5.2 批量分析接口

端点：POST /api/v1/analysis/batch-hotspots

请求体：
```json
{
  "date": "2025-10-29",
  "top_n": 10
}
```

响应：
```json
{
  "code": 200,
  "message": "批量分析成功",
  "data": {
    "total_analyzed": 10,
    "results": [
      {
        "hotspot_id": "...",
        "title": "...",
        "features": {...},
        "classification": {...}
      }
      // 更多结果
    ],
    "analysis_time": "2025-10-29T12:30:45"
  }
}
```

7.6 性能优化与扩展

7.6.1 并发控制

- 大模型请求采用异步并发处理
- 实现请求限流，避免API过载
- 批量处理逻辑优化，提高吞吐量

7.6.2 缓存策略

- 缓存大模型分析结果，避免重复分析
- 实现热点数据的本地缓存
- 支持缓存过期和刷新机制

7.6.3 扩展设计

- 支持多种大模型后端的切换
- 模块化设计，便于新增分析功能
- 配置驱动的分类规则，便于业务扩展

六、部署规划与运维策略

6.1 部署架构设计

6.1.1 服务器环境要求

操作系统：Rocky Linux 8.5+
硬件配置：2核CPU，2GB内存，20GB SSD存储
网络要求：开放443端口（HTTPS），支持 outbound 访问目标网站和内容平台API

6.1.2 部署架构图

plaintext
┌─────────────────────────────────────────┐
│             服务器 (2核2G)               │
├─────────────┬──────────────┬────────────┤
│ Nginx (反向代理) │ Uvicorn (ASGI) │ 应用服务     │
│ - SSL终结    │ - 4工作进程   │ - FastAPI应用 │
│ - 静态资源    │ - 异步I/O     │ - 配置文件    │
└─────────────┴──────────────┴────────────┘


6.1.3 部署流程

环境准备

bash
# 安装依赖
yum install -y python3.9 python3.9-devel gcc nginx
pip3.9 install -r requirements.txt

# 配置防火墙
firewall-cmd --add-port=443/tcp --permanent
firewall-cmd --reload


应用部署

bash
# 创建应用目录
mkdir -p /opt/agent-api/{app,config,logs}
chown -R nginx:nginx /opt/agent-api

# 配置systemd服务
cat > /etc/systemd/system/agent-api.service << EOF
[Unit]
Description=Agent API Service
After=network.target

[Service]
User=nginx
Group=nginx
WorkingDirectory=/opt/agent-api
ExecStart=/usr/local/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
systemctl daemon-reload
systemctl enable --now agent-api


Nginx配置

nginx
server {
    listen 443 ssl;
    server_name api.agent-platform.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    # SSL配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    # 健康检查端点
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}


6.2 配置管理策略

6.2.1 配置文件结构

plaintext
/opt/agent-api/config/
├── main.yaml         # 主配置文件
├── sites.yaml        # 网站采集配置
├── platforms.yaml    # 平台发布配置
└── credentials.yaml  # 加密的密钥配置


6.2.2 配置加密与解密

python
# 配置文件加密工具
from cryptography.fernet import Fernet

def encrypt_config(config_path, key_path):
    """加密配置文件"""
    key = Fernet.generate_key()
    with open(key_path, 'wb') as f:
        f.write(key)
        
    cipher = Fernet(key)
    with open(config_path, 'rb') as f:
        data = f.read()
        
    encrypted_data = cipher.encrypt(data)
    with open(config_path, 'wb') as f:
        f.write(encrypted_data)

# 使用示例
# encrypt_config("credentials.yaml", "secret.key")


6.2.3 配置热加载

python
# app/core/config.py
class ConfigManager:
    def __init__(self):
        self.config_files = {
            "main": "config/main.yaml",
            "sites": "config/sites.yaml",
            "platforms": "config/platforms.yaml"
        }
        self.config_cache = {}
        self.last_modified = {}
        self._load_all_configs()
        self._start_watcher()
        
    def _start_watcher(self):
        """启动配置文件监控线程"""
        def watch_config():
            while True:
                for name, path in self.config_files.items():
                    current_mtime = os.path.getmtime(path)
                    if current_mtime > self.last_modified.get(name, 0):
                        self._load_config(name)
                        self.last_modified[name] = current_mtime
                time.sleep(10)
                
        threading.Thread(target=watch_config, daemon=True).start()


6.3 监控与告警机制

6.3.1 健康检查接口

python
# app/api/health.py
@router.get("/health", tags=["system"])
async def health_check():
    """系统健康检查接口"""
    # 检查配置加载状态
    config_status = "ok" if config_manager.config_loaded else "error"
    
    # 检查服务资源使用
    memory_usage = psutil.virtual_memory().percent
    cpu_usage = psutil.cpu_percent(interval=1)
    
    # 检查关键依赖
    dependencies = {
        "uvicorn": "ok",
        "redis": "ok" if await check_redis() else "error"
    }
    
    status = "ok" if all(v == "ok" for v in dependencies.values()) and config_status == "ok" else "degraded"
    
    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "version": "1.2.0",
        "components": {
            "config": config_status,
            "dependencies": dependencies,
            "resources": {
                "cpu_usage_percent": cpu_usage,
                "memory_usage_percent": memory_usage
            }
        }
    }


6.3.2 日志管理策略

python
# app/core/logging.py
def setup_logging():
    """配置日志系统"""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # 按日轮转日志
    log_filename = os.path.join(log_dir, "agent-api.log")
    file_handler = RotatingFileHandler(
        log_filename, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=7,          # 保留7天日志
        encoding="utf-8"
    )
    
    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    
    # 配置根日志
    logger = logging.getLogger()
    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    
    return logger


6.3.3 告警触发条件

服务不可用：连续3次健康检查失败
资源告警：CPU使用率>85%或内存使用率>80%持续5分钟
接口错误率：5分钟内错误率>5%
采集失败率：单站点采集失败率>30%

6.4 备份与恢复策略

6.4.1 配置文件备份

bash
# 创建备份脚本
cat > /opt/agent-api/backup-config.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/agent-api/backup"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# 备份配置文件
tar -czf $BACKUP_DIR/config_$TIMESTAMP.tar.gz /opt/agent-api/config

# 删除7天前的备份
find $BACKUP_DIR -name "config_*.tar.gz" -mtime +7 -delete
EOF

# 添加定时任务
crontab -l | { cat; echo "0 1 * * * /bin/bash /opt/agent-api/backup-config.sh"; } | crontab -


6.4.2 故障恢复流程

配置恢复

bash
# 列出可用备份
ls -l /opt/agent-api/backup/config_*.tar.gz

# 恢复最近备份
tar -xzf /opt/agent-api/backup/config_20251028_010000.tar.gz -C /
systemctl restart agent-api


服务恢复

bash
# 检查服务状态
systemctl status agent-api

# 查看错误日志
journalctl -u agent-api -n 100 --no-pager

# 一键恢复
systemctl stop agent-api
rm -rf /opt/agent-api/app/__pycache__
systemctl start agent-api


6.5 性能优化策略

6.5.1 资源优化配置

Uvicorn工作进程数：设置为CPU核心数（2核服务器配置2个工作进程）
连接池配置：

python
# 配置HTTP连接池
HTTP_CLIENT = aiohttp.ClientSession(
    connector=aiohttp.TCPConnector(
        limit=100,  # 最大并发连接数
        ttl_dns_cache=300  # DNS缓存时间(秒)
    ),
    timeout=aiohttp.ClientTimeout(total=10)
)


6.5.2 缓存策略

配置缓存：内存缓存所有配置数据
DNS缓存：启用TCPConnector的DNS缓存（300秒）
热点数据缓存：

python
# 热点网站配置缓存
@lru_cache(maxsize=32)
def get_site_config(site_code):
    return config_manager.get_config("sites", site_code)


6.6 安全加固措施

6.6.1 密钥管理

所有密钥通过环境变量注入
敏感配置使用AES加密存储
定期轮换密钥（90天）

6.6.2 请求安全

启用HTTPS，禁用TLS 1.0/1.1
配置API请求限流

python
# 请求限流配置
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379/0"
)

# 应用限流
@app.get("/api/v1/collection")
@limiter.limit("60/minute")  # 每分钟最多60次请求
async def collection_endpoint(...):
    pass


6.7 版本更新流程

6.7.1 平滑更新步骤

准备新版本

bash
# 下载新版本代码
cd /opt/agent-api
git pull origin main

# 安装依赖
pip3.9 install -r requirements.txt --upgrade


应用更新

bash
# 使用滚动更新避免服务中断
systemctl start agent-api-new  # 启动新版本
sleep 10  # 等待新版本初始化
systemctl stop agent-api-old   # 停止旧版本


版本回滚

bash
# 如果发现新版本问题，回滚到上一版本
git checkout <previous-commit-hash>
pip3.9 install -r requirements.txt
systemctl restart agent-api


6.7.2 版本控制规范

采用语义化版本（Semantic Versioning）：MAJOR.MINOR.PATCH
每次更新记录CHANGELOG.md
关键更新前进行完整测试
