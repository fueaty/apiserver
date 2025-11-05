# API设计文档

## 1. 概述

本API服务器基于智能体工作流平台的调用需求，提供轻量级、高安全性、易维护的原子能力服务，实现"信息采集→智能选材→内容发布"的完整自动化流程闭环。

## 2. 技术架构

- **Web框架**：FastAPI（异步支持优秀，自动生成API文档）
- **异步运行时**：Uvicorn（ASGI服务器，专为异步应用优化）
- **配置管理**：YAML文件 + 内存缓存（零数据库依赖）
- **数据解析**：BeautifulSoup（HTML解析）、PyYAML（配置解析）

## 3. 认证机制

采用JWT令牌认证机制，但不提供外部接口申请令牌。所有API访问令牌必须通过本地脚本生成，并存储在预设文件中。

### 3.1 令牌生成与管理

1. 使用本地脚本 `/root/apiserver/secret/generate_auth_key.py` 生成JWT令牌
2. 生成的令牌自动记录在 `/root/apiserver/secret/auth_key.json` 文件中
3. 服务端启动时加载该文件中的有效认证令牌
4. 客户端从该文件获取有效的JWT令牌用于API访问

### 3.2 使用令牌

所有业务接口需在Header携带：

```
Authorization: Bearer <authkey>
```

## 4. 核心业务接口

### 4.1 网站信息采集接口

#### 接口地址

```
GET /api/v1/collection
```

#### 请求参数

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| date | string | 否 | 采集日期(YYYY-MM-DD) | 2025-10-28 |
| site_code | string | 否 | 网站编码(逗号分隔) | weibo,baidu |
| category | string | 否 | 分类筛选(配置驱动) | technology |
| keyword | string | 否 | 关键词筛选(配置驱动) | AI |

#### 响应结构（飞书兼容格式）

```json
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
```

### 4.2 智能选材接口

#### 接口地址

```
POST /api/v1/selection
```

#### 请求体

```json
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
```

#### 响应结构（飞书兼容格式）

```json
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
```

### 4.3 多平台内容发布接口

#### 接口地址

```
POST /api/v1/publication
```

#### 请求体规范

```json
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
```

#### 发布结果响应

```json
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
```

### 4.4 采集并直接入库接口

#### 接口地址

```
GET /api/v1/enhanced-collection/collect-and-store
```

#### 功能说明

采集指定网站的信息并直接存储到飞书多维表格

#### 请求参数

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| date | string | 否 | 采集日期(YYYY-MM-DD) | 2025-10-28 |
| site_code | string | 否 | 网站编码(逗号分隔) | weibo,baidu |
| category | string | 否 | 分类筛选(配置驱动) | technology |
| keyword | string | 否 | 关键词筛选(配置驱动) | AI |

#### 响应结构

```json
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
```

### 4.5 选材并入库接口

#### 接口地址

```
POST /api/v1/enhanced-collection/select-and-store
```

#### 功能说明

从热点库提取数据进行选材分析，并将选材结果存储到飞书多维表格

#### 请求体

```json
{
  "platforms": ["xiaohongshu", "zhihu", "wechat_public"]
}
```

#### 响应结构

```json
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
```

## 5. 系统管理接口

### 5.1 认证验证接口

#### 接口地址

```
POST /api/v1/auth/verify
```

#### 功能说明

验证访问令牌的有效性

#### 请求头

```
Authorization: Bearer <authkey>
```

#### 响应结构

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "client_id": "client_id",
    "expires_at": 1234567890,
    "valid": true
  }
}
```

### 5.2 获取可用站点列表接口

#### 接口地址

```
GET /api/v1/collection/sites
```

#### 功能说明

获取当前可用的采集站点列表

#### 请求头

```
Authorization: Bearer <authkey>
```

#### 响应结构

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "sites": {
      // 站点配置信息
    },
    "total": 7
  }
}
```

## 6. 错误处理

系统使用统一的错误响应格式：

```json
{
  "code": 500101,
  "message": "采集失败: 具体错误信息",
  "data": null
}
```

常见错误码：
- 40101: 无效的认证令牌
- 40102: 令牌已过期
- 500101: 采集失败
- 500102: 获取站点列表失败
- 500103: 采集并存储失败
- 500104: 选材并存储失败

## 7. 性能指标

- **响应时间**：采集接口≤5秒，选材接口≤3秒，发布接口≤8秒
- **吞吐量**：10-20 QPS稳定运行
- **资源利用率**：CPU平均<70%，内存<1.2G
- **可用性**：99.9%（单机部署）

## 8. 部署架构

### 8.1 服务器环境要求

- 操作系统：Rocky Linux 8.5+
- 硬件配置：2核CPU，2GB内存，20GB SSD存储
- 网络要求：开放443端口（HTTPS），支持 outbound 访问目标网站和内容平台API

### 8.2 部署架构图

```
┌─────────────────────────────────────────┐
│             服务器 (2核2G)               │
├─────────────┬──────────────┬────────────┤
│ Nginx (反向代理) │ Uvicorn (ASGI) │ 应用服务     │
│ - SSL终结    │ - 4工作进程   │ - FastAPI应用 │
│ - 静态资源    │ - 异步I/O     │ - 配置文件    │
└─────────────┴──────────────┴────────────┘
```