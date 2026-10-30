#!/usr/bin/env bash
# 用法：
#   ./launch.sh                      # 挂载并授权整个 $HOME
#   QORG_DATA_ROOTS="$HOME/Pictures:$HOME/Videos" ./launch.sh   # 只授权相册
#   PORT=8081 ./launch.sh            # 换端口
set -euo pipefail
ROOTS="${QORG_DATA_ROOTS:-$HOME}"
IMAGE="${QORG_IMAGE:-quantum-organizer:dev}"
docker run --rm -p "${PORT:-8080}:8080" \
  -v "$HOME:$HOME" \
  -v qorg-state:/state \
  -e QORG_DATA_ROOTS="$ROOTS" \
  "$IMAGE"
