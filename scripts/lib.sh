#!/usr/bin/env bash
# 公共函数库：所有脚本 source 它
# 用法: . "$(dirname "$0")/lib.sh"

set -uo pipefail

TV_IP="${TV_IP:-}"
DRY_RUN="${DRY_RUN:-1}"      # 默认 dry-run，必须显式 DRY_RUN=0 才真执行
REMOTE_DIR="/sdcard/Download"
ROOT_LOG="$REMOTE_DIR/root.log"

c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_grn()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_ylw()   { printf '\033[33m%s\033[0m\n' "$*"; }
c_dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

need_ip() {
  [ -n "$TV_IP" ] || { c_red "缺少电视 IP。用法: TV_IP=192.168.x.x bash $0"; exit 1; }
}

adb_() {
  # 每次调用前 connect（乐视 adb server 会掉）
  MSYS2_ARG_CONV_EXCL="*" adb connect "$TV_IP:5555" >/dev/null 2>&1
  MSYS2_ARG_CONV_EXCL="*" adb "$@"
}

check_conn() {
  need_ip
  local st
  st=$(adb_ devices | grep -c "$TV_IP:5555[[:space:]]*device")
  if [ "$st" -eq 0 ]; then
    c_red "无法连接 $TV_IP:5555"
    c_dim "排查：电视是否开机 / 是否同网段 / ADB 是否开启（乐视：设置→关于→连点版本号）"
    exit 1
  fi
  c_grn "已连接 $TV_IP"
}

# 以 uid1000 执行远程脚本（内容从 stdin 读）
# 用法: root_exec <<'EOF' ... EOF
root_exec() {
  local script; script=$(cat)
  if [ "$DRY_RUN" = "1" ]; then
    c_ylw "[dry-run] 将以 uid1000 执行："
    printf '%s\n' "$script" | sed 's/^/    /'
    return 0
  fi
  printf 'rm -f %s\n%s\n' "$ROOT_LOG" "$script" > /tmp/_root.sh
  adb_ push /tmp/_root.sh "$REMOTE_DIR/root.sh" >/dev/null || return 1
  adb_ shell "am startservice --user 0 -n com.tvhelper.root/.Shell" >/dev/null 2>&1
  sleep "${ROOT_WAIT:-8}"
  adb_ shell "cat $ROOT_LOG"
}

# 单条命令走 uid1000
root_sh() { printf '%s\n' "$*" | root_exec; }

# 检查是否有 uid1000 通道
have_channel() {
  adb_ shell pm list packages 2>/dev/null | grep -q "com.tvhelper.root"
}

# 安装 APK（自动选路径）
install_apk() {
  local apk="$1"
  [ -f "$apk" ] || { c_red "找不到 $apk"; return 1; }
  if [ "$DRY_RUN" = "1" ]; then
    c_ylw "[dry-run] 安装 $apk"
    return 0
  fi
  c_dim "推送 $apk ..."
  adb_ push "$apk" "$REMOTE_DIR/_install.apk" >/dev/null || return 1
  # 先试 uid2000，失败再走 uid1000
  if adb_ shell "pm install -r $REMOTE_DIR/_install.apk" 2>&1 | grep -q "Success"; then
    c_grn "安装成功 (uid2000)"
  elif have_channel; then
    c_dim "uid2000 失败，走 uid1000 通道 ..."
    root_sh "pm install -r $REMOTE_DIR/_install.apk" | grep -E "Success|Failure|EXIT"
  else
    c_red "安装失败，且没有 uid1000 通道"
    return 1
  fi
}

confirm() {
  if [ "$DRY_RUN" = "1" ]; then
    c_ylw "（当前是 dry-run，加 DRY_RUN=0 才会真的执行）"
    return 1
  fi
  c_ylw "$1"
  read -r -p "继续? [y/N] " ans
  [ "$ans" = "y" ] || { c_dim "已取消"; exit 0; }
}
