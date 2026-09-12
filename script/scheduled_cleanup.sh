#!/bin/bash
# 飞书数据定时清理脚本
#
# cron（每日 02:00）：
#   0 2 * * * /root/apiserver/script/scheduled_cleanup.sh
#
# 保留策略：飞书表只保留最近 35 天内的数据
# ------------------------------------------------------------------
# 飞书单个数据表硬上限 20,000 条（错误码 1254103），本项目采集速率约
# 400 条/天，因此 35 天 ≈ 14,000 条，正好等于安全水位线
# （WATERMARK = 14,000，见 app/services/feishu/limits.py）。
#
# 两级机制：
#   ① 按时间：删除 RETENTION_DAYS 天前的数据（下面的 DAYS=35）
#   ② 按容量：若仍高于水位线，从最旧的记录开始删到水位线以内（兜底，防止超限）
#
# ⚠️ 50% 保护闸
# 如果按时间要删掉的记录超过全表一半，cleanup_table 会**拒绝执行时间清理**
# 并告警，只做容量清理——防止"采集长期失败导致全表过期、一次清空"。
# 首次清理历史积压数据时需要人工加 --force 放行，例如：
#   python script/cleanup_feishu_data.py --table headlines --days 35 --dry-run
#   python script/cleanup_feishu_data.py --table headlines --days 35 --force
#
# 注意：20,000 条的表装不下 90 天数据（需约 36,000 条），
# 所以保留天数不要随意调大。

set -u

# 设置环境变量
export PYTHONPATH="/root/apiserver"
cd /root/apiserver || exit 1

# 目标表（对应 config/credentials.yaml 中 feishu.tables 的键）
TABLE="headlines"
# 保留天数
DAYS=35

# 日志文件
LOG_FILE="/root/apiserver/logs/cleanup_$(date +%Y%m%d).log"

# 创建日志目录
mkdir -p /root/apiserver/logs

# 执行清理
echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始执行飞书数据清理 (table=${TABLE}, 保留 ${DAYS} 天)" >> "$LOG_FILE"
python script/cleanup_feishu_data.py --table "$TABLE" --days "$DAYS" --batch-size 500 >> "$LOG_FILE" 2>&1

# 检查执行结果
if [ $? -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务执行成功" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务执行失败" >> "$LOG_FILE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务结束" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"
