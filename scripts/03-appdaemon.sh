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

# 版本查询走 uid1000。
# 注意：dumpsys package 会输出两段（/data 覆盖版 + /system 原版），
# 手工取第一条 codePath 才是"当前生效的那个"。
if [ "$DRY_RUN" = "0" ]; then
  VCINFO=$(root_sh "echo -n 'path: '; pm path com.stv.appdaemon; dumpsys package com.stv.appdaemon 2>&1 | grep -m1 versionCode")
  c_dim "当前生效："
  printf '%s\n' "$VCINFO" | grep -vE '^(=== rc|=== done)' | sed 's/^/    /'
  CUR_VC=$(printf '%s' "$VCINFO" | grep -o 'versionCode=[0-9]*' | head -1 | cut -d= -f2)
  if [ -n "$CUR_VC" ] && [ "$CUR_VC" -ge 2019060619 ] 2>/dev/null; then
    c_grn "已安装改过的版本 (versionCode=$CUR_VC)，无需重装"
    exit 0
  fi
fi

c_dim "新版 versionCode 必须 > /system 原版（2019060618），否则重启会被压回原版"
c_dim "（若报 INSTALL_FAILED_UPDATE_INCOMPATIBLE，说明签名不匹配，见 docs/03-appdaemon.md）"

install_apk "$APK" || { c_red "安装失败"; exit 1; }

[ "$DRY_RUN" = "1" ] && exit 0

c_dim "== 核对 =="
root_sh "dumpsys package com.stv.appdaemon | grep -E 'versionCode|codePath'" | tail -4

c_dim "== 检查是否还在崩溃 =="
CRASH=$(root_sh "logcat -d | grep -c StackOverflowError" | tail -1 | tr -dc '0-9')
c_dim "StackOverflowError 计数: ${CRASH:-?}（应为 0）"

c_grn "完成。请按主页键验证，然后重启电视再验证一次（重启验证不能省）"
c_dim "回退: adb shell pm uninstall com.stv.appdaemon"
