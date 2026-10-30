#!/usr/bin/env bash
# quantum-organizer 桌面双击入口（同一份脚本也可命令行驱动）
#
#   双击（无参数）: 未运行 -> 预检 -> 起容器 -> 等就绪 -> 开浏览器 -> 跟随日志
#                   已运行 -> 菜单（打开/跟随日志/最近日志/重启/停止/退出）
#   命令行: desktop-launch.sh [start|stop|restart|status|logs [n]|open]
#   ENV: PORT / QORG_DATA_ROOTS / QORG_IMAGE / QORG_STATE_VOLUME / NO_BROWSER=1 / NO_FOLLOW=1
set -uo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="qorg-ui"
IMAGE="${QORG_IMAGE:-quantum-organizer:dev}"
PORT="${PORT:-8080}"
URL="http://localhost:$PORT"
# 容器挂整个 $HOME，默认也授权整个 $HOME；想收紧就 QORG_DATA_ROOTS="$HOME/Pictures:$HOME/Videos"
ROOTS="${QORG_DATA_ROOTS:-$HOME}"
STATE_VOLUME="${QORG_STATE_VOLUME:-qorg-state}"

LOG_DIR="$PROJECT/logs"; LOG="$LOG_DIR/desktop-launch.log"
mkdir -p "$LOG_DIR"

# GUI 启动的 PATH 极简，补齐常用目录
export PATH="/home/lyon/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_OK=''; C_WARN=''; C_ERR=''; C_DIM=''; C_RST=''
fi
say()  { printf '%s[%s]%s %s\n' "$C_OK"   "$(date +%H:%M:%S)" "$C_RST" "$*" | tee -a "$LOG"; }
warn() { printf '%s[%s] 警告%s %s\n' "$C_WARN" "$(date +%H:%M:%S)" "$C_RST" "$*" | tee -a "$LOG"; }
err()  { printf '%s[%s] 错误%s %s\n' "$C_ERR"  "$(date +%H:%M:%S)" "$C_RST" "$*" | tee -a "$LOG"; }

pause_hold() { [[ -t 0 ]] || return 0; echo; read -r -p "按回车关闭窗口…" _ || true; }

