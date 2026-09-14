# apiserver

**热点采集 → 飞书多维表格 → 内容选材 → 多平台发布** 的自动化管道。

> 本 README 描述**仓库与生产的当前状态**（基线提交 `c3d05ae`）。
> 2025-11-05 那一版「agent-api 系统设计稿」描述的是另一套架构（Rocky Linux + systemd + nginx 常驻微服务），
> 与实现已不对应；原文可用 `git show f1a5f31:README.md` 取回。设计细节看 `doc/`（索引见 §十）。

---

## 一、系统在做什么

```
cron 08:00 / 21:00
        │
        ▼
script/run_daily_task.sh ──► script/everday_task.py
        │                        │
        │                        ├─► script/collection_pipeline.py    采集 9 站 → 写飞书 headlines 表
        │                        └─► script/export_today_headlines.py 导出当日快照到 <root>/{date}_headlines_data.json
        ▼
cron 02:00
        │
        ▼
script/scheduled_cleanup.sh ──► script/cleanup_feishu_data.py
                                 ① 按时间：删除 25 天前的记录
                                 ② 按容量：仍高于水位则从最旧开始删到水位以内
```

- **采集**：`app/services/collection/engine.py` 调度 9 个站点，归一化成飞书字段体后**按 `title` upsert** 写入 `headlines` 表（只与**当天**记录比对，跨天重复是设计语义）。
- **选材 / 发布**：`app/services/selection/`、`app/services/publication/`，配套 HTTP 接口见 §五。
- **正文与深度内容**：`app/services/collection/content_fetcher.py`（按需抓正文）、`app/services/analysis/`（LLM 特征分析）。

---

## 二、运行环境与实际运行方式

| 项 | 现状 |
|---|---|
| 生产 OS / Python | openEuler 24.03 / **Python 3.11.6** |
| 生产代码路径 | `/opt/apiserver`（`/root/apiserver` 是它的软链，兼容历史硬编码） |
| 调度 | 生产只有 **3 条 cron**（下表）；**仓库内不存在任何 systemd unit 文件** |
| 依赖 | 以 `requirements.txt` 为准（生产 `pip freeze` 的去噪超集，92 条）；详见该文件头部注释 |
| 仓库内其它运行形态 | FastAPI 常驻服务（`app/main.py`）+ 容器化（`Dockerfile` / `docker-compose.yml` / `deploy.sh`）。**生产当前的实际执行路径是 cron 批任务。** |

**三条 cron（生产唯一调度）**

| 时间 | 脚本 | 作用 |
|---|---|---|
| `0 8 * * *` | `script/run_daily_task.sh` | 采集 + 导出当日归档 |
| `0 21 * * *` | `script/run_daily_task.sh` | 采集 + 导出当日归档 |
| `0 2 * * *` | `script/scheduled_cleanup.sh` | 飞书表清理（时间 + 容量两级） |

`script/` 下其它脚本均为**人工**入口，不在调度内：`verify_run.sh`（带副作用的运行验证）、
`api_pipeline.py` / `collection_pipeline.py`（手动重放整条链路）、`cleanup_feishu_data.py`（清理 CLI）、
`smart_cleanup.py`、`manage_history_data.py`（归档搬移）、`analyze_history_data.py`、`export_headlines.py`、
`export_all_headlines.py`、`fetch_content_backfill.py`（正文回填）、`deduplicate_collect.py`、`start.sh`。

---

## 三、目录结构

| 路径 | 职责 |
|---|---|
| `app/api/v1/endpoints/` | 10 个路由模块（认证 / 采集 / 选材 / 发布 / 任务 / 飞书 / 分析 / 增强 / 正文 / 深度内容） |
| `app/middleware/` | 限流、异常处理、请求日志、安全响应头 |
| `app/services/collection/` | 采集引擎、9 个站点实现（`sites/`）、robots 检查、正文抓取、mock 治理、容量名录 |
| `app/services/feishu/` | `feishu_service.py`（读写/清理）、`field_rules.py`（字段规划）、`limits.py`（容量常量）、`function/`（初始化与调试脚本） |
| `app/services/selection/` | 选材引擎（含 `ml_engine.py`） |
| `app/services/publication/` | 多平台发布（`platforms/`：知乎 / 小红书 / 微信 / 微博 / 头条 / 掘金） |
| `app/services/analysis/` | 热点特征分析、`insights_service.py` |
| `app/tasks/` + `app/core/celery_config.py` | Celery 异步任务（容器化形态使用） |
| `app/wework/` | 企业微信通知与文件推送 |
| `script/` | 生产入口与运维脚本（§二） |
| `tests/` | **独立测试脚本**，直接 `python tests/<name>.py` 运行 |
| `config/` | 仓库只跟踪 4 个：`sites.yaml` / `platforms.yaml` / `analysis.yaml` / `redis.conf`。另 3 个（`zhihu.yaml` / `xiaohongshu.yaml` / `credentials.yaml`）已 gitignore，仓库里只有对应的 `*.example` |
| `doc/` | 设计文档与运维文档（§十） |
| `secret/` | JWT 令牌生成脚本与本地令牌文件（不入 git） |

