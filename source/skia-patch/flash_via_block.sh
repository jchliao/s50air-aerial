#!/system/bin/sh
# ============================================================================
# TEMPLATE ONLY - NEVER EXECUTED AGAINST THE TV AS-IS.
# Letv S50 Air: write the single-byte libskia.so patch via the raw block device.
# Run through the uid1000 channel (tvhelper .Shell -> /sdcard/Download/root.sh).
#
# BEFORE USE (all mandatory):
#   1. Full backup:  busybox dd if=/dev/block/mmcblk0p9 \
#                        of=/sdcard/Download/system_backup.img bs=1M
#   2. Locate libskia.so inside the partition:
#        busybox dd if=/dev/block/mmcblk0p9 \
#                  of=/sdcard/Download/system_full.img bs=1M
#        grep -a -b -o -F 'SkWEBPImageDecoder' /sdcard/Download/system_full.img
#      Compute: PHYS_OFFSET = (grep offset) - (offset of that string inside
#      libskia.so) + 0x1139BC. Verify the computed file start begins with
#      the ELF magic 7f 45 4c 46.
#   3. Set PHYS_OFFSET below, keep DRY_RUN=1, run once, confirm the byte
#      printed by od is exactly "01".
#   4. Only then set DRY_RUN=0. Reboot afterwards (zygote has libskia mmap'd).
#
# ROLLBACK: write byte 0x01 back to the same PHYS_OFFSET, or restore the
#           original libskia.so from backup. No dalvik-cache work needed.
# ============================================================================

DRY_RUN=1
PHYS_OFFSET=0          # <-- FILL ME (absolute byte offset in mmcblk0p9)

BLK=/dev/block/mmcblk0p9
BB=/system/bin/busybox
OUT=/sdcard/Download
BACKUP=$OUT/system_backup.img
TMP=$OUT/_wb_onebyte.bin
ZERO=$OUT/_wb_zero.bin
ONE=$OUT/_wb_one.bin

echo "=== libskia one-byte patch (via raw block) ==="
id
echo "  block       : $BLK"
echo "  offset      : $PHYS_OFFSET"
echo "  dry_run     : $DRY_RUN"

if [ "$PHYS_OFFSET" = "0" ]; then
    echo "ABORT: PHYS_OFFSET not set. See header."
    exit 2
fi
if [ ! -f "$BACKUP" ]; then
    echo "ABORT: full system backup missing: $BACKUP"
    exit 2
fi
echo "  backup      : OK"
ls -la "$BACKUP"

# --- read the current byte -------------------------------------------------
echo "=== reading current byte ==="
$BB dd if="$BLK" of="$TMP" bs=1 skip="$PHYS_OFFSET" count=1 2>&1
echo -n "  current byte: "
$BB od -An -tx1 "$TMP"

# --- verify it is still the original 0x01 ----------------------------------
$BB printf '\001' > "$ONE"
if ! $BB cmp -s "$TMP" "$ONE"; then
    echo "ABORT: byte at offset is not 0x01. Wrong offset or already patched?"
    exit 3
fi
echo "  sanity      : byte is 0x01 (original), safe to proceed"

if [ "$DRY_RUN" = "1" ]; then
    echo "=== DRY RUN: no write performed ==="
    echo "  would run: dd if=$ZERO of=$BLK bs=1 seek=$PHYS_OFFSET count=1 conv=notrunc"
    rm -f "$TMP" "$ONE"
    exit 0
fi

# --- write 0x00 ------------------------------------------------------------
$BB printf '\000' > "$ZERO"
echo "=== writing 0x00 ==="
$BB dd if="$ZERO" of="$BLK" bs=1 seek="$PHYS_OFFSET" count=1 conv=notrunc 2>&1
echo "  write_rc=$?"

# --- read back -------------------------------------------------------------
$BB dd if="$BLK" of="$TMP" bs=1 skip="$PHYS_OFFSET" count=1 2>&1
echo -n "  verify byte: "
$BB od -An -tx1 "$TMP"
if ! $BB cmp -s "$TMP" "$ZERO"; then
    echo "ERROR: verify failed. RESTORE FROM BACKUP IMMEDIATELY."
    exit 4
fi
echo "=== OK: patch written. REBOOT the TV to take effect. ==="
rm -f "$TMP" "$ZERO" "$ONE"
