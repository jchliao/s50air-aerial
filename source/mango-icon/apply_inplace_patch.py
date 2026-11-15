#!/usr/bin/env python3
"""Reversible, no-uninstall runtime experiment for the mangoTV RGB_565 fix.

Overwrites the installed APK with a variant that keeps the ORIGINAL v1
signature files byte-for-byte and only swaps classes4.dex. Dalvik does not
re-verify jar signatures at runtime, so this needs no uninstall, no signature
change and no data loss. uid1000 (tvhelper Shell) is required because /data/app
is system:system.

!!! PackageManager DOES verify every entry at the next BOOT scan, so run
    --restore BEFORE rebooting the TV.

Safety: --apply refuses to run unless the on-TV APK is byte-identical to the
original that the patch was built from (--baseline). This prevents accidentally
injecting a 5.16.3 dex into a different channel build.

  python apply_inplace_patch.py --baseline PATH --patch PATH --dry
  python apply_inplace_patch.py --baseline PATH --patch PATH --check
  python apply_inplace_patch.py --baseline PATH --patch PATH --apply
  python apply_inplace_patch.py --baseline PATH --patch PATH --restore
"""
import argparse, hashlib, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ADB = ROOT / 'aerial-tools' / 'platform-tools' / 'adb.exe'
DEV = '192.168.5.9:5555'
PKG = 'com.starcor.mango'
TMP = '/sdcard/Download/_mango_inplace.apk'
BACKUP = HERE / 'mango-apk-backup-from-tv.apk'


def adb(*a):
    return subprocess.run([str(ADB), '-s', DEV, *a], capture_output=True,
                          text=True, errors='replace')


def sh(s):
    p = adb('shell', s)
    return (p.stdout + p.stderr).strip()


def root(script):
    p = HERE / '_root_inplace.sh'
    p.write_text('#!/system/bin/sh\n' + script + '\necho "=== rc=$? ==="\n', newline='\n')
    adb('push', str(p), '/sdcard/Download/root.sh')
    adb('shell', 'am startservice --user 0 -n com.tvhelper.root/.Shell')
    for _ in range(20):
        time.sleep(1)
        log = sh('cat /sdcard/Download/root.log')
        if '=== rc=' in log:
            return log
    return sh('cat /sdcard/Download/root.log')


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', required=True, help='original on-device APK the patch was built from')
    ap.add_argument('--patch', required=True, help='inplace APK (same signature, new classes4.dex)')
    ap.add_argument('mode', nargs='?', default='--dry',
                    choices=['--dry', '--check', '--apply', '--restore'])
    a = ap.parse_args()
    base, patch = Path(a.baseline), Path(a.patch)
    for p in (base, patch):
        if not p.is_file():
            print('MISSING:', p)
            sys.exit(2)

    subprocess.run([str(ADB), 'connect', DEV], capture_output=True)
    remote = sh('pm path %s' % PKG).splitlines()
    remote = next((l.split(':', 1)[1].strip() for l in remote if l.startswith('package:')), None)
    if not remote:
        print('cannot resolve installed APK path')
        sys.exit(2)
    on_tv_md5 = sh('busybox md5sum %s' % remote).split()[0]
    base_md5, patch_md5 = md5(base), md5(patch)
    print('on-TV APK   :', remote, on_tv_md5)
    print('baseline    :', base.name, base_md5)
    print('patch       :', patch.name, patch_md5)

    if a.mode == '--check':
        print('STATE:', 'PATCHED' if on_tv_md5 == patch_md5 else
              'ORIGINAL' if on_tv_md5 == base_md5 else 'OTHER / UNKNOWN')
        return

    if a.mode == '--dry':
        print('\nDRY RUN - nothing will be written')
        print('  would overwrite:', remote)
        print('  backup target  :', BACKUP)
        print('  NOTE: --restore before rebooting the TV.')
        return

    src = base if a.mode == '--restore' else patch
    if a.mode == '--apply' and on_tv_md5 != base_md5:
        print('\nREFUSING --apply: on-TV APK does not match the baseline.')
        print('  Install the matching baseline first, or rebuild the patch for this build.')
        sys.exit(3)

    if a.mode == '--apply':
        print('\n1) pull on-TV APK as backup ->', BACKUP)
        adb('pull', remote, str(BACKUP))
        print('   bytes', BACKUP.stat().st_size, 'md5', md5(BACKUP))

    print('2) push', src.name, '->', TMP)
    r = adb('push', str(src), TMP)
    print('  ', (r.stdout + r.stderr).strip()[:200])

    print('3) uid1000 overwrite + relaunch')
    print(root(
        'busybox cp %s %s\necho CP_RC=$?\nbusybox chmod 644 %s\nbusybox md5sum %s\n'
        'am force-stop %s\nmonkey -p %s -c android.intent.category.LAUNCHER 1\n'
        'echo MONKEY_RC=$?\n' % (TMP, remote, remote, remote, PKG, PKG)
    )[:1200])
    print('\n4) on-TV md5 now:', sh('busybox md5sum %s' % remote).split()[0])
    if a.mode == '--apply':
        print('\nNEXT: look at the TV home page, then --restore BEFORE any reboot.')
    else:
        print('\nRESTORED.')


if __name__ == '__main__':
    main()