---

## 四、采集站点与容量上限（核心约束）

### 4.1 已启用站点与单轮产出上限

名录唯一来源：**`app/services/collection/site_caps.py`**（import 期守卫，见 4.3）。

| 站点 | 代码 | 单轮上限 | 备注 |
|---|---|---|---|
| 人民日报 | `people_daily` | 50 | RSS |
| 新华社 | `xinhua` | 30 | |
| 央视新闻 | `cctv` | 50 | |
| 澎湃新闻 | `thepaper` | 100 | `thepaper.py` 的 `MAX_RESULTS` |
| 微博热搜 | `weibo` | 50 | JS 页面，需 playwright + `playwright install chromium` |
| 百度热搜 | `baidu` | 50 | |
| 知乎热榜 | `zhihu` | 50 | 可由 `collection.result_limit`（**嵌套键**）覆盖；配置读的是**硬编码绝对路径** `/root/apiserver/config/zhihu.yaml`（`zhihu.py:43`），不是相对路径 |
| 36氪 | `tech_36kr` | 50 | RSS |
| 小红书 | `xiaohongshu` | 30 | |

**Σ(单轮) = 460 条**；按每天 2 轮 ⇒ 最坏日 **920** 条。

### 4.2 飞书表容量常量（唯一来源：`app/services/feishu/limits.py`）

| 常量 | 值 | 含义 |
|---|---|---|
| `TABLE_RECORD_LIMIT` | 20,000 | 飞书单表硬上限（错误码 `1254103`） |
| `RETENTION_DAYS` | 25 | 目标保留窗口 |
| `DAILY_BUDGET` | 630 | 规划日量（**均值口径**） |
| `WATERMARK` | 17,000 | 容量水位：写前预检会把表压到这里以下 |
| `WARNING` | 18,500 | 告警线 |

单次写接口上限 **500** 条（错误码 `1254104`）。

### 4.3 三条必须知道的算术事实

1. `Σ(上界) = 460 ≤ WATERMARK = 17,000` —— 单轮必然写得下（`site_caps.py` 的 **G1 守卫**，import 期硬失败）。
2. `460 × 2 = 920 > DAILY_BUDGET = 630`，且 `> 17000 / 25 = 680` —— **「上界口径」装不进日预算**。`DAILY_BUDGET` 是均值口径，两者不可比，因此**不能**把它写成硬断言（否则进程起不来）。`site_caps.py` 的 **G2 守卫**改为把当前最坏上界**冻结**为 920，任何站点上限被调大都会 import 期 raise。
3. `920 × 25 = 23,000 > TABLE_RECORD_LIMIT = 20,000` —— **「最坏情况下 25 天装不下」为真**。实际净日增超过 `17000 / 25 = 680` 时，写前预检会**最旧优先**把表压到水位，保留窗口随之被压缩（且**比 25 天新的记录照删**）。

> 安全底线是 **G1（单轮可写）**，不是「日总账」；手动重跑不在「2 轮/天」之内。
> 详细推导见 `doc/飞书数据清理与历史数据管理.md`。

---

## 五、HTTP 接口（真实全路径，取自 `app/api/v1/api.py` 与各端点模块）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/verify` | 校验 JWT。**不含申请令牌的端点**——令牌只能用 `secret/generate_auth_key.py` 本地生成 |
| POST | `/api/v1/auth/refresh` | 刷新令牌 |
| GET | `/api/v1/collection` | 采集（`site_code` 逗号分隔、`date`、`category`、`keyword`） |
| GET | `/api/v1/collection/sites` | 列出已启用站点 |
| POST | `/api/v1/collection/content/fetch` | 正文按需抓取 |
| POST | `/api/v1/collection/content/backfill` | 正文回填 |
| POST | `/api/v1/selection/selection` | 智能选材 |
| GET | `/api/v1/selection/selection/platforms` | 平台列表 |
| GET | `/api/v1/selection/selection/strategies` | 策略列表 |
| POST | `/api/v1/publication` | 多平台发布 |
| GET | `/api/v1/publication/platforms` | 发布平台列表 |
| GET | `/api/v1/enhanced/collect-and-store` | 采集并直接入库 |
| POST | `/api/v1/enhanced/select-and-store` | 选材并直接入库 |
| POST | `/api/v1/feishu/sync` | 飞书同步 |
| POST | `/api/v1/analysis/collect` | 效果分析采集 |
| GET | `/api/v1/analysis/report/{platform}/{publication_id}` | 效果报告 |
| POST | `/api/v1/analysis/insights/generate` | 深度内容生成 |
| GET | `/api/v1/analysis/insights/preflight` | 深度内容前置检查 |
| POST | `/api/v1/tasks/submit` | 提交 Celery 任务 |
| GET | `/api/v1/tasks/status/{task_id}` | 任务状态 |
| GET | `/api/v1/tasks/metrics` | 任务指标 |

