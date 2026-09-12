#!/bin/bash
# 飞书数据定时清理脚本

# 设置环境变量
export PYTHONPATH="/root/apiserver"
cd /root/apiserver

# 日志文件
LOG_FILE="/root/apiserver/logs/cleanup_$(date +%Y%m%d).log"

# 创建日志目录
mkdir -p /root/apiserver/logs

# 执行清理，保留最近90天数据
echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始执行飞书数据清理" >> "$LOG_FILE"
python script/cleanup_feishu_data.py --days 90 --batch-size 500 >> "$LOG_FILE" 2>&1

# 检查执行结果
if [ $? -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务执行成功" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务执行失败" >> "$LOG_FILE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - 清理任务结束" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"