ui_running()     { docker ps --filter "name=^${CONTAINER}$" --format '{{.Status}}' 2>/dev/null | grep -q Up; }
ui_status()      { docker ps -a --filter "name=^${CONTAINER}$" --format '{{.Status}}' 2>/dev/null; }
health_ok()      { curl -fsS -o /dev/null --max-time 2 "$URL/healthz" 2>/dev/null; }
port_owner()     { ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $NF}' | head -1; }
port_listening() { ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$"' | grep -q .; }

preflight() {
  command -v docker >/dev/null 2>&1 || { err "找不到 docker"; return 1; }
  timeout 8 docker info >/dev/null 2>&1 || { err "Docker 没在跑。修复: sudo systemctl start docker"; return 1; }
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    err "缺镜像 $IMAGE"
    err "构建（本机代理失效时要清空代理参数）:"
    err "  cd $PROJECT && docker build --network=host \\"
    err "    --build-arg HTTP_PROXY= --build-arg HTTPS_PROXY= \\"
    err "    --build-arg http_proxy= --build-arg https_proxy= --build-arg NO_PROXY='*' \\"
    err "    -t $IMAGE ."
    return 1
  fi
  # 端口冲突看监听，不看 HTTP：别的服务也会回 200
  if ! ui_running && port_listening; then
    local owner; owner="$(port_owner)"
    err "端口 $PORT 已被占用${owner:+: $owner}"
    err "先停掉占用者，或换端口: PORT=$((PORT + 1)) $0 start"
    return 1
  fi
  local avail; avail=$(df -Pm "$PROJECT" | awk 'NR==2{print $4}')
  (( avail > 500 )) || warn "分区剩余 ${avail}MB，整理大目录时状态库可能写满"
  return 0
}

wait_ready() {
  local i st
  for i in $(seq 1 "${1:-90}"); do
    health_ok && { say "服务就绪: $URL（${i}s）"; return 0; }
    st="$(ui_status)"
    [[ "$st" == *Up* ]] || { err "容器启动后退出（$st）"; docker logs "$CONTAINER" 2>&1 | tail -25; return 1; }
    sleep 1
  done
  err "等待 ${1:-90}s 仍未就绪"; docker logs "$CONTAINER" 2>&1 | tail -25; return 1
}

open_browser() {
  [[ "${NO_BROWSER:-0}" == "1" ]] && { say "跳过浏览器（NO_BROWSER=1）→ $URL"; return 0; }
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 & sleep 0.3; say "已请求打开浏览器 → $URL"
  else
    warn "找不到 xdg-open，请手动打开 $URL"
  fi
}

follow_logs() {
  [[ "${1:-follow}" == "tail" ]] && { docker logs --tail "${2:-60}" "$CONTAINER" 2>&1; return 0; }
  say "跟随容器日志（Ctrl+C 只停跟随；停止服务用菜单 s 或 $0 stop）"
  docker logs -f --tail 30 "$CONTAINER" 2>&1 | grep -v -E 'GET /(healthz|assets|favicon)'
}

do_start() {
  preflight || { pause_hold; return 1; }
  ui_running && { say "已在运行（$(ui_status)）"; health_ok && say "地址: $URL"; return 0; }
  say "启动容器 $CONTAINER（镜像 $IMAGE，端口 $PORT，授权 $ROOTS）…"
  if ! docker run -d --rm --name "$CONTAINER" \
        -p "$PORT:8080" \
        -v "$HOME:$HOME" \
        -v "$STATE_VOLUME:/state" \
        -e QORG_STATE_DIR=/state \
        -e QORG_DATA_ROOTS="$ROOTS" \
        "$IMAGE" >>"$LOG" 2>&1; then
    err "docker run 失败:"; tail -15 "$LOG"; err "完整日志: $LOG"; pause_hold; return 1
  fi
  wait_ready 90 || { pause_hold; return 1; }
  open_browser
}

do_stop() {
  ui_running || { say "未在运行"; return 0; }
  say "停止…"
  docker stop "$CONTAINER" >>"$LOG" 2>&1
  ui_running && { err "停止失败: $(ui_status)"; pause_hold; return 1; }
  say "已停止"
}

do_restart() { do_stop && { sleep 1; do_start; }; }

menu() {
  echo; say "已在运行（$(ui_status)）→ $URL"
  printf '%s\n' " ${C_DIM}选择操作（15 秒无输入默认打开浏览器）:${C_RST}" \
    "   [o] 打开浏览器   [f] 跟随日志   [l] 最近日志   [r] 重启   [s] 停止   [q] 退出"
  local ans=''; read -r -t 15 -p "  > " ans || ans='o'
  case "${ans:-o}" in
    o|O) open_browser ;; f|F) follow_logs follow ;; l|L) follow_logs tail 80 ;;
    r|R) do_restart ;; s|S) do_stop ;; q|Q) return 0 ;; *) open_browser ;;
  esac
}

case "${1:-}" in
  start)   do_start || exit 1
           [[ "${NO_FOLLOW:-0}" == "1" ]] || { [[ -t 0 ]] && follow_logs; } ;;
  stop)    do_stop || exit 1 ;;
  restart) do_restart || exit 1
           [[ "${NO_FOLLOW:-0}" == "1" ]] || { [[ -t 0 ]] && follow_logs; } ;;
  status)  echo "容器: $(ui_status || echo 未创建)"; echo "HTTP: $(health_ok && echo 200 || echo 不可达)  $URL"
           echo "镜像: $IMAGE  端口: $PORT  授权: $ROOTS"; echo "日志: $LOG" ;;
  logs)    shift; follow_logs tail "${1:-60}" ;;
  open)    open_browser ;;
  *)
    say "桌面入口：项目=$PROJECT 容器=$CONTAINER 端口=$PORT"
    if ui_running; then menu; else
      do_start || exit 1
      [[ "${NO_FOLLOW:-0}" == "1" ]] || { [[ -t 0 ]] && follow_logs; }
    fi ;;
esac
