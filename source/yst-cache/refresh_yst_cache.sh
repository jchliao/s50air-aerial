#!/bin/bash
# 一键修复小电视(com.xiaodianshi.tv.yst) 部分图标不显示。
# 原理见 ../../docs/06-vp8x-icon-cache.md：只改 sdcard 上的 Fresco 图片缓存，
# 把 WebP VP8X 扩展容器降级为简单 VP8（带 alpha 的转 RGBA PNG），
# 不碰 APK、不重签、不卸载、不丢登录态，也不给系统打补丁。
#
#   bash refresh_yst_cache.sh             # 拉取 -> 转换 -> 推回（幂等，可反复跑）
#   bash refresh_yst_cache.sh --restore  # 还原成首次备份的原始缓存
#
# 可覆盖的环境变量：
#   TV_IP=192.168.5.9   ADB=adb   PYTHON=python3   FFMPEG=ffmpeg
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
ADB="${ADB:-adb}"
DEV="${TV_IP:-192.168.5.9}:5555"
REMOTE="/sdcard/Android/data/com.xiaodianshi.tv.yst/cache/ImagePipeLine"
export MSYS2_ARG_CONV_EXCL="*"          # Windows MSYS/Git Bash：别改写 /sdcard 路径

"$ADB" connect "$DEV" >/dev/null 2>&1

# 可选：如果有原始缓存的 zip 备份，先解出来做 --restore 源
if [ ! -d tmpimg/pipe.bak ] && [ -f yst-cache-original.zip ]; then
    "$PY" -c "import zipfile; zipfile.ZipFile('yst-cache-original.zip').extractall('tmpimg/pipe.bak')"
    echo "已从 zip 恢复原始备份"
fi

if [ "$1" = "--restore" ]; then
    if [ ! -d tmpimg/pipe.bak ]; then echo "没有原始备份，无法还原"; exit 1; fi
    if [ ! -d tmpimg/pipe ]; then mkdir -p tmpimg/pipe; fi
    echo "=== 还原原始缓存 ==="
    "$PY" patch_yst_cache.py --restore
    "$ADB" -s "$DEV" push tmpimg/pipe/v2.ols100.1 "$REMOTE/" 2>&1 | tail -1
    echo "已还原。"
    exit 0
fi

echo "=== 1/3 拉取电视缓存 ==="
rm -rf tmpimg/pipe
mkdir -p tmpimg
"$ADB" -s "$DEV" pull "$REMOTE" tmpimg/pipe 2>&1 | tail -1

echo "=== 2/3 转换 VP8X -> VP8 / PNG ==="
"$PY" patch_yst_cache.py

echo "=== 3/3 推回电视 ==="
"$ADB" -s "$DEV" push tmpimg/pipe/v2.ols100.1 "$REMOTE/" 2>&1 | tail -1

echo "完成。切走再进小电视（或 am force-stop 后重开 / 重启电视）让 Fresco 重建索引。"
