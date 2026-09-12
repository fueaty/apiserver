# apiserver 仓库 Commit 有效性审计报告

- 审计对象：`C:\Users\17655\Desktop\apiserver`（Git 仓库，与远程生产目录同源）
- 审计基准：`HEAD = b1a0742e11c446e9a2b945f1ee815bf7829bc836`
- 审计方法：`git log --all --graph`、`git show --stat`、`git diff-tree --name-status`、`git show <sha>:<path>` 逐条核验真实 diff
- 审计日期：2026-09-12
- ⚠️ **历史重写说明**：本报告完成于历史重写**之前**，正文中所有 SHA 均为**重写前**的旧对象。2026-09-12 为抹除泄露的飞书表格标识，仓库做了全历史重写，旧 SHA 已全部失效。**阅读与复现时请配合文末「附录 A：历史重写后的 SHA 映射」。**

---

## 一、结论摘要

原审计给出的「有效 commit 数量 = 2，比例 2/3 = 67%」**高估了真实代码演进密度**。经逐条核对 diff，本报告认为：

**真实有效 commit 净数量为 1 个，占后续候选提交的 1/3（33%）。**

分歧根源在于 `309cf31`（"删除多余文件"）的定性。该提交删除的文件与前一提交 `22ae8bf`（"新建项目"）新增的文件**完全对称**，是一次误提交后的即时回滚，净代码演进为零，不应计入有效。

---

## 二、完整提交清单与判定

仓库完整历史含 4 个非合并提交，无 merge 节点（`git rev-list --no-merges --all --count` = 4）。

| # | SHA | 提交信息 | 日期 | 变更规模 | 判定 |
|---|-----|---------|------|---------|------|
| 1 | `22ae8bf` | 新建项目 | 2025-11-05 15:22:19 | 142 文件 / +20002 | 基线（不计入） |
| 2 | `309cf31` | 删除多余文件 | 2025-11-05 15:41:06 | 10 文件 / -331 | **无效**（对 #1 的回滚） |
| 3 | `6015c34` | docs: 更新README文档为详细系统设计文档 | 2025-11-05 15:55:28 | 1 文件 / +1387 -26 | 无效（纯文档） |
| 4 | `b1a0742` | 同步脚本为最新版本 | 2025-11-08 23:14:44 | 3 文件 / +258 -80 | **有效** |

---

## 三、逐条核验依据

### 3.1 `22ae8bf`「新建项目」— 基线

首次导入，142 个文件、20002 行。作为基线排除，不计入代码演进。此项无争议。

### 3.2 `309cf31`「删除多余文件」— 判定无效

**原判定**：视为"可区分的代码库清理"，计入有效。
**核验结果**：该提交为 `22ae8bf` 的对称回滚，不计入。

`git diff-tree --name-status -M 309cf31` 实际输出：

```
D       .todo
D       =2.0.1
D       =5.0.1
D       =5.3.4
D       compare_zhihu_requests.py
D       cookie.txt.example
R100    hotspot_feature_analysis_design.md -> doc/hotspot_feature_analysis_design.md
D       jsex.py
D       parse_xiaohongshu_mcp.py
D       test_file.txt
```

与 `22ae8bf` 新增内容的字段级对照：

| 文件 | `22ae8bf` | `309cf31` | 关系 |
|------|-----------|-----------|------|
| `parse_xiaohongshu_mcp.py` | A（+121） | D | 加→删 |
| `jsex.py` | A（+87） | D | 加→删 |
| `compare_zhihu_requests.py` | A（+68） | D | 加→删 |
| `test_file.txt` | A（+2） | D | 加→删 |
| `=2.0.1` / `=5.0.1` / `=5.3.4` | A | D | 加→删 |
| `hotspot_feature_analysis_design.md` | A（+575） | R100 → `doc/` | 迁移 |

**三个判定失效点：**

1. **对称性**：`309cf31` 删除的 6 个内容文件，全部是 `22ae8bf` 同一批新增的文件（`A` 对 `D`，无一例外）。这不是独立清理，是逆操作。
2. **时间间隔 19 分钟**：`22ae8bf` 提交于 15:22:19，`309cf31` 提交于 15:41:06，同一作者、同一天连续两次提交。符合"误提交后立即修正"的典型特征。
3. **`=2.0.1`、`=5.0.1`、`=5.3.4` 的文件名**：这是 `pip install xxx > requirements.txt` 漏写重定向符 `>` 产生的垃圾文件（`=2.0.1` 正是 `textual==2.0.1` 这类包名 specifier 的残留）。这证明 `22ae8bf` 的导入本身就不干净，`309cf31` 是在收拾这个烂摊子。

