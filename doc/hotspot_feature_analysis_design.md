# 热点特征分析模块设计方案

## 1. 模块概述

热点特征分析模块旨在通过访问飞书表格中的热点库数据，提取排名前十的热点URL对应的文章内容，利用大模型分析其特征，并按照科技、生活、时政等类别进行分类入库，为内容创作和选材提供数据支持。

## 2. 系统架构

### 2.1 模块定位

该模块将作为现有`app/services/analysis/`目录下的扩展功能，与采集引擎(collection)和选材引擎(selection)协同工作，同时与飞书多维表格集成获取热点数据源，并使用大模型进行特征分析。

### 2.2 文件结构

```
app/services/analysis/
├── __init__.py
├── analysis_service.py        # 现有发布效果分析服务
├── feature_analysis/          # 新增：热点特征分析子模块
│   ├── __init__.py
│   ├── analyzer.py            # 特征分析器核心类
│   ├── classifier.py          # 热点分类器
│   ├── extractor.py           # URL内容提取器
│   ├── storage.py             # 结果存储管理
│   ├── feishu_data_loader.py  # 飞书表格数据加载器
│   ├── llm_processor.py       # 大模型处理器
│   └── utils/                 # 工具函数
│       ├── __init__.py
│       ├── text_processor.py  # 文本处理工具
│       └── category_rules.py  # 分类规则定义
└── tasks/                     # 新增：分析任务相关
    ├── __init__.py
    └── feature_analysis_tasks.py  # 特征分析任务定义
```

### 2.3 核心组件

| 组件名称 | 职责 | 文件位置 |
|---------|------|--------|
| FeatureAnalyzer | 特征分析主控制器 | app/services/analysis/feature_analysis/analyzer.py |
| ContentExtractor | 从URL提取文章内容 | app/services/analysis/feature_analysis/extractor.py |
| HotspotClassifier | 热点分类器 | app/services/analysis/feature_analysis/classifier.py |
| AnalysisStorage | 分析结果存储管理 | app/services/analysis/feature_analysis/storage.py |
| FeishuDataLoader | 飞书表格数据加载器 | app/services/analysis/feature_analysis/feishu_data_loader.py |
| LLMProcessor | 大模型特征分析处理器 | app/services/analysis/feature_analysis/llm_processor.py |
| TextProcessor | 文本处理工具 | app/services/analysis/feature_analysis/utils/text_processor.py |
| CategoryRules | 分类规则定义 | app/services/analysis/feature_analysis/utils/category_rules.py |

## 3. 核心功能设计

### 3.1 热点URL提取

- 从飞书多维表格中读取热点数据（使用app_token和table_id）
- 根据表格中的排名字段筛选排名前十的热点
- 提取这些热点的URL和基本信息（标题、热度、来源、发布时间等）
- 支持按日期范围筛选热点数据

### 3.2 文章内容提取

- 访问热点URL并提取文章正文内容
- 处理不同网站的内容结构差异
- 提取标题、正文、发布时间、作者等元数据
- 处理可能的访问限制和反爬机制

### 3.3 大模型特征分析

- **文本特征提取**：
  - 通过大模型提取关键词、主题
  - 利用大模型进行情感分析和内容摘要
  - 识别实体和关键事件

- **结构特征分析**：
  - 使用大模型分析标题吸引力要素
  - 分析内容结构特点和叙事风格

- **传播潜力评估**：
  - 基于大模型预测内容传播潜力
  - 分析热点话题关联度

### 3.4 热点分类

- **分类体系**：
  - 科技类：科技新闻、产品发布、技术趋势等
  - 生活类：健康、美食、旅行、时尚等
  - 时政类：政治新闻、政策解读、国际事件等
  - 娱乐类：影视、音乐、明星、综艺节目等
  - 财经类：股市、经济政策、企业动态等
  - 体育类：赛事、运动员、体育产业等

- **分类方法**：
  - 基于大模型的文本分类
  - 结合规则的分类结果优化
  - 多级分类体系支持（主分类、子分类）

### 3.5 结果存储

- 将分析结果以结构化格式存储
- 支持JSON文件存储和数据库存储两种模式
- 提供数据查询和统计功能

## 4. 详细类设计

### 4.1 FeatureAnalyzer类

