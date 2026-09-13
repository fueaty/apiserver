# 增量 PRD：字段补齐 + 正文采集 + ai_insights 写入

> 类型：**增量需求 PRD**（已上线生产系统 `apiserver`，非从零新项目）
> 语言：中文 ｜ 技术栈：Python 3.9.19 + FastAPI + lark_oapi + 飞书多维表格
> 范围：仅覆盖本文件 3 项增量需求，不复述既有系统全貌

---

## 0. 背景（一句话）

`apiserver` 是"热点采集 → 飞书多维表格 → 内容选材 → 多平台发布"的流水线。本次增量解决三个**已知缺陷/缺口**，且必须以**最小变更**方式落地，不触碰既有稳定逻辑。

---

## 1. 产品目标

**一句话目标**：让采集到的真实数据不再被静默丢弃、让热点记录具备正文、并首次打通"headlines → LLM → ai_insights"的深度内容链路。

| 指标 | 现状 | 目标 | 可衡量方式 |
|---|---|---|---|
| `headlines.published_at` 落库率 | 0%（写入即被丢弃） | 新采集记录 ≥ 95% 有值 | 线上表随机抽样 100 条非空占比 |
| `publish_tasks.error_message` 字段是否在线 | 字段不存在 | 字段存在（结构对齐） | `ensure_table_fields` 后线上字段集合校验 |
| 采集器返回正文的站点数 | 1/9（仅知乎返回摘要） | 摘要/正文可用站点 ≥ 7/9 | 单次采集后 `content` 非空记录占比 |
| 正文抓取接口成功率（成功抓取站点的合法 URL） | 无能力 | ≥ 80%（可抓站点），失败均优雅降级 | 接口返回 `succeeded/total` |
| `ai_insights` 可写入 | 无任何写入代码 | 端到端可写入 1 条 | 调用端点后线上表新增 1 行 |

**正交性**：① 修复"数据正确性/不丢失"；② 补齐"内容完整性"；③ 新增"价值产出链路"。三者互不依赖，可独立交付。

---

## 2. 用户故事

**① 字段缺口**
- 作为**内容运营**，我希望头条记录保留真实发布时间（`published_at`），以便按时间排查/排序热点，而不是只能看到采集时间。
- 作为**发布负责人**，我希望发布失败的原因（`error_message`）能落库，以便无需翻日志即可定位失败。
- 作为**维护者**，我希望采集器不再写入与 `site_code` 语义重复的 `platform` 字段，以免误导后续数据消费方。

**② 正文采集**
- 作为**内容编辑**，我希望对指定 URL 或一批 headlines 记录按需抓取网页正文，以便对需要深度加工的热点拿到全文。
- 作为**维护者**，我希望正文抓取是独立、按需触发的能力，不拖慢每天 08:00/21:00 的主采集流水线。
- 作为**维护者**，我希望抓取过程尊重 `robots.txt`、有超时与并发上限，且单条失败不影响整批。

**③ ai_insights 深度内容写入**
- 作为**内容运营**，我希望从 headlines 选定记录后一键生成深度内容（摘要/标签/情感/SEO 等）并写入 `ai_insights`，以便直接复用。
- 作为**维护者**，我希望 LLM 客户端可插拔、无 Key 时自动降级为 Mock，保证链路与测试在无外部依赖时也能跑通。
- 作为**维护者**，我希望配置里绝不硬编码密钥，真实 Key 只从 `config/credentials.yaml` 读取。

---

## 3. 需求池

> 优先级：P0 = 必须交付；P1 = 应当交付；P2 = 可选。
> 所有验收标准均可测试，且默认遵循"依赖桩 + 断言计数器"的离线测试风格（见 §6）。

### 需求 ①：字段缺口修复

