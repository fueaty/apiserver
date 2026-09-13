#!/usr/bin/env bash
# script/verify_run.sh
# ---------------------------------------------------------------------------
# 把「运行输出重定向到服务端日志」从**操作者纪律**变成**机器保证**。
#
# 背景：7717f24 那轮端到端验证因「只在终端看、没有重定向」被 QA 判为证据不合规
# （NO_VERIFY_LOG）。修一个流程不能靠人的自觉 —— 本脚本固定把采集流水线的
# stdout+stderr 落到 logs/verify_<时间戳>.log，并把该路径打到 stdout，
# 供验证者事后读取（同时性 + 验证者可读 + 编码完好 三条件）。
#
# 用法（生产机 /opt/apiserver）：
#   bash script/verify_run.sh
#   → 打印 VERIFY_LOG=/opt/apiserver/logs/verify_YYYYmmdd_HHMMSS.log
#            VERIFY_RC=<采集流水线退出码>
#   → 退出码 = 采集流水线退出码（0=成功）
#
# 本脚本自身只做「定位 + 重定向 + 报路径」，**不改变任何采集逻辑**。
# ---------------------------------------------------------------------------
set -u

APP_ROOT="/opt/apiserver"
cd "${APP_ROOT}" || { echo "无法进入 ${APP_ROOT}" >&2; exit 2; }

mkdir -p logs

TS="$(date +%Y%m%d_%H%M%S)"
LOG="logs/verify_${TS}.log"

# 固定解释器(/usr/bin/python3)与 PYTHONPATH，规避 PATH / 多解释器歧义；
# 运行前已 cd 到 APP_ROOT，故流水线内的 sys.path.append("..") 亦无害。
PYTHONPATH="${APP_ROOT}" /usr/bin/python3 script/collection_pipeline.py > "${LOG}" 2>&1
rc=$?

# 打印绝对路径与退出码（供操作者/CI 直接引用；验证者据此读文件）
echo "VERIFY_LOG=${APP_ROOT}/${LOG}"
echo "VERIFY_RC=${rc}"

exit "${rc}"
