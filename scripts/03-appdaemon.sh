#!/usr/bin/env bash
# 03-appdaemon.sh — 安装改过的 appdaemon（修主页键递归崩溃）
# 用法: TV_IP=192.168.x.x bash scripts/03-appdaemon.sh [apk路径]
#
# ⚠️ 这个包是平台签名构建的，只能装在签名匹配的电视上。
#    装不上（INSTALL_FAILED_UPDATE_INCOMPATIBLE）说明签名不对，
#    需要自己用电视的平台密钥重签，见 docs/03-appdaemon.md
set -uo pipefail
cd "$(dirname "$0")"
. ./lib.sh

APK="${1:-../apk/appdaemon-v3.apk}"
check_conn

[ -f "$APK" ] || { c_red "找不到 $APK"; exit 1; }

c_ylw "== 安装改过的 appdaemon =="

OLD_VC=$(adb_ shell "dumpsys package com.stv.appdaemon 2>/dev/null | grep -m1 versionCode" | tr -d '\r' | grep -o '[0-9]*' | head -1)
SYS_VC=$(adb_ shell "pm dump /system/app/AppDaemon.apk 2>/dev/null | grep -m1 versionCode" | tr -d '\r' | grep -o '[0-9]*' | head -1)

c_dim "当前: ${OLD_VC:-未知}   /system: ${SYS_VC:-未知}"
c_dim "新版 versionCode 必须 > /system，否则重启会被压回原版"

install_apk "$APK" || { c_red "安装失败"; exit 1; }

[ "$DRY_RUN" = "1" ] && exit 0

c_dim "== 核对 =="
root_sh "dumpsys package com.stv.appdaemon | grep -E 'versionCode|codePath'" | tail -4

c_dim "== 检查是否还在崩溃 =="
CRASH=$(root_sh "logcat -d | grep -c StackOverflowError" | tail -1 | tr -dc '0-9')
c_dim "StackOverflowError 计数: ${CRASH:-?}（应为 0）"

c_grn "完成。请按主页键验证，然后重启电视再验证一次（重启验证不能省）"
c_dim "回退: adb shell pm uninstall com.stv.appdaemon"
