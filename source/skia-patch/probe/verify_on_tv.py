#!/usr/bin/env python3
"""Run the A/B verification on the TV WITHOUT flashing /system or rebooting.

Why this works
--------------
A normal app is forked from zygote, which has already mmap'ed
/system/lib/libskia.so; LD_LIBRARY_PATH cannot change that. `app_process`
started directly from the shell is a fresh, non-zygote process, so the
Android dynamic linker resolves DT_NEEDED through LD_LIBRARY_PATH first.
We put the patched library (named libskia.so) in /data/local/tmp/skiapatch
and run the SAME probe twice:

  A  no LD_LIBRARY_PATH  -> /system/lib/libskia.so   (control)
  B  LD_LIBRARY_PATH=... -> /data/local/tmp/...      (patched)

The probe prints /proc/self/maps (proof of which library was really loaded),
decodes the same WebP/PNG samples and reports hasAlpha / alpha histogram /
pixel checksum. That is an end-to-end proof of the patch, with zero writes
to /system, no reboot and no remote-control keypresses.

Usage:
    python verify_on_tv.py [--adb <adb.exe>] [--serial 192.168.5.9:5555]
                           [--patched <libskia-patched.so>] [--dry-run]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]                       # workspace root
BUILD = ROOT / 'aerial-tools' / 'build'
ART = BUILD / 'patch-libskia'
SAMPLES = BUILD / 'webptest'
ADB = ROOT / 'aerial-tools' / 'platform-tools' / 'adb.exe'

TV_DEX = '/sdcard/Download/skiaprobe.dex'
TV_LIB = '/data/local/tmp/skiapatch/libskia.so'
TV_SAMPLES = '/sdcard/Download/webptest'
TV_OUT = '/sdcard/Download/skiaprobe'
TV_SCRIPT = '/sdcard/Download/skiaprobe_run.sh'

SCRIPT = """#!/system/bin/sh
echo "=== SKIAPROBE A/B ==="
id
ls -l /data/local/tmp/skiapatch/libskia.so
# app_process needs a writable dexopt cache. /data/dalvik-cache is
# system:system 0771 and uid2000(shell) cannot create files there;
# without this it fails to load the dex and dies at 0xdeadd00d.
mkdir -p /data/local/tmp/skiadroid/dalvik-cache
rm -rf /sdcard/Download/skiaprobe
mkdir -p /sdcard/Download/skiaprobe
echo "--- A: original /system/lib/libskia.so ---"
ANDROID_DATA=/data/local/tmp/skiadroid CLASSPATH=/sdcard/Download/skiaprobe.dex app_process /system/bin com.tv.skiaprobe.ProbeMain orig
echo "A_EXIT=$?"
echo "--- B: patched libskia.so via LD_LIBRARY_PATH ---"
LD_LIBRARY_PATH=/data/local/tmp/skiapatch:/vendor/lib:/system/lib:/system/lib/egl ANDROID_DATA=/data/local/tmp/skiadroid CLASSPATH=/sdcard/Download/skiaprobe.dex app_process /system/bin com.tv.skiaprobe.ProbeMain patched
echo "B_EXIT=$?"
echo "--- output files ---"
ls -l /sdcard/Download/skiaprobe/
echo "=== DONE ==="
"""

# samples that must be byte-for-byte identical between A and B
REGRESSION = ['10_checker.png', '03_vp8_plain.webp', '12_checker_vp8.webp',
              '01_vp8x_iccp.webp', '04_vp8x_iccp_plain.webp',
              '05_vp8x_alph_plain.webp']
# samples that carry an ALPH chunk and must change with the patch
ALPHA = ['02_vp8x_alph.webp', '11_checker_vp8x.webp']


def run(cmd, capture=True):
    return subprocess.run([str(x) for x in cmd], capture_output=capture,
                          text=True, errors='replace')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=str(ADB))
    ap.add_argument('--serial', default='192.168.5.9:5555')
    ap.add_argument('--patched', default=str(ART / 'libskia-patched.so'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    adb = a.adb
    for p in (adb, a.patched, ART / 'skiaprobe.dex', SAMPLES / '10_checker.png'):
        if not Path(p).exists():
            print('MISSING: %s' % p)
            return 2

    if a.dry_run:
        print(SCRIPT)
        return 0

    def A(*args):
        r = run([adb, '-s', a.serial] + list(args))
        if r.returncode != 0:
            print('  !! adb rc=%d: %s\n%s' % (r.returncode, ' '.join(map(str, args)),
                                               (r.stderr or '')[:500]))
        return r

    print('connect ...')
    run([adb, 'connect', a.serial])

    print('push dex / patched lib / samples ...')
    A('push', ART / 'skiaprobe.dex', TV_DEX)
    A('shell', 'mkdir -p /data/local/tmp/skiapatch')
    A('push', a.patched, TV_LIB)
    A('shell', 'chmod 644 ' + TV_LIB)
    A('push', SAMPLES, TV_SAMPLES)

    local_script = ART / 'skiaprobe_run.sh'
    local_script.write_text(SCRIPT.replace('\r\n', '\n'), encoding='utf-8', newline='\n')
    A('push', local_script, TV_SCRIPT)

    print('run A/B ...')
    r = A('shell', 'sh', TV_SCRIPT)
    console = (r.stdout or '') + (r.stderr or '')
    (ART / 'verify_dynamic_console.log').write_text(console, encoding='utf-8')
    print(console)

    for label in ('orig', 'patched'):
        A('pull', TV_OUT + '/' + label + '.txt', ART / (label + '.txt'))
    A('pull', TV_OUT, ART / 'probe_out')

    texts = {}
    for label in ('orig', 'patched'):
        p = ART / (label + '.txt')
        texts[label] = p.read_text(encoding='utf-8', errors='replace') if p.exists() else ''

    def parse(t):
        out = {}
        for line in t.splitlines():
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
        return out

    A_, B_ = parse(texts['orig']), parse(texts['patched'])
    checks = []

    def ck(name, ok, detail=''):
        checks.append(dict(name=name, ok=bool(ok), detail=str(detail)))
        print('[%s] %-56s %s' % ('PASS' if ok else 'FAIL', name, detail))

    print()
    print('=== A/B verdict ===')
    ck('control loaded /system/lib/libskia.so',
       '/system/lib/libskia.so' in A_.get('_maps', ''), A_.get('_maps', '(missing)'))
    ck('experiment loaded patched libskia.so',
       TV_LIB in B_.get('_maps', ''), B_.get('_maps', '(missing)'))
    ck('LD_LIBRARY_PATH actually set for B',
       'skiapatch' in B_.get('_ld', ''), B_.get('_ld', '(missing)'))
    ck('both runs decoded the same sample set',
       len(A_) > 5 and set(k for k in A_ if not k.startswith('_')) ==
       set(k for k in B_ if not k.startswith('_')),
       'A=%d B=%d samples' % (len(A_) - 2, len(B_) - 2))

    for n in REGRESSION:
        d1, d2 = A_.get(n), B_.get(n)
        ck('no regression: %s' % n,
           bool(d1 and d2 and d1.get('checksum') == d2.get('checksum')),
           'A=%s B=%s' % (d1.get('checksum', '?') if d1 else 'MISSING',
                          d2.get('checksum', '?') if d2 else 'MISSING'))

    for n in ALPHA:
        d1, d2 = A_.get(n), B_.get(n)
        ok = bool(d1 and d2
                  and d1.get('hasAlpha') == 'false'
                  and d2.get('hasAlpha') == 'true'
                  and d1.get('transparent', 0) == 0
                  and d1.get('semi', 0) == 0
                  and (d2.get('transparent', 0) + d2.get('semi', 0)) > 0)
        ck('alpha restored: %s' % n, ok,
           'A hasAlpha=%s opaque=%s semi=%s trans=%s | B hasAlpha=%s opaque=%s semi=%s trans=%s'
           % (d1.get('hasAlpha', '?') if d1 else '?', d1.get('opaque', '?') if d1 else '?',
              d1.get('semi', '?') if d1 else '?', d1.get('transparent', '?') if d1 else '?',
              d2.get('hasAlpha', '?') if d2 else '?', d2.get('opaque', '?') if d2 else '?',
              d2.get('semi', '?') if d2 else '?', d2.get('transparent', '?') if d2 else '?'))

    failed = [c for c in checks if not c['ok']]
    # separate "patch wrong" from "harness did not work"
    harness_ok = all(c['ok'] for c in checks[:4])
    verdict = ('PATCH VERIFIED END-TO-END' if not failed and harness_ok
               else 'HARNESS INCONCLUSIVE' if not harness_ok else 'PATCH NOT VERIFIED')
    print()
    print('=== SUMMARY: %d checks, %d passed, %d failed ===' %
          (len(checks), len(checks) - len(failed), len(failed)))
    print('VERDICT: %s' % verdict)
    if not harness_ok:
        print('The two runs did not load different libraries, so no conclusion')
        print('about the patch can be drawn. Check verify_dynamic_console.log.')

    (ART / 'verify_dynamic.json').write_text(json.dumps({
        'control': {k: v for k, v in A_.items() if not k.startswith('_')},
        'patched': {k: v for k, v in B_.items() if not k.startswith('_')},
        'control_maps': A_.get('_maps'), 'patched_maps': B_.get('_maps'),
        'checks': checks, 'verdict': verdict,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
