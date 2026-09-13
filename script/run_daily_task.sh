#!/bin/bash
# 每日定时任务执行脚本（迁移后：部署根目录为 /opt/apiserver）
#
# cron（每日 08:00 / 21:00）：
#   0 8  * * * /opt/apiserver/script/run_daily_task.sh
#   0 21 * * * /opt/apiserver/script/run_daily_task.sh
#
# 作用：采集各站点热点 → 写入飞书多维表格 → 导出当日归档 JSON

set -u

APISERVER_HOME="/opt/apiserver"

cd "$APISERVER_HOME" || exit 1
export PYTHONPATH="$APISERVER_HOME:${PYTHONPATH:-}"

mkdir -p "$APISERVER_HOME/logs"

LOG_FILE="$APISERVER_HOME/logs/daily_task_$(date +%Y%m%d).log"

echo "========================================" >> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始执行每日采集任务" >> "$LOG_FILE"

/usr/bin/python3 "$APISERVER_HOME/script/everday_task.py" >> "$LOG_FILE" 2>&1
RC=$?

if [ $RC -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 每日采集任务执行成功" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 每日采集任务执行失败 (exit=$RC)" >> "$LOG_FILE"
fi

exit $RC
