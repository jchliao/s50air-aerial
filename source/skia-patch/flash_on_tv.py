#!/usr/bin/env python3
"""Drive the 1-byte libskia.so patch write on the Letv S50 Air.

The TV's /system is read-only and neither uid2000 nor uid1000 can remount it,
but /dev/block/mmcblk0p9 is `system:system 0660`, so the uid1000 channel
(com.tvhelper.root/.Shell -> /sdcard/Download/root.sh) can write the raw block.

Modes
-----
  dry       DEFAULT. Push verification samples + run all checks, write NOTHING.
  backup    Full 512 MB system partition dump to /sdcard/Download/system_backup.img.
  apply     Write 0x00 at physical offset 31947196. Requires --confirm-write-system.
  rollback  Write 0x01 back. Requires --confirm-write-system.

Safety
------
  * `apply` refuses to run unless a full partition backup exists on the TV
    (unless --skip-backup-check is given explicitly).
  * The TV-side script independently re-verifies uid, block device, ELF anchor,
    and the 8 bytes around the patch site before touching anything.
  * Nothing here reboots the TV or sends remote-control keypresses.

Usage
-----
  python flash_on_tv.py --mode dry
  python flash_on_tv.py --mode backup
  python flash_on_tv.py --mode apply --confirm-write-system
  python flash_on_tv.py --mode rollback --confirm-write-system
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # workspace root
BUILD = ROOT / 'aerial-tools' / 'build'
ASSETS = BUILD / 'patch-libskia' / 'flash_assets'
ADB = ROOT / 'aerial-tools' / 'platform-tools' / 'adb.exe'

TV_DIR = '/sdcard/Download/skiaflash'
TV_SCRIPT = TV_DIR + '/flash_via_block.sh'
TV_ROOT_SH = '/sdcard/Download/root.sh'
TV_LOG = '/sdcard/Download/root.log'
TV_BACKUP = '/sdcard/Download/system_backup.img'
SYSTEM_SIZE = 524288 * 1024                 # 512 MB

SAMPLES = {
    '_elf4.bin':     bytes.fromhex('7f454c46'),
    '_orig8.bin':    bytes.fromhex('0110a0e3907afdeb'),
    '_patched8.bin': bytes.fromhex('0010a0e3907afdeb'),
    '_zero1.bin':    b'\x00',
    '_one1.bin':     b'\x01',
}

BACKUP_SH = '''#!/system/bin/sh
BB=/system/bin/busybox
if [ -f /sdcard/Download/system_backup.img ]; then
  echo "BACKUP_EXISTS: keeping existing full partition backup"
  ls -l /sdcard/Download/system_backup.img
  echo "=== BACKUP DONE ==="
  exit 0
fi
echo "=== full system partition backup (512MB) ==="
id
$BB dd if=/dev/block/mmcblk0p9 of=/sdcard/Download/system_backup.img bs=1M 2>&1
echo "dd_rc=$?"
ls -l /sdcard/Download/system_backup.img
$BB sync
echo "BACKUP_OK"
echo "=== BACKUP DONE ==="
'''


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True,
                          errors='replace', **kw)


def sh(adb, cmd, timeout=60):
    r = run([adb, 'shell', cmd], timeout=timeout)
    return (r.stdout or '').strip(), (r.stderr or '').strip(), r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['dry', 'backup', 'apply', 'rollback'],
                    default='dry')
    ap.add_argument('--confirm-write-system', action='store_true',
                    help='required for apply/rollback')
    ap.add_argument('--skip-backup-check', action='store_true',
                    help='allow apply without a full 512MB partition backup')
    ap.add_argument('--adb', default=str(ADB))
    ap.add_argument('--serial', default='192.168.5.9:5555')
    a = ap.parse_args()

    adb = a.adb
    if not Path(adb).exists():
        print('ERROR: adb not found:', adb)
        return 2

    run([adb, 'connect', a.serial], timeout=30)
    out, _, _ = sh(adb, 'getprop ro.product.model')
    if not out:
        print('ERROR: TV not reachable via adb')
        return 2
    print('device:', out)

    if a.mode in ('apply', 'rollback') and not a.confirm_write_system:
        print('ERROR: %s writes to the system partition; pass '
              '--confirm-write-system after reading docs/09-flash-decision.md'
              % a.mode)
        return 2

    if a.mode == 'apply' and not a.skip_backup_check:
        out, _, _ = sh(adb, 'ls -l ' + TV_BACKUP)
        if str(SYSTEM_SIZE) not in out:
            print('ERROR: full partition backup missing or wrong size.')
            print('       Run: python flash_on_tv.py --mode backup')
            print('       (or pass --skip-backup-check to accept the risk)')
            return 2
        print('backup check: OK (512 MB)')

    # --- prepare local verification samples --------------------------------
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, data in SAMPLES.items():
        (ASSETS / name).write_bytes(data)

    sh(adb, 'mkdir -p ' + TV_DIR)
    for name in SAMPLES:
        r = run([adb, 'push', str(ASSETS / name), TV_DIR + '/' + name], timeout=60)
        if r.returncode:
            print('ERROR pushing', name, r.stderr)
            return 2
    r = run([adb, 'push', str(HERE / 'flash_via_block.sh'), TV_SCRIPT], timeout=60)
    if r.returncode:
        print('ERROR pushing flash script:', r.stderr)
        return 2

    # --- build root.sh (tvhelper executes exactly this file as uid1000) ----
    if a.mode == 'backup':
        root_content = BACKUP_SH
        done_marker = '=== BACKUP DONE ==='
    else:
        root_content = ('#!/system/bin/sh\n'
                        'sh %s %s\n' % (TV_SCRIPT, a.mode))
        done_marker = '=== done ==='
    tmp = ASSETS / 'root.sh'
    tmp.write_text(root_content, newline='\n')
    r = run([adb, 'push', str(tmp), TV_ROOT_SH], timeout=60)
    if r.returncode:
        print('ERROR pushing root.sh:', r.stderr)
        return 2

    sh(adb, 'rm -f ' + TV_LOG)
    sh(adb, 'am startservice --user 0 -n com.tvhelper.root/.Shell')

    # --- wait for tvhelper to finish (backup can take ~40s) ----------------
    log = ''
    deadline = time.time() + 180
    while time.time() < deadline:
        out, _, _ = sh(adb, 'cat ' + TV_LOG, timeout=30)
        log = out
        if done_marker in log or '=== done ===' in log:
            break
        time.sleep(1)

    print('--- root.log ---')
    print(log)
    print('--- verdict ---')

    if a.mode == 'backup':
        ok = 'BACKUP_OK' in log or 'BACKUP_EXISTS' in log
    elif a.mode == 'dry':
        ok = 'DRY_RUN_OK' in log
    elif a.mode == 'apply':
        ok = 'FLASH_OK' in log
    else:
        ok = 'ROLLBACK_OK' in log

    if 'ABORT:' in log or 'ERROR:' in log:
        ok = False

    if ok:
        print('%s: OK' % a.mode.upper())
        if a.mode in ('apply', 'rollback'):
            print('Next: REBOOT the TV manually, then run the post-flash '
                  'checklist in docs/08-system-patch.md section 6 (layer 4).')
        elif a.mode == 'dry':
            print('No bytes were written. Ready for --mode apply.')
        return 0
    print('%s: FAILED (see root.log above). No reboot performed.' % a.mode.upper())
    return 1


if __name__ == '__main__':
    sys.exit(main())
