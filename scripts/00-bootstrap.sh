#!/usr/bin/env bash
# 00-bootstrap.sh — 第一阶段：用系统安装器装上 uid1000 通道
#
# 为什么单独一个脚本：
#   这是整个改造里**唯一**需要人在电视上按遥控器的一步。
#   装完之后所有包都走 tvhelper 静默安装（scripts 里的 install_apk 自动处理）。
#
# 用法:
#   TV_IP=192.168.5.9 bash scripts/00-bootstrap.sh path/to/tvhelper.apk
#   默认找 ../apk/tvhelper.apk（不在仓库里，需自己构建，见 source/tvhelper/README.md）
set -uo pipefail
cd "$(dirname "$0")"
. ./lib.sh

APK="${1:-../apk/tvhelper.apk}"

if [ ! -f "$APK" ]; then
  c_red "找不到 $APK"
  cat <<'EOT'

TVHelper 是 uid1000 执行通道，需要自己构建（4.5 KB，源码本仓库已带）：

  cd source/tvhelper
  # 按 README 的四步：javac → d8 → aapt2 → sign_apk.py
  # 构建好后放回 apk/tvhelper.apk，或直接把路径传进来

详见 source/tvhelper/README.md

EOT
  exit 1
fi

check_conn

c_ylw "== 第一阶段：安装 uid1000 通道 =="
c_dim "整个改造里唯一需要遥控器操作的一步"

if adb_ shell pm list packages 2>/dev/null | grep -q "com.tvhelper.root"; then
  c_grn "com.tvhelper.root 已存在，跳过安装"
else
  install_via_installer "$APK" "$REMOTE_DIR/tvhelper.apk" || exit 1

  [ "$DRY_RUN" = "1" ] && exit 0

  c_ylw "请到电视上点「安装」，装完按回车继续核对"
  read -r _
fi

[ "$DRY_RUN" = "1" ] && exit 0

c_dim "== 核对已安装 =="
adb_ shell "pm list packages -f | grep tvhelper" | tr -d '\r' | sed 's/^/    /'

# 注意：不能在这里 dumpsys 查 sharedUser —— uid 2000 没有 DUMP 权限，会返回空，
# 看起来像"签名不对"。真正的判定标准是下面这次实测能不能拿到 uid=1000。

c_dim "== 实测通道是否可用（真正的验收标准）=="
OUT=$(root_sh 'echo alive; id')
printf '%s\n' "$OUT" | grep -vE '^(=== rc|=== done)' | sed 's/^/    /'

if printf '%s' "$OUT" | grep -q "uid=1000"; then
  c_grn "通道打通 ✅ 之后所有安装都会自动走它，不用再碰遥控器"
  c_dim "下一步: DRY_RUN=0 bash scripts/01-debloat.sh all"
else
  c_red "通道没有以 uid 1000 执行"
  c_dim "检查 logcat: adb logcat -d | grep tvhelper"
  exit 1
fi
