#!/bin/bash
# 飞书数据定时清理脚本
#
# cron（每日 02:00）：
#   0 2 * * * /opt/apiserver/script/scheduled_cleanup.sh
#
# 保留策略：飞书表只保留最近 25 天内的数据
# ------------------------------------------------------------------
# 飞书单个数据表硬上限 20,000 条（错误码 1254103），启用 thepaper 站点后本项目
# 采集速率约 630 条/天，因此 25 天 ≈ 15,750 条，落在安全水位线以内
# （WATERMARK = 17,000，见 app/services/feishu/limits.py）。
#
# 两级机制：
#   ① 按时间：删除 RETENTION_DAYS 天前的数据（默认 25 天，取自 limits.RETENTION_DAYS）
#   ② 按容量：若仍高于水位线，从最旧的记录开始删到水位线以内（兜底，防止超限）
#
# ⚠️ 50% 保护闸
# 如果按时间要删掉的记录超过全表一半，cleanup_table 会**拒绝执行时间清理**
# 并告警，只做容量清理——防止"采集长期失败导致全表过期、一次清空"。
# 首次清理历史积压数据时需要人工加 --force 放行，例如：
#   python3 script/cleanup_feishu_data.py --table headlines --dry-run
#   python3 script/cleanup_feishu_data.py --table headlines --force
#
# 注意：20,000 条的表装不下 90 天数据（按 630 条/天 需约 56,700 条），
# 保留窗口请改 limits.RETENTION_DAYS，不要随意调大。
#
# ⚠️ 不要写死部署路径 / 不要用裸 python
# 本脚本用 BASH_SOURCE 自定位根目录，因此 /root/apiserver 与 /opt/apiserver
# 两种部署都能直接跑，不依赖 `ln -s /opt/apiserver /root/apiserver` 这条兼容软链。
# 解释器固定用 python3：openEuler 24.03 默认没有 /usr/bin/python
# （旧机那条 `python` 是由 RPM python-unversioned-command 提供的）。

set -u

# 自动定位部署根目录（本脚本位于 <部署根>/script/ 下）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APISERVER_HOME="$(dirname "$SCRIPT_DIR")"

# 设置环境变量
export PYTHONPATH="$APISERVER_HOME"
cd "$APISERVER_HOME" || exit 1

# 目标表（对应 config/credentials.yaml 中 feishu.tables 的键）
TABLE="headlines"
# 保留天数不再在本脚本写死：cleanup_feishu_data.py 的 --days 默认值
# 直接取自 app/services/feishu/limits.py 的 RETENTION_DAYS（唯一事实来源），
# 因此这里不再传 --days，避免两处数字漂移（历史教训：DAYS=35 与文档不一致）。

# 日志文件
LOG_FILE="$APISERVER_HOME/logs/cleanup_$(date +%Y%m%d).log"

# 创建日志目录
mkdir -p "$APISERVER_HOME/logs"

# 执行清理
echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始执行飞书数据清理 (table=${TABLE}, 保留天数=limits.RETENTION_DAYS(默认), home=${APISERVER_HOME})" >> "$LOG_FILE"
python3 script/cleanup_feishu_data.py --table "$TABLE" --batch-size 500 >> "$LOG_FILE" 2>&1

# 检查执行结果
if [ $? -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务执行成功" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务执行失败" >> "$LOG_FILE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务结束" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"
