#!/usr/bin/env python3
"""Fix mangoTV home-page white stair-block icon by swapping the cloud
navigation config's channelIcon (alpha-only white stub) to the already-good
imgFocus URL. Only the sdcard okhttp cache body is touched; journal/.0/APK/system
are untouched. Length is preserved so the DiskLruCache CLEAN record stays valid.

  python apply_nav_fix.py            # apply
  python apply_nav_fix.py --restore  # restore original
  python apply_nav_fix.py --check    # verify current state
"""
import subprocess, gzip, hashlib, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
ADB=str(ROOT/'aerial-tools'/'platform-tools'/'adb.exe'); DEV='192.168.5.9:5555'
HERE=Path(__file__).resolve().parent
CURRENT=Path(tempfile.gettempdir())/'_mango_nav_current.1'
K='5fc2131bc283c9aa311b02961f68bdeb'
B='/sdcard/Android/data/com.starcor.mango/cache/okttp'
REMOTE=f'{B}/{K}.1'
TMP='/sdcard/Download/_mango_nav_fixed.1'
ORIG=HERE/'original-cache-body.gz'; FIX=HERE/'fixed-cache-body.gz'
OLD='0f9da23663f3461bb7915ddc4f90b480_5993.png'
NEW='db8667b31d874c3c9f5d728954eb96da_4398.png'

def adb(*a):
    return subprocess.run([ADB,'-s',DEV,*a],capture_output=True,text=True,errors='replace')

def pull_current():
    adb('pull',REMOTE,str(CURRENT))
    return CURRENT.read_bytes()

def report(tag,b):
    try: t=gzip.decompress(b).decode('utf-8')
    except Exception as e: print(tag,'DECOMPRESS FAIL',e); return
    print(f'{tag}: bytes={len(b)} sha256={hashlib.sha256(b).hexdigest()[:16]} '
          f'json={len(t)}B channelIcon=imgFocus:{t.count(NEW)} stub:{t.count(OLD)}')

subprocess.run([ADB,'connect',DEV],capture_output=True)
mode=sys.argv[1] if len(sys.argv)>1 else 'apply'
if mode=='--check':
    report('CURRENT',pull_current()); sys.exit(0)
src = ORIG if mode=='--restore' else FIX
print('source:',src.name, src.stat().st_size,'bytes')
report('SOURCE',src.read_bytes())
p=adb('push',str(src),TMP); print('push:',(p.stdout+p.stderr).strip()[:200])
r=adb('shell',f'busybox cp {TMP} {REMOTE}; echo CP_RC=$?; busybox ls -l {REMOTE}')
print('cp:',r.stdout.strip()[:300], r.stderr.strip()[:200])
report('ON TV ',pull_current())
print('\n备份原文件:',ORIG)
print('注意：本方案已证伪（getChannels URL 带动态 ttid，app 每次启动联网重拉，旧缓存不会被读）。')
print('保留此脚本仅作反例与缓存回滚工具；真正修复见 build_patched_apk.py / docs/11。')