```python
class FeatureAnalyzer:
    """热点特征分析器主类"""
    
    def __init__(self):
        self.feishu_loader = FeishuDataLoader()
        self.extractor = ContentExtractor()
        self.llm_processor = LLMProcessor()
        self.classifier = HotspotClassifier()
        self.storage = AnalysisStorage()
    
    async def analyze_top_hotspots(self, date: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        分析指定日期的top热点
        
        Args:
            date: 日期字符串，格式YYYY-MM-DD，默认为当天
            limit: 分析的热点数量，默认10
            
        Returns:
            分析结果列表
        """
        # 1. 从飞书表格获取top热点数据
        # 2. 提取文章内容
        # 3. 使用大模型分析特征
        # 4. 进行分类
        # 5. 存储结果
        # 6. 返回分析结果
        pass
    
    async def analyze_single_hotspot(self, hotspot_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析单个热点"""
        pass
    
    def get_analysis_summary(self, category: str = None) -> Dict[str, Any]:
        """获取分析摘要"""
        pass
```

### 4.2 ContentExtractor类

```python
class ContentExtractor:
    """URL内容提取器"""
    
    def __init__(self):
        # 初始化HTTP客户端
        # 配置请求头、代理等
        pass
    
    async def extract_content(self, url: str, site_code: str = None) -> Dict[str, Any]:
        """
        从URL提取文章内容
        
        Args:
            url: 文章URL
            site_code: 站点代码，用于选择特定的提取策略
            
        Returns:
            包含文章内容和元数据的字典
        """
        pass
    
    def _extract_by_site(self, html: str, site_code: str) -> Dict[str, Any]:
        """根据站点代码选择特定的提取策略"""
        pass
    
    def _extract_generic(self, html: str) -> Dict[str, Any]:
        """通用内容提取方法"""
        pass
```

### 4.3 HotspotClassifier类

```python
class HotspotClassifier:
    """热点分类器"""
    
    def __init__(self):
        self.rules = CategoryRules()
        # 可选择加载ML模型
    
    def classify(self, content: str, title: str = None) -> Dict[str, Any]:
        """
        对内容进行分类
        
        Args:
            content: 文章内容
            title: 文章标题
            
        Returns:
            分类结果，包含主分类、置信度等
        """
        pass
    
    def _rule_based_classify(self, text: str) -> Dict[str, Any]:
        """基于规则的分类"""
        pass
    
    def _ml_based_classify(self, text: str) -> Dict[str, Any]:
        """基于机器学习的分类"""
        pass
    
    def get_category_details(self, category: str) -> Dict[str, Any]:
        """获取分类详情"""
        pass
```

### 4.4 FeishuDataLoader类

```python
class FeishuDataLoader:
    """飞书表格数据加载器"""
    
    def __init__(self):
        # 从配置中读取飞书表格信息
        self.app_token = "EhSmbB0x0aujxXsNgPncjIyLntc"  # AI Headlines Pipeline
        self.table_id = "tblOkYEu3bc87Tuo"
        self.feishu_client = self._init_feishu_client()
    
    def _init_feishu_client(self):
        """初始化飞书客户端"""
        # 从app/services/feishu/目录下复用现有飞书客户端
        # 或者创建新的客户端实例
        pass
    
    async def get_top_hotspots(self, date: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        从飞书表格获取排名靠前的热点数据
        
        Args:
            date: 日期过滤，格式YYYY-MM-DD
            limit: 返回的热点数量限制
            
        Returns:
            热点数据列表
        """
        # 1. 构建查询条件
        # 2. 调用飞书API查询数据
        # 3. 按排名排序并限制数量
        # 4. 返回处理后的数据
        pass
    
    def get_hotspots_by_date_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """获取日期范围内的热点数据"""
        pass

### 4.5 LLMProcessor类

```python
class LLMProcessor:
    """大模型处理器"""
    
    def __init__(self):
        # 初始化大模型客户端
        self.model_config = self._load_model_config()
        self.llm_client = self._init_llm_client()
    
    def _load_model_config(self) -> Dict[str, Any]:
        """加载大模型配置"""
        # 从配置文件加载模型参数
        pass
    
    def _init_llm_client(self):
        """初始化大模型客户端"""
        # 根据配置初始化对应的大模型客户端
        # 支持不同的大模型提供商
        pass
    
    async def analyze_content(self, title: str, content: str) -> Dict[str, Any]:
        """
        使用大模型分析内容特征
        
        Args:
            title: 文章标题
            content: 文章内容
            
        Returns:
            特征分析结果
        """
        # 1. 构建提示词
        # 2. 调用大模型API
        # 3. 解析响应结果
        # 4. 返回结构化特征数据
        pass
    
    def extract_keywords(self, text: str, top_n: int = 10) -> List[str]:
        """提取关键词"""
        pass
    
    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """情感分析"""
        pass
    
    def generate_summary(self, text: str, max_length: int = 100) -> str:
        """生成摘要"""
        pass

