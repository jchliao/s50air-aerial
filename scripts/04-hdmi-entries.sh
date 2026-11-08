#!/usr/bin/env bash
# 04-hdmi-entries.sh — 安装 HDMI 1/2/3 桌面直达磁贴
# 用法: TV_IP=192.168.x.x bash scripts/04-hdmi-entries.sh
set -uo pipefail
cd "$(dirname "$0")"
. ./lib.sh

check_conn

c_ylw "== HDMI 直达磁贴 =="
c_dim "每个信号源一个独立 APK（Aerial 磁贴按包名去重）"
c_dim "点击后直接切到对应 HDMI，无闪屏"

# 先验证信号源管理器存在
if ! adb_ shell pm list packages 2>/dev/null | grep -q com.stv.signalsourcemanager; then
  c_red "电视上没有 com.stv.signalsourcemanager，这个方案不适用"
  exit 1
fi

for n in 1 2 3; do
  c_dim "-- HDMI $n --"
  install_apk "../apk/hdmi$n.apk" || c_red "hdmi$n 安装失败"
  # 走系统安装器时每次都要人在电视上点确认，装完等一下再投下一个
  [ "$DRY_RUN" = "0" ] && [ "$INSTALL_MODE" = "installer" ] && {
    c_ylw "请在电视上点「安装」后按回车继续"
    read -r _
  }
done

[ "$DRY_RUN" = "1" ] && exit 0

c_dim "== 核对 =="
adb_ shell "pm list packages | grep com.tv.hdmi" | tr -d '\r'

c_grn "完成。打开 Aerial 桌面应该能看到 HDMI 1/2/3 三个磁贴"
c_dim "改成 PS4 等名字：Aerial 控制中心 → 个性化 → 手机扫码 → 主屏幕页改名/换图标"
c_dim "卸载: adb shell pm uninstall com.tv.hdmi1"