| 编号 | 优先级 | 需求描述 | 验收标准 | 影响文件（初步） |
|---|---|---|---|---|
| R1-1 | **P0** | 将 `published_at` 加入 `TABLE_PLANS['headlines']` 显式名单（定义已在 `BASE_FIELD_DEFINITIONS`，**无需重复定义**），使 `ensure_table_fields` 会**创建**该列而非删除 | ① `headlines` 解析字段集合包含 `published_at`；② 携带 `published_at` 的记录经 `_align_records_with_fields` 后**不被丢弃**；③ 其余表 `TABLE_PLANS` 字段集冻结不变 | `app/services/feishu/field_rules.py` |
| R1-2 | **P0** | `published_at` 列补齐后，验证采集写入路径真实落库（`zhihu/thepaper/cctv` 等） | 桩化 `batch_add_records`，断言送入对齐函数的记录含 `published_at` 键；线上抽检非空 | `app/services/feishu/feishu_service.py`(读)、`sites/*.py`(读) |
| R1-3 | **P0** | 将 `error_message` 加入 `TABLE_PLANS['publish_tasks']` 显式名单（定义已在 `BASE_FIELD_DEFINITIONS`） | `publish_tasks` 解析字段集合包含 `error_message`；字段同步后线上存在该列 | `app/services/feishu/field_rules.py` |
| R1-4 | **P1** | 明确 `error_message` 取值口径：`manager.py` 仅在 `result['success']` 为真时构造该字段，导致恒为空串；修正为**失败时也写入失败原因** | 桩化发布结果为失败时，`publish_tasks` 记录 `error_message` 非空 | `app/services/publication/manager.py` |
| R1-5 | **P1** | 移除 `sites/zhihu.py` 中与 `site_code` 冗余的 `"platform": "zhihu"` 键；`headlines` 名单**不**补 `platform` | `headlines` 解析集合**不含** `platform`；`zhihu.py` 源码不再出现 `"platform"` 键（AST/文本断言） | `app/services/collection/sites/zhihu.py` |

**取舍说明（重要）**：
- `published_at` / `error_message` 二者**已在 `BASE_FIELD_DEFINITIONS` 中定义**（第 23、31 行），缺的是 `TABLE_PLANS` 显式名单。因 `_resolve_fields` 只校验"显式名单里的名字是否已定义"，这两个名字不会触发 `ValueError`，改动是**纯新增名单项**，风险极低。
- `platform` **不补**：它与 `site_code` 语义重复，且只有 1 个站点写，补了反而制造跨表污染风险（历史缺陷 8 的根因）。改为**在写入侧清理**冗余键。

### 需求 ②：正文采集能力

| 编号 | 优先级 | 需求描述 | 验收标准 | 影响文件（初步） |
|---|---|---|---|---|
| R2-1 | **P0** | 新增**独立**正文抓取能力：给定 URL 抓取并抽取正文文本（按站点选择器 + 通用兜底） | 对本地 HTML 夹具（fixture）能抽出正文；未配置选择器的站点走通用兜底；抽出为空时返回 `EXTRACT_EMPTY` 而非异常 | **新增** `app/services/collection/content_fetcher.py` |
| R2-2 | **P0** | 提供按需 REST 端点：输入 URL 列表或 headlines 记录 id，逐条抓取并返回**逐条状态** | 见 §4.1 契约：部分成功返回 200 且 `results` 含逐条 `status`；超时/失败不使整批 500 | **新增** `app/api/v1/endpoints/content.py`；注册于 `app/api/v1/api.py` |
| R2-3 | **P0** | 抓取过程：**超时**、**并发上限**、**尊重 robots.txt**（复用 `robots_checker`） | robots 禁止时该条 `status=skipped, error_code=ROBOTS_DISALLOWED`；并发不超过配置上限（桩计数断言） | `app/services/collection/content_fetcher.py`、`app/services/collection/robots_checker.py`(复用) |
| R2-4 | **P0** | **优雅降级**：任一条抓取失败不得使整批失败，原记录保持不变 | 桩化"部分 URL 超时"，断言其余条目仍成功、接口整体 200 | `app/services/collection/content_fetcher.py` |
| R2-5 | **P1** | 抓到的正文可**回写** `headlines.content`（按记录 id 更新，不产生重复行） | 回写后原记录 `content` 更新为正文；不新增重复记录；`write_back=false` 时不写 | `app/services/feishu/feishu_service.py`(需新增/复用 update)、`content_fetcher.py` |
| R2-6 | **P1** | 可选小批处理 backfill：扫描 `headlines` 中 `content` 为空的记录，限量抓取回写（支持 `dry_run`） | `dry_run=true` 只返回计划不写入；`limit` 生效；失败条目被跳过不影响其余 | 同上 + **新增** `script/fetch_content_backfill.py` |
| R2-7 | **P2** | 按站点可配置正文选择器，配置落在 `config/sites.yaml` | 站点配置新增 `content_selector` 后，抓取优先命中该选择器 | `config/sites.yaml`、`content_fetcher.py` |