### 4.6 AnalysisStorage类

```python
class AnalysisStorage:
    """分析结果存储管理器"""
    
    def __init__(self):
        # 初始化存储配置
        pass
    
    def save_analysis_result(self, result: Dict[str, Any]) -> bool:
        """保存分析结果"""
        pass
    
    def save_batch_results(self, results: List[Dict[str, Any]]) -> bool:
        """批量保存分析结果"""
        pass
    
    def get_results_by_date(self, date: str) -> List[Dict[str, Any]]:
        """获取指定日期的分析结果"""
        pass
    
    def get_results_by_category(self, category: str, date: str = None) -> List[Dict[str, Any]]:
        """获取指定分类的分析结果"""
        pass
```

## 5. 数据流设计

### 5.1 整体流程

```
飞书表格热点数据 → FeishuDataLoader → FeatureAnalyzer → ContentExtractor → LLMProcessor → 特征分析结果 → HotspotClassifier → 分类结果 → AnalysisStorage → 结果查询
```

### 5.2 数据处理流程

1. **数据获取阶段**：
   - 从飞书表格(app_token: "EhSmbB0x0aujxXsNgPncjIyLntc", table_id: "tblOkYEu3bc87Tuo")获取热点数据
   - 支持按日期过滤和排名排序
   - 选择需要分析的热点（默认top 10）

2. **内容提取阶段**：
   - 对每个热点URL发送HTTP请求
   - 解析HTML页面，提取文章内容
   - 处理提取失败的情况（重试、跳过等）

3. **大模型特征分析阶段**：
   - 构建结构化提示词，包含标题和内容
   - 调用大模型API进行特征分析
   - 提取关键实体信息（人物、地点、事件等）
   - 分析标题吸引力
   - 评估传播潜力
   - 生成内容摘要
   - 进行情感分析

4. **分类阶段**：
   - 基于大模型的文本分类
   - 结合规则的分类结果优化
   - 计算分类置信度
   - 支持多级分类体系（主分类、子分类）

5. **存储阶段**：
   - 保存原始热点数据
   - 保存大模型特征分析结果
   - 保存分类结果
   - 生成统计摘要

## 6. 与现有系统集成

### 6.1 与Collection服务集成

- 可以直接使用Collection服务采集的热点数据
- 提供回调接口，在采集完成后自动触发特征分析

### 6.2 与Selection服务集成

- 为Selection服务提供热点分类信息，用于优化选材策略
- 提供特征分析API，供选材引擎查询

### 6.3 API接口设计

```python
# 在app/api/v1/analysis.py中添加新接口

@router.post("/feature-analysis/hotspots", response_model=List[HotspotAnalysisResponse])
async def analyze_hotspots(
    request: HotspotAnalysisRequest,
    analyzer: FeatureAnalyzer = Depends(get_feature_analyzer)
):
    """分析热点特征"""
    results = await analyzer.analyze_top_hotspots(
        date=request.date,
        limit=request.limit
    )
    return results

@router.get("/feature-analysis/summary", response_model=AnalysisSummaryResponse)
async def get_analysis_summary(
    category: Optional[str] = None,
    date: Optional[str] = None,
    analyzer: FeatureAnalyzer = Depends(get_feature_analyzer)
):
    """获取分析摘要"""
    # 实现摘要获取逻辑
    pass
```

## 7. 配置管理

在`config/`目录下创建`feature_analysis.yaml`配置文件：

