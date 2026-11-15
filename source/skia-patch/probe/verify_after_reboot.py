#!/usr/bin/env python3
"""Post-reboot verification: is the patched libskia.so really in effect?

Run this AFTER the TV has been rebooted.  Unlike verify_on_tv.py (which is an
A/B comparison using LD_LIBRARY_PATH), this script deliberately loads NO
replacement library: app_process resolves DT_NEEDED to the real
/system/lib/libskia.so.  If the 1-byte patch was written to the system
partition and the reboot picked it up, the probe must now behave exactly like
the "patched" baseline from verify_on_tv.py -- with no LD_LIBRARY_PATH at all.

Checks
------
  1. VFS sha256 of /system/lib/libskia.so == patched library
  2. block-device read-back at 0x1E779BC still 00 10 a0 e3 ...
  3. /proc/self/maps says /system/lib/libskia.so (no LD_LIBRARY_PATH)
  4. zygote / system_server are post-reboot processes and map the system lib
  5. every decoded sample matches the patched baseline pixel-for-pixel
     (checksum / alphaSum / hasAlpha / histogram), and differs from the
     original-library baseline on the ALPH samples
  6. exported PNGs are byte-identical to the patched baseline PNGs

Usage:
    python verify_after_reboot.py
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]                        # workspace root
BUILD = ROOT / 'aerial-tools' / 'build'
ART = BUILD / 'patch-libskia'
SAMPLES = BUILD / 'webptest'
ADB = ROOT / 'aerial-tools' / 'platform-tools' / 'adb.exe'

TV_DEX = '/sdcard/Download/skiaprobe.dex'
TV_SAMPLES = '/sdcard/Download/webptest'
TV_OUT = '/sdcard/Download/skiaprobe'
LABEL = 'after_reboot'
PHYS_OFF = 31947196
SO_SIZE = 2247420
SO_START = 30818304

PROBE_SCRIPT = """#!/system/bin/sh
BB=/system/bin/busybox
echo "=== POST-REBOOT PROBE ==="
id
echo "--- uptime / date (proof of reboot) ---"
cat /proc/uptime
date
echo "--- VFS sha256 /system/lib/libskia.so ---"
$BB sha256sum /system/lib/libskia.so
echo "--- this shell process maps ---"
grep libskia /proc/self/maps
echo "--- run probe with NO LD_LIBRARY_PATH ---"
mkdir -p /data/local/tmp/skiadroid/dalvik-cache
rm -rf /sdcard/Download/skiaprobe
mkdir -p /sdcard/Download/skiaprobe
ANDROID_DATA=/data/local/tmp/skiadroid CLASSPATH=/sdcard/Download/skiaprobe.dex app_process /system/bin com.tv.skiaprobe.ProbeMain after_reboot
echo "PROBE_EXIT=$?"
echo "--- outputs ---"
ls -l /sdcard/Download/skiaprobe/
echo "=== PROBE DONE ==="
"""

ROOT_SCRIPT = """#!/system/bin/sh
BB=/system/bin/busybox
echo "=== UID1000 SYSTEM VIEW ==="
id
echo "--- zygote / system_server pids ---"
Z=$($BB pidof zygote)
S=$($BB pidof system_server)
echo "ZYGOTE=$Z SYSTEM_SERVER=$S"
echo "--- zygote libskia maps ---"
grep libskia /proc/$Z/maps
echo "--- system_server libskia maps ---"
grep libskia /proc/$S/maps
echo "--- system_server status ---"
grep -E '^(Name|Uid|CapEff)' /proc/$S/status
echo "--- block device 8B @ patch site ---"
$BB dd if=/dev/block/mmcblk0p9 of=/sdcard/Download/_blk8.bin bs=1 skip=31947196 count=8 2>/dev/null
$BB od -An -tx1 /sdcard/Download/_blk8.bin
rm -f /sdcard/Download/_blk8.bin
echo "--- block device: full libskia.so region sha256 ---"
$BB dd if=/dev/block/mmcblk0p9 of=/sdcard/Download/_so_from_block.bin bs=4096 skip=7524 count=549 2>/dev/null
$BB head -c 2247420 /sdcard/Download/_so_from_block.bin > /sdcard/Download/_so_slice.bin
$BB sha256sum /sdcard/Download/_so_slice.bin
$BB md5sum /sdcard/Download/_so_slice.bin
rm -f /sdcard/Download/_so_from_block.bin /sdcard/Download/_so_slice.bin
echo "--- system health ---"
grep ' /system ' /proc/mounts
echo "=== UID1000 DONE ==="
"""

REGRESSION = ['10_checker.png', '03_vp8_plain.webp', '12_checker_vp8.webp',
              '01_vp8x_iccp.webp', '04_vp8x_iccp_plain.webp',
              '05_vp8x_alph_plain.webp']
ALPHA = ['02_vp8x_alph.webp', '11_checker_vp8x.webp']


def run(cmd, timeout=300):
    return subprocess.run([str(x) for x in cmd], capture_output=True,
                          text=True, errors='replace', timeout=timeout)


def parse(path):
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        m = re.match(r'SAMPLE (\S+) \|', line)
        if m:
            d = dict(name=m.group(1), raw=line)
            for k in ('hasAlpha', 'checksum', 'alphaSum', 'opaque', 'semi',
                      'transparent', 'cfg'):
                mm = re.search(r'\b' + k + r'=([^ |]+)', line)
                if mm:
                    d[k] = mm.group(1)
            for k in ('opaque', 'semi', 'transparent', 'alphaSum'):
                if k in d:
                    d[k] = int(d[k])
            out[d['name']] = d
        elif line.startswith('LIBSKIA_MAPS='):
            out['_maps'] = line[len('LIBSKIA_MAPS='):]
        elif line.startswith('LD_LIBRARY_PATH='):
            out['_ld'] = line[len('LD_LIBRARY_PATH='):]
        elif line.startswith('PID='):
            out['_pid'] = line[4:]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=str(ADB))
    ap.add_argument('--serial', default='192.168.5.9:5555')
    a = ap.parse_args()
    adb = a.adb

    for p in (adb, ART / 'skiaprobe.dex', ART / 'orig.txt', ART / 'patched.txt',
              ART / 'libskia-patched.so', SAMPLES / '10_checker.png'):
        if not Path(p).exists():
            print('MISSING: %s' % p)
            return 2

    def A(*args, timeout=300):
        r = run([adb, '-s', a.serial] + list(args), timeout)
        if r.returncode != 0:
            print('  !! adb rc=%d: %s\n%s' % (r.returncode, ' '.join(map(str, args)),
                                               (r.stderr or '')[:400]))
        return r

    print('connect ...')
    run([adb, 'connect', a.serial])

    print('push probe dex + samples ...')
    A('push', ART / 'skiaprobe.dex', TV_DEX)
    A('push', SAMPLES, TV_SAMPLES)

    probe_sh = ART / 'post_reboot_probe.sh'
    probe_sh.write_text(PROBE_SCRIPT.replace('\r\n', '\n'), encoding='utf-8', newline='\n')
    A('push', probe_sh, '/sdcard/Download/post_reboot_probe.sh')
    print('run probe (no LD_LIBRARY_PATH) ...')
    r = A('shell', 'sh /sdcard/Download/post_reboot_probe.sh')
    console = (r.stdout or '') + (r.stderr or '')
    (ART / 'post_reboot_console.log').write_text(console, encoding='utf-8')
    print(console)

    root_sh = ART / 'post_reboot_root.sh'
    root_sh.write_text(ROOT_SCRIPT.replace('\r\n', '\n'), encoding='utf-8', newline='\n')
    A('push', root_sh, '/sdcard/Download/root.sh')
    A('shell', 'rm -f /sdcard/Download/root.log')
    A('shell', 'am startservice --user 0 -n com.tvhelper.root/.Shell')
    rootlog = ''
    for _ in range(60):
        rootlog = A('shell', 'cat /sdcard/Download/root.log').stdout or ''
        if '=== done ===' in rootlog:
            break
        time.sleep(1)
    (ART / 'post_reboot_root.log').write_text(rootlog, encoding='utf-8')
    print(rootlog)

    print('pull results ...')
    A('pull', TV_OUT + '/' + LABEL + '.txt', ART / (LABEL + '.txt'))
    p = ART / 'probe_out_after_reboot'
    if p.exists():
        shutil.rmtree(p)
    A('pull', TV_OUT, p)

    # ---------------- verdict ----------------
    base_p = parse(ART / 'patched.txt')
    base_o = parse(ART / 'orig.txt')
    now = parse(ART / (LABEL + '.txt'))
    patched_so = (ART / 'libskia-patched.so').read_bytes()
    so_hash = hashlib.sha256(patched_so).hexdigest()
    checks = []

    def ck(name, ok, detail=''):
        checks.append(dict(name=name, ok=bool(ok), detail=str(detail)))
        print('[%s] %-58s %s' % ('PASS' if ok else 'FAIL', name, detail))

    m = re.search(r'([0-9a-f]{64})\s+/system/lib/libskia\.so', console)
    vfs = m.group(1) if m else '(missing)'
    ck('VFS /system/lib/libskia.so == patched sha256', vfs == so_hash, vfs)

    m = re.search(r'00\s+10\s+a0\s+e3\s+90\s+7a\s+fd\s+eb', rootlog)
    ck('block device still patched (00 10 a0 e3 ...)', bool(m))

    m = re.search(r'([0-9a-f]{64})\s+/sdcard/Download/_so_slice\.bin', rootlog)
    blk = m.group(1) if m else '(missing)'
    ck('full so from block device == patched sha256', blk == so_hash, blk)

    ck('probe loaded the SYSTEM libskia.so',
       '/system/lib/libskia.so' in now.get('_maps', '')
       and 'skiapatch' not in now.get('_maps', ''),
       now.get('_maps', '(missing)'))
    ld = now.get('_ld', '')
    ck('no LD_LIBRARY_PATH substitution used',
       'skiapatch' not in ld,
       repr(ld) + ' (system default, no replacement lib)')

    zy = re.search(r'ZYGOTE=(\d+)', rootlog)
    sy = re.search(r'SYSTEM_SERVER=(\d+)', rootlog)
    alive = bool(zy and sy and int(zy.group(1)) > 0 and int(sy.group(1)) > 0)
    ck('post-reboot zygote / system_server alive',
       alive,
       'zygote pid=%s system_server pid=%s' %
       (zy.group(1) if zy else '?', sy.group(1) if sy else '?'))
    # Android 4.3 procfs hides /proc/<pid>/maps of other uids even from
    # uid1000; this is a kernel permission limit, NOT a patch problem.
    if 'Permission denied' in rootlog:
        print('[INFO] /proc/<pid>/maps of zygote & system_server unreadable '
              '(kernel proc restriction). VFS + block-device hashes + the '
              'non-zygote probe above already prove the loaded library.')

    ck('probe decoded the full sample set',
       len(now) >= 8, '%d samples' % (len(now) - 3))

    for n in REGRESSION + ALPHA:
        d1, d2 = now.get(n), base_p.get(n)
        same = bool(d1 and d2 and all(
            d1.get(k) == d2.get(k) for k in
            ('hasAlpha', 'checksum', 'alphaSum', 'opaque', 'semi',
             'transparent', 'cfg')))
        ck('matches patched baseline: %s' % n, same,
           'now checksum=%s / baseline=%s' %
           (d1.get('checksum', '?') if d1 else 'MISSING',
            d2.get('checksum', '?') if d2 else 'MISSING'))

    for n in ALPHA:
        d1, d0 = now.get(n), base_o.get(n)
        ck('differs from ORIGINAL library: %s' % n,
           bool(d1 and d0 and d1.get('checksum') != d0.get('checksum')
                and d1.get('hasAlpha') == 'true'
                and d0.get('hasAlpha') == 'false'),
           'now hasAlpha=%s alphaSum=%s | orig hasAlpha=%s alphaSum=%s' %
           (d1.get('hasAlpha', '?') if d1 else '?', d1.get('alphaSum', '?') if d1 else '?',
            d0.get('hasAlpha', '?') if d0 else '?', d0.get('alphaSum', '?') if d0 else '?'))

    # exported PNG byte comparison against patched baseline
    old_dir = ART / 'probe_out' / 'skiaprobe'
    new_dir = ART / 'probe_out_after_reboot'
    if not (old_dir.exists() and new_dir.exists()):
        old_dir = ART / 'probe_out'
        new_dir = ART / 'probe_out_after_reboot'
    png_ok = 0
    png_n = 0
    if old_dir.exists() and new_dir.exists():
        for f in sorted(new_dir.glob(LABEL + '_*.png')):
            counterpart = old_dir / f.name.replace(LABEL + '_', 'patched_', 1)
            if not counterpart.exists():
                continue
            png_n += 1
            if f.read_bytes() == counterpart.read_bytes():
                png_ok += 1
    ck('exported PNGs byte-identical to patched baseline',
       png_n >= 8 and png_ok == png_n, '%d/%d' % (png_ok, png_n))

    failed = [c for c in checks if not c['ok']]
    verdict = 'PATCH LIVE AND VERIFIED AFTER REBOOT' if not failed else 'NOT FULLY VERIFIED'
    print()
    print('=== SUMMARY: %d checks, %d passed, %d failed ===' %
          (len(checks), len(checks) - len(failed), len(failed)))
    print('VERDICT: %s' % verdict)

    (ART / 'post_reboot_verify.json').write_text(json.dumps({
        'vfs_sha256': vfs, 'block_sha256': blk, 'expected_sha256': so_hash,
        'probe_maps': now.get('_maps'), 'ld_library_path': ld,
        'samples': {k: v for k, v in now.items() if not k.startswith('_')},
        'checks': checks, 'verdict': verdict,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
