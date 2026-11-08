#!/usr/bin/env bash
# 99-restore.sh — 恢复原状
# 用法: TV_IP=192.168.x.x bash scripts/99-restore.sh [选项]
#   --keep-aerial    保留 Aerial，只恢复系统应用
#   --only-appdaemon 只回退 appdaemon
#   --only-ssm       只回退信号源管理器
set -uo pipefail
cd "$(dirname "$0")"
. ./lib.sh

KEEP_AERIAL=0
ONLY=""
for a in "$@"; do
  case "$a" in
    --keep-aerial) KEEP_AERIAL=1;;
    --only-appdaemon) ONLY="appdaemon";;
    --only-ssm) ONLY="ssm";;
  esac
done

check_conn

if [ "$ONLY" = "appdaemon" ]; then
  c_ylw "== 只回退 appdaemon =="
  [ "$DRY_RUN" = "1" ] && { echo "  pm uninstall com.stv.appdaemon"; exit 0; }
  root_sh "pm uninstall com.stv.appdaemon" | grep -E "Success|Failure"
  c_grn "已回退到 /system 原版（无需重启）"
  exit 0
fi

if [ "$ONLY" = "ssm" ]; then
  c_ylw "== 只回退信号源管理器 =="
  [ "$DRY_RUN" = "1" ] && { echo "  pm uninstall com.stv.signalsourcemanager"; exit 0; }
  root_sh "pm uninstall com.stv.signalsourcemanager" | grep -E "Success|Failure"
  exit 0
fi

c_ylw "== 恢复原状 =="
c_dim "1. 启用所有被停用的包"
c_dim "2. 卸下覆盖的 appdaemon / ssm（自动回退到 /system 原版）"
[ "$KEEP_AERIAL" = "0" ] && c_dim "3. 卸载 Aerial 和 HDMI 入口"

if [ "$DRY_RUN" = "1" ]; then
  c_ylw "（dry-run，加 DRY_RUN=0 真执行）"
  exit 0
fi

confirm "即将恢复系统应用，桌面会变回乐视原桌面。继续？"

c_dim "-- 启用被停用的包 --"
root_exec <<'EOF'
for p in $(pm list packages -d | sed 's/package://'); do
  pm enable $p 2>&1
  echo "enabled $p"
done
EOF

c_dim "-- 卸载 appdaemon 覆盖版 --"
root_sh "pm uninstall com.stv.appdaemon" | grep -E "Success|Failure"

c_dim "-- 卸载 ssm 覆盖版 --"
root_sh "pm uninstall com.stv.signalsourcemanager" | grep -E "Success|Failure"

if [ "$KEEP_AERIAL" = "0" ]; then
  c_dim "-- 卸载 Aerial 与 HDMI 入口 --"
  root_sh "pm uninstall app.orchard.tv.lite; pm uninstall com.tv.hdmi1; pm uninstall com.tv.hdmi2; pm uninstall com.tv.hdmi3" | grep -E "Success|Failure"
fi

c_grn "完成。建议重启电视使状态完全恢复"
c_dim "adb reboot"
