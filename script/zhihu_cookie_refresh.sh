#!/bin/bash
# 知乎 Cookie 定时续期脚本（免人工）
#
# cron（建议每日 06:00，赶在采集任务之前）：
#   0 6 * * * /opt/apiserver/script/zhihu_cookie_refresh.sh
#
# 背景：知乎热榜 API GET /api/v3/feed/topstory/hot-lists/total **必须带登录态**，没有匿名通道
# （无凭证 → 401 code=101；cookie 过期 → 401 code=100 ERR_LOGIN_TICKET_EXPIRED）。
# zhihu.py 只读 config/zhihu.yaml 的 `cookie.auth` 一个通道，该值过期后 zhihu 站点会连续
# 0 条入库且不报错。本脚本用无头 playwright 复用 runtime/zhihu_profile 持久化 profile 续期，
# 且**只在序列化后的 cookie 真的变化时才改写** cookie.auth 那一行。
#
# profile 失效（refresh 拿不到有效 z_c0）时，zhihu_cookie_tool.py 会走 --check 的告警路径
# 推送企业微信，提示人工执行一次扫码：
#   python3 script/zhihu_cookie_tool.py --login
# 扫码后 profile 重新可用，后续 cron 又会自动续期。
#
# ⚠️ 不要写死部署路径 / 不要用裸 python
# 本脚本用 BASH_SOURCE 自定位根目录，因此 /root/apiserver 与 /opt/apiserver
# 两种部署都能直接跑，不依赖 `ln -s /opt/apiserver /root/apiserver` 这条兼容软链。
# 解释器固定用 python3：openEuler 24.03 默认没有 /usr/bin/python。
#
# 注意：runtime/ 与 config/zhihu.yaml 都含实时凭证，二者均已在 .gitignore 中忽略。

set -u

# 自动定位部署根目录（本脚本位于 <部署根>/script/ 下）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APISERVER_HOME="$(dirname "$SCRIPT_DIR")"

# 设置环境变量
export PYTHONPATH="$APISERVER_HOME"
cd "$APISERVER_HOME" || exit 1

# 日志文件
LOG_FILE="$APISERVER_HOME/logs/zhihu_cookie_$(date +%Y%m%d).log"

# 创建日志目录
mkdir -p "$APISERVER_HOME/logs"

# 执行续期（rc 契约见 zhihu_cookie_tool.py 头部：
#   0=成功 / 2=认证仍失败（需人工 --login）/ 3=传输失败、任何其它非 200 状态
#   （403/429 风控、500、302…）、响应体无法解析、状态文件不可用、
#   **浏览器/运行环境不可用（playwright 缺失、chromium 装坏、驱动启动失败）**）
echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始知乎 cookie 续期 (home=${APISERVER_HOME})" >> "$LOG_FILE"
python3 script/zhihu_cookie_tool.py --refresh >> "$LOG_FILE" 2>&1
RC=$?

if [ $RC -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 续期成功 (rc=0)" >> "$LOG_FILE"
elif [ $RC -eq 2 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 续期失败 (rc=2)：凭证仍不可用，需要人工执行 --login 扫码" >> "$LOG_FILE"
else
    # ⚠️ 浏览器/运行环境不可用也落在这里（playwright 缺失、chromium 装坏、驱动启动失败）：
    #    此时工具仍会就地跑 check()，凭证失效会被升级成 rc=2 + 企微告警；rc=3 说明浏览器
    #    坏了但凭证暂时还行 —— 必须去查运行环境，否则 cookie 一过期就直接断流。
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 续期异常 (rc=$RC)：查日志确认是风控(403/429)/传输/状态文件问题/浏览器或运行环境不可用（playwright 缺失、chromium 装坏、驱动启动失败）" >> "$LOG_FILE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - 任务结束" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"