**取舍说明**：**不把正文抓取并入主采集 cron**。主流水线每天跑 2 次、已稳定（含 20,000 条上限、500/批分片、超限自愈、upsert 语义），加重活会使其变慢变脆。改为**按需触发端点 + 可选独立脚本**。

### 需求 ③：ai_insights 深度内容写入

| 编号 | 优先级 | 需求描述 | 验收标准 | 影响文件（初步） |
|---|---|---|---|---|
| R3-1 | **P0** | 新增 `ai_insights` **写入端点**：从 `headlines` 读指定记录 → 调 LLM 生成深度内容 → 写入 `ai_insights` | 见 §4.2 契约；Mock 模式下端到端返回 `written≥1` | **新增** `app/api/v1/endpoints/insights.py`（或并入 `analysis.py`）；注册于 `api.py` |
| R3-2 | **P0** | LLM 客户端**可插拔**：真实实现走 OpenAI 兼容协议，Key 从 `config/credentials.yaml` 读，**绝不硬编码**；无 Key 自动降级 Mock | 无 Key 时 `llm_client=mock` 且链路成功；有 Key（桩）时走真实分支；源码无硬编码 Key（文本断言） | `app/services/analysis/feature_analysis/llm_processor.py`、`config/credentials.yaml.example` |
| R3-3 | **P0** | 字段映射：headlines → ai_insights 14 字段（见 §5.3） | 映射后字段集合 ⊇ `TABLE_PLANS['ai_insights']`（14 字段），无缺失 | `app/services/analysis/**`、`app/services/feishu/field_rules.py`(读) |
| R3-4 | **P1** | 写入走 `feishu_service.batch_add_records`（唯一收口，含超限自愈） | 桩化后调用参数含 `ai_insights` 的 app_token/table_id | `app/services/feishu/feishu_service.py`(复用) |
| R3-5 | **P1** | 新增**预检**端点：返回 LLM 配置状态 + `ai_insights` 线上表结构是否与规划一致 | 未确认表结构时返回 `TABLE_SCHEMA_UNCONFIRMED` 提示 | `insights.py`、`feishu_service.py`(读) |

**前置条件（写入硬门槛）**：`ai_insights` 表**当前无任何写入代码、可能无数据**，属全新链路。**首次写入前必须人工确认线上表结构与 `TABLE_PLANS['ai_insights']` 一致**，避免字段不匹配被静默丢弃。R3-5 预检端点即为此服务。

---

## 4. 接口 / 交互设计（REST API 契约）

> 无 UI。所有端点沿用既有鉴权：`Authorization: Bearer <token>`（`verify_token`），失败返回 401。
> 统一响应包裹：`{"code": <int>, "message": <str>, "data": <obj|null>}`。

### 4.1 正文抓取（需求 ②）

#### `POST /api/v1/collection/content/fetch`（P0）

**请求体**
```json
{
  "urls": ["https://www.thepaper.cn/newsDetail_forward_xxx"],
  "record_ids": ["2025010112ab3"],
  "site_code": "thepaper",
  "write_back": false,
  "concurrency": 4,
  "timeout": 10
}
```
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `urls` | `List[str]` | 二选一 | 与 `record_ids` 至少提供一个；同时提供时以 `urls` 为准 |
| `record_ids` | `List[str]` | 二选一 | headlines 记录 id，服务端反查 `url` |
| `site_code` | `str` | 否 | 未提供时按 URL 域名/站点配置推断；用于选择正文选择器 |
| `write_back` | `bool` | 否 | `true` 时把正文回写 `headlines.content`；默认 `false` |
| `concurrency` | `int` | 否 | 缺省取服务端上限，超出被截断 |
| `timeout` | `int` | 否 | 单请求超时秒，缺省 10，上限 30 |