**唯一非回滚的动作为文档迁移**（`hotspot_feature_analysis_design.md` → `doc/`，`R100` 表示 100% 相似度重命名，内容零变更）。这是一次目录整理，不构成代码能力演进。

**结论**：将 `22ae8bf` 排除为基线、却将 `309cf31`（其逆操作）计入有效，存在逻辑不自洽。二者相抵，净演进为零。

### 3.3 `6015c34`「docs: 更新README文档」— 判定无效

`git show --stat 6015c34` 输出仅一项：

```
README.md | 1413 +++++++++++++++++++++++++--------
1 file changed, 1387 insertions(+), 26 deletions(-)
```

单文件、纯 Markdown、无任何源码变更。属文档演进，按审计口径不计入代码演进。**此项与原判定一致，无争议。**

### 3.4 `b1a0742`「同步脚本为最新版本」— 判定有效

`git show --stat b1a0742` 实际输出：

```
script/collection_pipeline.py  | 168 +++++++++++++++++++++++++++---
script/deduplicate_collect.py  | 101 +++++++++++++++++++++++++
scripts/encrypt_credentials.py |  69 -----------------------
3 files changed, 258 insertions(+), 80 deletions(-)
```

**（1）新增去重脚本 — 已核实存在且内容一致**

- 文件当前存在：`script/deduplicate_collect.py`，位于工作区
- `git grep -n "def deduplicate_items" b1a0742 -- script/deduplicate_collect.py` → 命中第 44 行
- 实际实现（冻结版本原文）：

```python
def deduplicate_items(items):
    if not items:
        return [], 0

    # 使用集合来去重，基于标题和URL的组合
    seen = set()
    unique_items = []

    for item in items:
        # 创建一个唯一标识符，基于标题和URL
        # 有些项目可能没有URL字段，所以我们使用title作为备选
        title = item.get('title', '')
        url = item.get('url', '')

        # 如果title不存在，则跳过这个项目
        if not title:
            continue

        # 创建唯一键
        key = f"{title}:{url}" if url else title

        if key not in seen:
            seen.add(key)
            unique_items.append(item)
```

与原审计引文逐字一致。去重键为 `title:url` 组合，无 url 时退化为 title，无 title 则跳过。

**（2）采集流水线增强 — 已核实**

`script/collection_pipeline.py` 增 157 行、删 11 行（文件级 stat 为 +168/-80，含上下文行）。新增内容要点：

- 新增导入：`from datetime import datetime`、`import httpx`、`from collections import defaultdict`
- 新增存量记录读取逻辑：`all_existing_records` 收集 + `今日已存在 N 条记录` 输出
- 去重策略：代码注释明确为「根据项目规范中的第 19 条'数据写入去重规范'，采用'先删除后插入'策略处理重复数据」

**（3）删除过时辅助代码 — 已核实**

`scripts/encrypt_credentials.py` 被整体删除（-69 行）。

**（4）生产环境一致性 — 已核实**

远程生产目录 `script/collection_pipeline.py` 的 MD5 为 `4dd50ab64d427a1629be9d2d4e5a58a5`，与本地工作区该文件 MD5 **完全一致**。该改动已在生产生效。

**结论**：该提交同时完成「清理过时辅助代码」与「为采集流程加入去重与更新逻辑」两个实质动作，构成真实且可区分的代码演进，计入有效。

---

## 四、比例口径对照

| 口径 | 分子 | 分母 | 比例 | 说明 |
|------|------|------|------|------|
| 原审计口径 | 2 | 3 | **67%** | 将 `309cf31` 计为有效清理 |
| 全量口径 | 2 | 4 | **50%** | 不排除基线提交 |
| **本报告口径** | **1** | **3** | **33%** | 剔除 `309cf31` 回滚后仅剩 `b1a0742` |

