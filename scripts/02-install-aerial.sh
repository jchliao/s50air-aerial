#!/usr/bin/env bash
# 02-install-aerial.sh — 安装 Aerial Lite 并做官方后两步
# 用法: TV_IP=192.168.x.x bash scripts/02-install-aerial.sh [apk路径]
set -uo pipefail
cd "$(dirname "$0")"
. ./lib.sh

APK="${1:-../apk/aerial-lite.apk}"
check_conn

[ -f "$APK" ] || { c_red "找不到 $APK"; exit 1; }

c_ylw "== 安装 Aerial Lite =="
c_dim "$APK"
c_dim "$(aapt_path 2>/dev/null || true)"

# 版本号对比
if command -v aapt >/dev/null 2>&1; then
  c_dim "本地: $(aapt dump badging "$APK" 2>/dev/null | head -1)"
fi
CUR=$(adb_ shell "dumpsys package app.orchard.tv.lite 2>/dev/null | grep -m1 versionName" | tr -d '\r')
[ -n "$CUR" ] && c_dim "电视现有: $CUR" || c_dim "电视未安装 Aerial"

install_apk "$APK" || exit 1

[ "$DRY_RUN" = "1" ] && exit 0

c_dim "== 授权 WRITE_SECURE_SETTINGS（亮度调节用）=="
root_sh "pm grant app.orchard.tv.lite android.permission.WRITE_SECURE_SETTINGS" | tail -3

c_dim "== 启动 Aerial 桌面 =="
adb_ shell "am start -n app.orchard.tv.lite/.HomeActivity" 2>&1 | tail -2

c_grn "完成。下一步："
c_dim "  按遥控器主页键，看是否回到 Aerial"
c_dim "  - 弹出「使用哪个应用」→ 选 Aerial + 始终 → 结束"
c_dim "  - 回到乐视桌面 / 黑屏 → 需要 bash scripts/03-appdaemon.sh"
