#!/usr/bin/env bash
# fetch-tools.sh — 下载构建 APK 所需的最小工具链（无需 Android SDK）
# 用法: bash source/tools/fetch-tools.sh
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p bin

echo "== 1/3 build-tools（aapt / zipalign）=="
if [ ! -f bin/aapt.exe ] && [ ! -f bin/aapt ]; then
  curl -L -o bt.zip "https://dl.google.com/android/repository/build-tools_r26.0.2-windows.zip"
  unzip -o -q bt.zip "android-8.1.0/aapt.exe" "android-8.1.0/zipalign.exe" "android-8.1.0/lib/apksigner.jar" -d /tmp/bt
  cp /tmp/bt/android-8.1.0/*.exe bin/
  cp -r /tmp/bt/android-8.1.0/lib bin/
  rm -rf /tmp/bt bt.zip
else
  echo "已存在，跳过"
fi

echo "== 2/3 r8（D8 dexer）=="
if [ ! -f bin/r8.jar ]; then
  curl -L -o bin/r8.jar "https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.2.42/r8-8.2.42.jar"
else
  echo "已存在，跳过"
fi

echo "== 3/3 android.jar (API 16，自带 resources.arsc) =="
if [ ! -f bin/android.jar ]; then
  curl -L -o bin/android.jar "https://repo1.maven.org/maven2/com/google/android/android/4.1.1.4/android-4.1.1.4.jar"
else
  echo "已存在，跳过"
fi

echo
echo "完成。还需要 JDK 17（javac）："
echo "  - Windows: https://adoptium.net/temurin/releases/?version=17"
echo "  - Linux:   sudo apt install openjdk-17-jdk"
echo
echo "验证："
echo "  bin/aapt.exe version        # 或 bin/aapt version"
echo "  java -cp bin/r8.jar com.android.tools.r8.D8 --version"
echo
echo "注意：r8.jar 展开后可直接用（不需要 r8 的依赖包）。"
echo "      如果 D8 报缺类，改用完整 r8 发行包或 Android Gradle Plugin 自带的 r8。"
