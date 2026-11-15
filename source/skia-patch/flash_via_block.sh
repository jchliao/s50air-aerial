#!/system/bin/sh
# ============================================================================
# Letv S50 Air — write the single-byte libskia.so WebP-alpha patch via the
# RAW BLOCK DEVICE. Runs through the uid1000 channel:
#   com.tvhelper.root/.Shell -> /sdcard/Download/root.sh
#
# Modes:  dry (DEFAULT, never writes) | apply | rollback
#
# All offsets below were MEASURED on this exact TV on 2026-11-15:
#   system partition      /dev/block/mmcblk0p9  (512 MB, ext4 ro)
#   libskia.so start      30818304 = 0x1D64000  (4K aligned)
#                         verified: 4 bytes = 7f 45 4c 46 and the whole
#                         2,247,420-byte file is byte-identical to backup
#   patch site            31947196 = 0x1E779BC  (start + 0x1139BC)
#                         verified: 8 bytes = 01 10 a0 e3 90 7a fd eb
#   uid1000 write perm    test -w = 0, dd count=0 open-for-write = 0
#
# SAFETY:
#   - dry-run by default; `apply` must be requested explicitly by the PC driver
#   - verifies uid, block device, ELF anchor, and 8 surrounding bytes BEFORE any write
#   - backs up the containing 4K block before writing
#   - sync + read back FROM THE BLOCK DEVICE (not /system/lib/, whose page cache
#     may still hold the old page until reboot)
#   - NEVER reboots and NEVER sends remote-control keypresses
#
# ROLLBACK: pass `rollback` to write 0x01 back, then reboot.
# FULL BACKUP (strongly recommended before `apply`):
#   busybox dd if=/dev/block/mmcblk0p9 of=/sdcard/Download/system_backup.img bs=1M
# ============================================================================

MODE=${1:-dry}

BB=/system/bin/busybox
BLK=/dev/block/mmcblk0p9
SO_START=30818304
PATCH_OFF=31947196
BLOCK_IDX=7799              # (PATCH_OFF & ~4095) / 4096 = 31944704 / 4096
IN_BLOCK=2492               # PATCH_OFF - 31944704
D=/sdcard/Download/skiaflash

fail() { echo "ABORT: $*"; exit 2; }

echo "=== SKIA FLASH mode=$MODE ==="
id

case "$MODE" in
    dry|apply|rollback) ;;
    *) fail "unknown mode '$MODE' (expected dry|apply|rollback)" ;;
esac

# --- preconditions ---------------------------------------------------------
id | $BB grep -q 'uid=1000' || fail "must run as uid=1000(system)"
[ -b "$BLK" ] || fail "block device missing: $BLK"
$BB test -w "$BLK" || fail "no write permission on $BLK"
for f in _elf4.bin _orig8.bin _patched8.bin _zero1.bin _one1.bin; do
    [ -f "$D/$f" ] || fail "missing verification sample: $D/$f (run flash_on_tv.py)"
done
echo "  uid / block / samples : OK"

# --- anchor check: ELF magic at the start of the embedded .so ---------------
$BB dd if="$BLK" of="$D/_cur4.bin" bs=1 skip="$SO_START" count=4 2>&1 || fail "cannot read ELF anchor"
$BB cmp -s "$D/_cur4.bin" "$D/_elf4.bin" || fail "ELF magic mismatch at $SO_START (wrong image?)"
echo "  ELF anchor @$SO_START : 7f 45 4c 46  OK"

# --- patch site state ------------------------------------------------------
$BB dd if="$BLK" of="$D/_cur8.bin" bs=1 skip="$PATCH_OFF" count=8 2>&1 || fail "cannot read patch site"
echo -n "  current 8 bytes       : "
$BB od -An -tx1 "$D/_cur8.bin"
if   $BB cmp -s "$D/_cur8.bin" "$D/_orig8.bin";    then STATE=orig
elif $BB cmp -s "$D/_cur8.bin" "$D/_patched8.bin"; then STATE=patched
else fail "unexpected bytes at $PATCH_OFF - wrong offset or damaged image"
fi
echo "  state                 : $STATE"

# --- always back up the containing 4K block --------------------------------
$BB dd if="$BLK" of="$D/_block4k.bak" bs=4096 skip="$BLOCK_IDX" count=1 2>&1 \
    || fail "cannot back up 4K block"
$BB dd if="$D/_block4k.bak" of="$D/_bak1.bin" bs=1 skip="$IN_BLOCK" count=1 2>/dev/null
echo -n "  backup block byte     : "
$BB od -An -tx1 "$D/_bak1.bin"
echo "  4K backup             : $D/_block4k.bak"

# --- dry run stops here ----------------------------------------------------
if [ "$MODE" = "dry" ]; then
    echo "  would write           : 0x00 at physical offset $PATCH_OFF (sector 62396 +444)"
    echo "  no bytes were written"
    echo "DRY_RUN_OK"
    rm -f "$D/_cur4.bin" "$D/_cur8.bin" "$D/_bak1.bin"
    exit 0
fi

# --- apply / rollback ------------------------------------------------------
if [ "$MODE" = "apply" ]; then
    [ "$STATE" = "orig" ] || fail "already patched; run rollback first"
    SRC="$D/_zero1.bin"; EXPECT="$D/_patched8.bin"; WORD=0x00
else
    [ "$STATE" = "patched" ] || fail "not patched; nothing to roll back"
    SRC="$D/_one1.bin"; EXPECT="$D/_orig8.bin"; WORD=0x01
fi

echo "=== writing $WORD at $PATCH_OFF ==="
$BB dd if="$SRC" of="$BLK" bs=1 seek="$PATCH_OFF" count=1 conv=notrunc 2>&1 \
    || fail "write failed - RESTORE FROM system_backup.img"
echo "  write_rc=$?"
$BB sync || fail "sync failed"
echo "  sync                  : OK"

$BB dd if="$BLK" of="$D/_verify8.bin" bs=1 skip="$PATCH_OFF" count=8 2>&1 \
    || fail "cannot read back"
echo -n "  readback 8 bytes      : "
$BB od -An -tx1 "$D/_verify8.bin"
$BB cmp -s "$D/_verify8.bin" "$EXPECT" || {
    echo "ERROR: readback mismatch. RESTORE FROM system_backup.img (or run rollback)."
    exit 4
}

if [ "$MODE" = "apply" ]; then
    echo "FLASH_OK: 1 byte patched on disk. REBOOT REQUIRED (zygote still has old lib mmap'd)."
else
    echo "ROLLBACK_OK: original byte restored. REBOOT REQUIRED."
fi
echo "  After reboot, verify sha256 of /system/lib/libskia.so = f8e4328c... (apply) / 4642931b... (rollback)."
rm -f "$D/_cur4.bin" "$D/_cur8.bin" "$D/_bak1.bin" "$D/_verify8.bin"
exit 0