服务级：`GET /`、`GET /health`、`GET /metrics`、`/docs`（Swagger）。

> ⚠️ `/api/v1/selection/selection/...` 的**重复段**是历史遗留（路由前缀 `/selection` + 端点 `/selection`），
> 已有调用方在用，改动需评估兼容性。同理「增强采集」的前缀是 `/enhanced`，不是 `/enhanced-collection`
> （后者只存在于**未被挂载的死代码** `app/api/v1/__init__.py:15`）。
>
> 上表按无尾斜杠书写。其中 `GET /api/v1/collection`（`collection.py:26`）与 `POST /api/v1/publication`
> （`publication.py:26`）的装饰器是 `@router.get("/")` / `@router.post("/")`，**注册路径含尾斜杠**；
> Starlette 默认 `redirect_slashes` 会 307 过去。此行为为**静态推导**，本机两个解释器都未装 fastapi，
> 未能实例化 app 枚举 `app.routes` 实测。

---

## 六、配置与凭据

- **凭据**：`config/credentials.yaml`（真实生产密钥）。已 gitignore，**不得提交**；新增配置只动对应的 `*.example`。
- **配置读取**：统一走 `app/core/config.py` 的 `config_manager` / `settings`：
  - `get_credentials()` → `config/credentials.yaml`
  - `get_config()` → `config/analysis.yaml`（根键 `feature_analysis`）
  - `sites.yaml` 的根键是 `sites`，其 `enabled` **真正决定采集名单**
- **令牌**：两套机制并存，别混：
  - `secret/generate_auth_key.py` 生成**长效** authkey（365 天），记录在 `secret/auth_key.json`，业务接口用 `Authorization: Bearer <authkey>`；
  - `/api/v1/auth/verify` + `/refresh` 签发/刷新**短效** access token（`ACCESS_TOKEN_EXPIRE_MINUTES = 120`）。

---

## 七、测试

约定：`tests/` 下每个文件都是**独立可执行脚本**，**22 个跟踪文件里 0 个 `import pytest`**，直接：

```bash
python tests/<name>.py        # 退出码 0 = 全通过
```

末行打印「结果: N 通过 / M 失败」的只有 **12 / 22** 个。没有该行的 10 个：`test_cctv_collection` /
`test_content_endpoint` / `test_content_extractor` / `test_content_fetcher` / `test_feature_analysis_package` /
`test_feishu_field_plans` / `test_insights_endpoint` / `test_insights_mapping` / `test_llm_client_factory` /
`test_publication_platforms`（其中最后两个文件没有 `__main__` 守卫，靠模块级顺序执行 + 末尾 `sys.exit`）。
**判据一律以退出码为准，不要靠 grep 结果行。**

关键的几套（它们不是「跑一遍看看」，而是**防回归的锁**）：

| 测试 | 锁住什么 |
|---|---|
| `test_write_path_wiring.py` | 三个写入面的 mock 过滤 / 容量预检接线是否还在（模块在、行为被改回去 ⇒ 变红） |
| `test_mock_governance.py` / `test_mock_optin.py` | 动态枚举所有含 `_get_mock_data` 的站点；mock 必须显式 opt-in |
| `test_site_caps_budget.py` | 站点上限名录 + G1/G2 守卫 + 名录闭包 + 接线锁（用变异对照证明有鉴别力） |
| `test_capacity_budget.py` | `limits.py` 的容量不变式；用「复制到临时目录 + 子进程 import」做文本变异 |
| `test_requirements_coverage.py` | 全仓 AST import 扫描 vs `requirements.txt`，0 漏配 |
| `test_thepaper_collection.py` / `test_thepaper_feishu_shape.py` | thepaper 采集与写入形状 |
| `test_target_sites_source_of_truth.py` | `sites.yaml` enabled 名单的单一事实来源 |

**本机（Windows）跑测试的注意事项**：bash coreutils 不可用，请用绝对路径调用解释器；
项目依赖未安装时应使用「依赖桩 + 直接加载真实源码」，不要为跑测试去装全量依赖。

---

## 八、部署

生产 `192.168.3.105`（SSH 端口以运维配置为准），代码在 `/opt/apiserver`。