```yaml
feature_analysis:
  # 飞书表格配置
  feishu:
    app_token: "EhSmbB0x0aujxXsNgPncjIyLntc"  # AI Headlines Pipeline
    table_id: "tblOkYEu3bc87Tuo"
    timeout: 30  # 请求超时时间（秒）
    retry_count: 3  # 失败重试次数
    
  # 大模型配置
  llm:
    provider: "openai"  # 可选值: openai, anthropic, baidu等
    model_name: "gpt-4"
    temperature: 0.3
    max_tokens: 2000
    api_key: "your_api_key_here"  # 从环境变量或密钥管理服务获取
    timeout: 60  # 请求超时时间（秒）
    retry_count: 3  # 失败重试次数

  # 内容提取配置
  extraction:
    timeout: 30
    max_retries: 3
    retry_delay: 5
    user_agent: "Mozilla/5.0..."
    proxy_enabled: false
    
  # 分类配置
  classification:
    default_threshold: 0.6
    use_ml_model: false
    ml_model_path: "models/hotspot_classifier.model"
    
  # 存储配置
  storage:
    type: "json_file"  # 可选: json_file, database
    json_dir: "data/analysis_results"
    database_url: "sqlite:///./analysis.db"  # 如果使用数据库
    
  # 分类规则配置
  category_rules:
    tech:
      keywords: ["科技", "人工智能", "5G", "芯片", "互联网", "算法", "大数据", "区块链", "元宇宙"]
      domains: ["tech", "science", "digital", "innovation"]
    
    life:
      keywords: ["健康", "美食", "旅行", "时尚", "生活", "家居", "育儿", "减肥", "健身"]
      domains: ["lifestyle", "health", "food", "travel"]
    
    politics:
      keywords: ["政策", "政府", "会议", "领导人", "改革", "法案", "选举", "外交", "国际"]
      domains: ["politics", "government", "diplomacy", "election"]
    
    entertainment:
      keywords: ["电影", "音乐", "明星", "综艺", "演唱会", "电视剧", "娱乐", "绯闻"]
      domains: ["entertainment", "celebrity", "movie", "music"]
    
    finance:
      keywords: ["股票", "经济", "金融", "投资", "企业", "市场", "股市", "银行", "贸易"]
      domains: ["finance", "economy", "stock", "business"]
    
    sports:
      keywords: ["体育", "足球", "篮球", "比赛", "赛事", "运动员", "冠军", "奥运", "世界杯"]
      domains: ["sports", "football", "basketball", "match"]
```

## 8. 部署与集成建议

### 8.1 部署架构

- **集成到现有服务**：将热点特征分析模块集成到现有的analysis服务中
- **定时任务执行**：设置定时任务，每天定时从飞书表格获取数据并进行分析

### 8.2 性能优化建议

- 使用异步处理提高并发性能
- 实现缓存机制减少重复分析和API调用
- 对大文本进行分片处理
- 优化大模型调用，合理设置上下文窗口和参数

### 8.3 监控与告警

- 监控飞书API调用频率和成功率
- 监控大模型API调用状态和延迟
- 监控分析任务的执行时间
- 设置异常告警机制

### 8.4 依赖安装

- 需要安装的新依赖：
  - `newspaper3k` 或 `readability-lxml`：用于文章内容提取
  - `jieba`：用于中文分词
  - `scikit-learn`（可选）：用于机器学习分类
  - `fasttext`（可选）：用于文本分类

## 9. 异常处理

### 9.1 飞书API异常处理

- 实现指数退避重试机制
- 处理API限流和配额问题
- 对数据格式异常进行优雅降级

### 9.2 大模型调用异常处理

- 处理API超时和失败
- 实现请求重试和错误恢复
- 对异常响应进行验证和清理

### 9.3 内容提取异常处理

- 处理URL访问失败
- 处理不同网站结构和编码问题
- 对提取失败的内容提供合理的默认值

### 9.4 熔断机制

- 实现熔断机制，避免单个站点问题影响整体分析
- 设置重试和失败阈值，防止系统资源耗尽
- 对提取失败的URL进行日志记录和智能重试

## 9. 后续优化方向

1. **模型优化**：
   - 训练更准确的分类模型
   - 引入深度学习模型进行内容理解

2. **特征扩展**：
   - 增加图片分析能力
   - 引入社交媒体传播路径分析

3. **实时性提升**：
   - 实现流式处理架构
   - 提供近实时的热点分析能力

4. **用户交互**：
   - 开发热点分析可视化界面
   - 提供自定义分析规则的能力

## 10. 风险评估

1. **内容提取风险**：
   - 网站结构变化导致提取失败
   - 反爬机制可能限制访问
   - 解决方案：定期更新提取规则，实现自适应提取策略

2. **分类准确性风险**：
   - 基于规则的分类可能不够准确
   - 解决方案：结合机器学习模型，不断优化分类规则

3. **性能风险**：
   - 大量URL请求可能导致性能瓶颈
   - 解决方案：实现批量处理和并发请求，优化资源使用

4. **数据质量风险**：
   - 提取的内容可能不完整或包含噪声
   - 解决方案：实现内容质量评估机制，过滤低质量数据

---

本设计方案提供了热点特征分析模块的完整架构和实现思路，可根据实际需求进行调整和优化。