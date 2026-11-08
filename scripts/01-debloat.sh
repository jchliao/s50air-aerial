#!/usr/bin/env bash
# 01-debloat.sh — 停用广告/上报/内容包
# 用法: TV_IP=192.168.x.x bash scripts/01-debloat.sh [a|b|c|all]
#      DRY_RUN=0 才会真的执行（默认只打印）
set -uo pipefail
cd "$(dirname "$0")"
. ./lib.sh

STAGE="${1:-a}"
check_conn

BATCH_A="com.stv.bootadmanager com.stv.reportlog com.stv.reportService com.stv.stvpush com.stv.feedback"

BATCH_B="com.stv.lap.alitvbuy com.iptv.ylhb com.newtv.sport cn.tvplay.gunworld \
sina.mobile.tianqitongstv com.kuyun.stv.androidtv com.kuyun.common.androidtv \
com.kuyun.identifer com.stv.guider com.stv.calendar com.stv.message \
com.le.lepay.tv com.stv.music com.tvos.store.music com.amap.android.location \
com.letv.leso com.letv.lekids"

BATCH_C="com.stv.litemode com.stv.deskplatform com.stv.net.misc com.letv.android.tv.letvlive \
com.stv.ucenter com.stv.t2.account com.stv.helper.main com.stv.android.videochat \
com.stv.downloads com.kookong.tv.livematch com.letv.combine"

# 白名单：即使误传也不动
NEVER="com.stv.helper.service com.stv.signalsourcemanager com.stv.lekey \
com.stv.commonservice com.stv.filemanager"

case "$STAGE" in
  a) LIST="$BATCH_A"; DESC="A批：广告/上报/推送/反馈（零风险）";;
  b) LIST="$BATCH_B"; DESC="B批：内容/购物/游戏/儿童/天气（低风险）";;
  c) LIST="$BATCH_C"; DESC="C批：系统相关（逐个确认）";;
  all) LIST="$BATCH_A $BATCH_B $BATCH_C"; DESC="全部（A+B+C）";;
  *) c_red "未知批次: $STAGE（可选 a|b|c|all）"; exit 1;;
esac

c_ylw "== $DESC =="
COUNT=0
for p in $LIST; do
  case " $NEVER " in *" $p "*) c_red "跳过（白名单）: $p"; continue;; esac
  COUNT=$((COUNT+1))
done
c_dim "将处理 $COUNT 个包"

if [ "$DRY_RUN" = "1" ]; then
  for p in $LIST; do
    case " $NEVER " in *" $p "*) continue;; esac
    printf "  pm disable-user --user 0 %s\n" "$p"
  done
  c_ylw "（dry-run，加 DRY_RUN=0 真执行）"
  exit 0
fi

# 优先 uid2000，不行走 uid1000
SCRIPT=""
for p in $LIST; do
  case " $NEVER " in *" $p "*) continue;; esac
  SCRIPT="$SCRIPT pm disable-user --user 0 $p 2>&1
echo \"--- $p \$?\""
done

c_dim "执行中（约 10 秒）..."
root_exec <<EOF
$SCRIPT
echo "=== disabled list ==="
pm list packages -d
EOF

c_grn "完成。核对："
c_dim "  adb shell pm list packages -d | grep -c package"
c_dim "恢复：adb shell pm enable <包名>"