- ⚠️ **不要在生产执行 `git pull`**：生产的 git 历史与本地不同，且工作区有未提交改动。
- 采用 **scp 直传 + md5 比对**：记录基线 → 备份 → 覆盖 → 双端校验 → 冒烟（`py_compile` + import）。
- **文件清单必须现算**（`git diff --name-status <base> <head>`），不要沿用任何手写清单——
  发布工作区 `.workbuddy/_deploy/` 里有三份互相冲突的旧清单（分别写死 **10 / 43 / 4** 个文件），
  沿用任一份都会**静默少发文件**（旧流程实际丢过 2 个新增文件）。该目录已被 gitignore，不在仓库跟踪范围内。
- 生产**无 systemd 服务**：改代码不需要重启任何进程，下一次 cron 即生效。
- 容器化路径与生产当前形态**不同**，不要混用。`docker-compose.yml` 的 4 个服务是
  `apiserver` / `redis` / `mongodb` / `playwright`；而 `deploy.sh:59` / `:77` 却在检查 `api` 与
  `celery-worker` —— 这两个服务名**在 compose 里并不存在**，即该脚本的健康检查永远不可能通过
  （真 bug，未修）。

运维与排障细节见 `doc/DEPLOY.md`、`doc/DEPLOYMENT.md`、`doc/服务器优化指南.md`。

---

## 九、已知问题与待办（诚实清单）

1. **站点失败会回退到 mock 数据**：产出行带显式标记，**三个写入面都会剔除**
   （`script/collection_pipeline.py:149` `split_write_set`；
   `app/api/v1/endpoints/enhanced_collection.py:74` `build_headline_records`；
   `app/api/v1/endpoints/feishu.py:27` `split_real_and_mock`）。
   **真正的缺口是「写前容量预检」只有一处有**：`collection_pipeline.py:298` `ensure_capacity`，
   另两个写入面（`enhanced_collection.py:103` / `:272`、`POST /api/v1/feishu/sync`）都没有。
   唯一兜底是批写接口内部的 `1254103` 自愈重试（`feishu_service.py:532-546`）。
2. **归档的「搬进 `history_data/`」这一步不在任何调度里**，需要人工执行 `script/manage_history_data.py`。
   导出落点本身已修正为「项目根目录、不依赖 cwd」。
3. **保留窗口不是保证**：见 §4.3 第 3 条；`DAILY_BUDGET` 目前没有任何代码路径强制。
4. **重复实现**：`generate_content_id` 在 `app/utils/id_generator.py:13` 与 `secret/generate_auth_key.py:60` 各有一份。
5. **站点产出为 0 时无法区分「今日无新内容」与「站点静默失败」**。已有**站点级缺口告警**
   （`collection_pipeline.py:113-120`：对「已启用但本次 0 产出」的站点推送企业微信并打印），
   但告警文案**自认不判因**（`:117`「可能是该站未启用/配置缺失/采集为空」），日志层面仍无区分手段。

---

## 十、设计文档索引（`doc/`）

| 文档 | 内容 |
|---|---|
| `doc/API设计文档.md` | HTTP 接口设计 |
| `doc/开发设计.md` / `doc/流程规划.md` / `doc/需求prd.md` | 总体设计（含 2025-11 的早期方案，部分已偏离实现） |
| `doc/飞书多维表格设计文档.md` | 字段规划与表结构 |
| `doc/飞书数据清理与历史数据管理.md` | 容量模型、清理策略、归档链 |
| `doc/飞书用户访问令牌获取指南.md` | 用户 token 获取步骤 |
| `doc/选材引擎规划.md` / `doc/平台差异化布局设计.md` | 选材与平台适配 |
| `doc/hotspot_feature_analysis_design.md` / `doc/ml_training_guide.md` | 特征分析与模型训练 |
| `doc/incremental/` | 增量需求的 PRD / 架构设计 / 类图 / 时序图 |
| `doc/DEPLOY.md` / `doc/DEPLOYMENT.md` / `doc/服务器优化指南.md` | 部署与运维 |
| `doc/生产pip-freeze-openEuler24.03-py311-20260913.txt` | 生产依赖原始快照 |
| `doc/SECURITY.md` | 安全说明 |

---

**修订记录**
- 2026-09-14：按仓库实况重建（原 2025-11-05 设计稿见 `git show f1a5f31:README.md`）。
- 2026-09-14：按 21 项逐条事实核对（`file:line` 级）修正 6 处 —— `/api/v1/feishu/sync` 的 mock 过滤
  （实为**已有**，缺的只是预检）、`docker-compose.yml` 真实服务名与 `deploy.sh` 的不一致、
  zhihu 配置的**硬编码路径 + 嵌套键**、测试「结果行」的适用范围（12/22）、三份旧清单所在目录
  （`.workbuddy/_deploy/`，gitignored）、站点级缺口告警的存在。

如发现本文与代码不符，**以代码为准**，并提交修正。