**采用 33% 的理由**：`22ae8bf` 作为初始导入被排除是合理的（符合"预处理所指的 3 个候选后续提交"），但 `309cf31` 是 `22ae8bf` 的逆操作，二者的净效果相抵为零。若承认前者为基线，就应同样承认后者为"撤销基线中的误提交"，而非独立演进。

---

## 五、仓库实际演进轨迹

本仓库真实的能力变化只有一条主线：

```
首次导入（含误加的垃圾文件与临时脚本）
    ↓
撤回误提交（恢复干净状态）
    ↓
扩写 README 为系统设计文档（文档层）
    ↓
【唯一实质代码演进】增强采集流水线 + 新增去重脚本
```

真正的代码能力增量集中在 `b1a0742` 一个提交，体现为采集流程的数据去重与更新逻辑。

---

## 六、附带发现

1. **`22ae8bf` 的导入不干净**：`=2.0.1`、`=5.0.1`、`=5.3.4` 三处 pip 重定向失误残留文件进入了首次提交，建议后续提交前检查工作区，避免同类问题。
2. **分支命名不一致**：远程本地分支为 `master`，本地为 `main`，但均跟踪 `origin/main`，`git rev-list --left-right --count master...origin/main` = `0 0`，无分叉。
3. **`b1a0742` 的提交信息不够达意**：「同步脚本为最新版本」未体现"新增去重功能"这一核心变更，从提交信息无法判断该提交包含实质代码演进。

---

*本报告所有数据均来自 Git 对象库直接读取，可通过报告中的 SHA 与命令复现。*

> ⚠️ 由于 2026-09-12 的全历史重写，正文中的**旧 SHA 已不可解析**，复现请使用附录 A 的新 SHA。

---

## 附录 A：历史重写后的 SHA 映射（2026-09-12 追加）

为避免泄露的飞书表格标识随历史外传，仓库于 2026-09-12 执行了**全历史重写**：所有提交经 `git commit-tree` 重新生成，含标识的 4 个文件（README.md、feishu_data_loader.py、doc/hotspot_feature_analysis_design.md、doc/开发设计.md）被替换为占位符，随后以 `git clone --no-local --bare` 生成全新对象库并整体换入。**旧 SHA 已全部无法解析。**

| 报告正文中的旧 SHA | 重写后的新 SHA | 提交信息 | 判定（不变） |
|---|---|---|---|
| `22ae8bf` | `2902b1c` | 新建项目 | 基线（不计入） |
| `309cf31` | `20ea9de` | 删除多余文件 | **无效**（对基线的回滚） |
| `6015c34` | `f1a5f31` | docs: 更新README文档为详细系统设计文档 | 无效（纯文档） |
| `b1a0742` | `c487174` | 同步脚本为最新版本 | **有效** |
| `a528f2a`（本报告写就后才产生） | `7667b0e` | feat: 合并远程飞书数据清理与历史数据管理功能 | 另行提交，不参与口径计算 |
| （重写后新增） | `9247dc6` | feat: 新增澎湃新闻采集、commit 有效性审计报告并脱敏飞书标识 | 另行提交，不参与口径计算 |

复现示例（请用新 SHA）：

```bash
git diff-tree --name-status -M 20ea9de                          # 原 309cf31
git show --stat c487174                                         # 原 b1a0742
git grep -n "def deduplicate_items" c487174 -- script/deduplicate_collect.py
git show --stat f1a5f31                                         # 原 6015c34
```

**重写对审计结论的影响：无。** 判定依据的是各提交的**内容差异**（新增/删除的文件、行数、`A→D` 对称性），而重写只替换了 4 个文档与死代码文件中的飞书标识，未改动任何提交的变更范围、文件结构或提交顺序，故「有效 commit 净数量 = 1，占比 1/3 = 33%」的结论保持不变。

**重写过程中同时确认的两点：**

1. 被替换的 4 个文件中，3 个为纯文档（README.md、两份设计文档），1 个为死代码 —— `app/services/analysis/feature_analysis/feishu_data_loader.py` 调用了项目中并不存在的 `config_manager.get_config()`，实例化即 `AttributeError`，从未参与运行。**故本次脱敏对仓库功能零影响。**
2. 真实运行时凭据存放于 `config/credentials.yaml`（已被 `.gitignore` 忽略，历史中从未提交），**全程未被改动**。