**响应体（200，部分失败也 200）**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 2, "succeeded": 1, "failed": 1, "skipped": 0,
    "results": [
      {"url": "https://...", "record_id": "2025010112ab3", "status": "success",
       "title": "...", "content": "...", "content_length": 1234,
       "extractor": "site_selector", "elapsed_ms": 320},
      {"url": "https://...", "record_id": null, "status": "failed",
       "error_code": "FETCH_TIMEOUT", "error_message": "read timeout", "retryable": true}
    ]
  }
}
```
- 逐条 `status` ∈ `success | failed | skipped`
- 逐条 `error_code` ∈ `FETCH_TIMEOUT | FETCH_HTTP_ERROR | FETCH_CONNECT_ERROR | ROBOTS_DISALLOWED | EXTRACT_EMPTY | INVALID_URL | INTERNAL_ERROR`

**错误码（HTTP 级）**

| HTTP | 场景 |
|---|---|
| 400 | `urls` 与 `record_ids` 同时为空；`timeout`/`concurrency` 非法 |
| 401 | 未通过鉴权 |
| 404 | `record_ids` 全部在 headlines 中查不到 |
| 500 | 服务端异常（**不含**单条抓取失败） |

#### `POST /api/v1/collection/content/backfill`（P1）

**请求体**：`{"site_code": "thepaper", "limit": 50, "dry_run": true}`
**响应体**：`data` 含 `planned / fetched / written / skipped`，逐条结果同 §4.1。
- `dry_run=true`：只返回计划清单，不抓取、不写入。

### 4.2 ai_insights 生成与写入（需求 ③）

#### `POST /api/v1/analysis/insights/generate`（P0）

**请求体**
```json
{
  "record_ids": ["2025010112ab3"],
  "urls": [],
  "generate": ["summary", "tags", "sentiment", "seo_title", "seo_description", "seo_keywords", "category"],
  "llm": {"provider": "openai", "model_name": "gpt-4-turbo", "temperature": 0.3, "max_tokens": 2000},
  "dry_run": false,
  "write": true
}
```
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `record_ids` / `urls` | `List[str]` | 二选一 | 与 §4.1 同口径；来源为 headlines |
| `generate` | `List[str]` | 否 | 需 LLM 生成的字段子集；缺省为全部可生成字段 |
| `llm` | `object` | 否 | 本次调用覆盖默认配置（provider/model/temperature/max_tokens） |
| `dry_run` | `bool` | 否 | 只生成不写入 |
| `write` | `bool` | 否 | 默认 `true`；写入 `ai_insights` |

**响应体**
```json
{
  "code": 200, "message": "success",
  "data": {
    "total": 1, "generated": 1, "written": 1, "failed": 0,
    "llm_provider": "openai", "llm_client": "mock",
    "results": [
      {"record_id": "2025010112ab3", "url": "https://...", "status": "success",
       "insight_id": "2025010113cd4",
       "fields": {"title": "...", "summary": "...", "tags": "...", "sentiment": "中性",
                  "seo_title": "...", "seo_description": "...", "seo_keywords": "..."}}
    ]
  }
}
```
- `llm_client` ∈ `real | mock`（无 Key 时为 `mock`，链路仍应成功）
- 逐条 `status` ∈ `success | failed | skipped`
- 逐条 `error_code` ∈ `LLM_NOT_CONFIGURED | LLM_TIMEOUT | LLM_RESPONSE_PARSE_ERROR | HEADLINE_NOT_FOUND | TABLE_SCHEMA_UNCONFIRMED | FEISHU_WRITE_FAILED | INTERNAL_ERROR`

**错误码（HTTP 级）**：400（来源为空）/ 401 / 404（headlines 记录全不存在）/ 500（服务端异常）。

#### `GET /api/v1/analysis/insights/preflight`（P1）

**响应体**：`data = {"llm": {"provider_configured": bool, "has_api_key": bool, "client": "real|mock"}, "table": {"name": "ai_insights", "schema_confirmed": bool, "missing_fields": [...]}}`
- 用途：首次写入前人工确认"Key 是否就绪 + 线上表结构是否与规划一致"。

---

## 5. 数据设计

### 5.1 需求 ① 字段增补清单

| 表 | 字段名 | 类型 | 是否需改 `BASE_FIELD_DEFINITIONS` | 动作 | 理由 |
|---|---|---|---|---|---|
| `headlines` | `published_at` | text | **否**（第 23 行已定义） | 加入 `TABLE_PLANS['headlines']` 显式名单 → **补** | 真实发布时间，全站点通用；不补则可能被当作多余列删除 |
| `headlines` | `platform` | text | 否 | **不补**；改为清理 `sites/zhihu.py` 冗余键 | 与 `site_code` 语义重复，仅 1 站写 |
| `publish_tasks` | `error_message` | text | **否**（第 31 行已定义） | 加入 `TABLE_PLANS['publish_tasks']` 显式名单 → **补** | 发布失败原因需落库 |

> ⚠️ 通用规则重申：`ensure_table_fields()` 执行 `fields_to_delete = 线上字段 - required_fields`，凡不在解析集合内的线上列都会被删除（连带数据）。因此任何"写入方在写但规划里没有"的字段都必须补进 `TABLE_PLANS` 显式名单；引用未定义字段名会在 import 期抛 `ValueError`（`_resolve_fields` 守卫）。

### 5.2 需求 ② 正文回写策略

- **回写目标列**：`headlines.content`（该列已在 `headlines` 名单中，无需改字段规划）。
- **定位方式**：按 headlines 记录 id + 线上 `record_id` 更新，**不得**新增重复行（`batch_add_records` 是"新增"语义）。→ 需确认飞书是否支持按记录更新（见 §7）。
- **覆盖策略（建议）**：默认**仅当 `content` 为空时写入**；`overwrite=true` 才覆盖已有值（如知乎 `excerpt` 摘要）。避免摘要被正文无条件冲掉。
- **降级**：抓取失败/被 robots 拒绝的记录**保持原样**，只在响应中标注状态。

### 5.3 需求 ③ 字段映射（headlines → ai_insights，14 字段）

| ai_insights 字段 | 来源 | 说明 |
|---|---|---|
| `id` | `generate_content_id()` 新生成 | 时间戳+5 位随机 |
| `title` | `headlines.title` | 直传 |
| `url` | `headlines.url` | 直传 |
| `content` | `headlines.content`；为空则退化为 `title`+`summary` | 建议先触发需求 ② |
| `author` | `headlines.author` | 可能为空 |
| `category` | LLM 生成，缺省回退 `headlines.category` | |
| `summary` | LLM 生成 | |
| `tags` | LLM 生成（多值逗号连接为 text） | |
| `sentiment` | LLM 生成（积极/中性/消极） | |
| `seo_title` | LLM 生成 | |
| `seo_description` | LLM 生成 | |
| `seo_keywords` | LLM 生成 | |
| `published_at` | `headlines.published_at` | **依赖需求 ①** 落地 |
| `status` | 固定 `"generated"` | 或 `"pending"` |

---

## 6. 非功能需求

### 6.1 硬约束（生产/本机环境）

1. **Python 3.9.19 兼容**：禁止 `match` 语句、`X | Y` 联合类型、`dict1 | dict2`、运行时位置的 `list[str]`/`dict[str,int]` 内建泛型（用 `typing.List/Dict/Optional`）。Pydantic 为 **v2**，用 `model_dump()` 而非 `.dict()`。
2. **离线可测**：本机无项目依赖（`aiohttp/httpx/lark_oapi/pydantic/fastapi` 全缺），bash 的 `ls/grep/tail/dirname` 不可用。测试一律用"**依赖桩 + 断言计数器**"风格，参考 `tests/test_feishu_field_plans.py`、`tests/test_publication_platforms.py`。
3. **不碰真实密钥**：不改 `config/credentials.yaml` 中的生产密钥；新增配置项只写 `config/credentials.yaml.example`。
4. **不破坏既有测试**：`tests/test_feishu_capacity.py`(59) + `tests/test_feishu_field_plans.py`(38) + `tests/test_publication_platforms.py`(110) 共 **207 条断言**必须继续全过。
5. **增量最小变更**：不重构既有稳定逻辑。

### 6.2 性能 / 超时 / 并发 / 降级

| 项 | 要求 |
|---|---|
| 单请求超时 | 正文抓取 ≤ 10s（可配，上限 30s）；LLM 调用超时独立配置 |
| 并发上限 | 正文抓取并发默认 ≤ 4（服务端硬上限，防打爆目标站与自身） |
| robots.txt | 抓取前检查；禁止则跳过并标注，不重试 |
| 主流水线隔离 | 正文抓取与 ai_insights 生成**不得**并入 08:00/21:00 主采集 cron |
| 优雅降级 | 单条失败不影响整批；LLM 无 Key → Mock；抓取失败 → 保留原记录 |
| 幂等/去重 | 回写走"更新"而非"新增"，避免重复行 |
| 可观测 | 每个端点返回逐条状态 + `elapsed_ms`，便于排障 |

---

## 7. 待确认问题（需人工拍板）

| # | 问题 | 现状/冲突 | 建议 |
|---|---|---|---|
| Q1 | **文档口径不一致**：`doc/飞书多维表格设计文档.md` §1.1 未列 `published_at`，但 §1.2/§1.3 列了；§1.8 未列 `error_message` | 文档与写入方实际行为冲突 | **以写入方实际行为为准**（headlines 有 `published_at`、publish_tasks 有 `error_message`）；同步修订文档 |
| Q2 | **线上表结构变更确认**：`headlines`/`publish_tasks` 补列、`ai_insights` 首次启用 | 生产表结构不可擅动 | 执行前由人工在飞书侧确认；`ai_insights` 首次写入前必须过 R3-5 预检 |
| Q3 | **LLM provider / 模型 / 端点 / 出网** | `config/*.yaml` 无 `llm` 段 | 确认 provider（OpenAI 兼容？内网？）、模型名、是否需代理；Key 放 `credentials.yaml`（示例文件仅占位） |
| Q4 | **LLM 基础设施现状** | `LLMProcessor._initialize_llm_client()` 固定返回 `LLMMockClient`；且其依赖的 `config_manager.get_config()` 在 `app/core/config.py` 中**不存在**（疑似未实现） | 确认是补齐 `get_config()` 还是改用既有 `get_credentials()`；真实客户端需新建 |
| Q5 | **正文抓取合规边界** | 版权/转载/频率 | 确认可全文抓取的站点白名单、User-Agent 标识、频率上限、是否仅内部使用 |
| Q6 | **回写机制** | `batch_add_records` 是"新增"语义 | 确认飞书是否支持按记录更新（update record / 按主键 upsert），否则回写会产生重复行 |
| Q7 | **正文覆盖策略** | 知乎 `content` 现为 `excerpt` 摘要 | 确认默认"仅空时写入"还是允许 `overwrite` |
| Q8 | **error_message 语义** | `manager.py` 仅在 success 时构造，恒为空串 | 确认是否一并修正调用逻辑（失败也落库，见 R1-4） |
| Q9 | **并发/超时默认值** | 未定义 | 确认正文抓取并发与超时的生产默认值 |
| Q10 | **是否入调度** | 主 cron 已稳定 | 确认正文 backfill 是否需定时（建议：仅手动/按需） |

---

## 附：影响文件总览（供架构师接手）

| 需求 | 主要改动 |
|---|---|
| ① | `app/services/feishu/field_rules.py`（+2 名单项）、`app/services/publication/manager.py`（可选）、`app/services/collection/sites/zhihu.py`（-1 键） |
| ② | **新增** `app/services/collection/content_fetcher.py`、`app/api/v1/endpoints/content.py`；**新增** `script/fetch_content_backfill.py`；改 `app/api/v1/api.py`、`config/sites.yaml`、`feishu_service.py`(update) |
| ③ | **新增** `app/api/v1/endpoints/insights.py`；改 `app/services/analysis/feature_analysis/llm_processor.py`、`app/api/v1/api.py`、`config/credentials.yaml.example` |
| 测试 | **新增** 正文抓取/字段映射/LLM 可插拔的断言计数器测试；保证既有 207 断言全过 |
