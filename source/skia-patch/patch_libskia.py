#!/usr/bin/env python3
"""One-byte binary patch for Letv S50 Air (Android 4.3) libskia.so.

Problem
-------
SkWEBPImageDecoder::setDecodeConfig() ends with an unconditional

    mov r1, #1
    bl  SkBitmap::setIsOpaque

so EVERY WebP bitmap decoded through BitmapFactory is flagged opaque.
The decoder itself is fine: for SkBitmap::kARGB_8888_Config it sets
WebPDecBuffer.colorspace = MODE_RGBA (1), stride = 4*width and
size = rowBytes*height, i.e. libwebp really writes the ALPH channel into
the pixels. Skia then throws that information away at draw/export time,
so transparent VP8X icons render as black/white blocks.

Patch
-----
Change `mov r1, #1` to `mov r1, #0` at file offset 0x1139BC (VA == file
offset for this .so's .text). Instruction length, control flow, stack
usage and relocations are unchanged: only the boolean argument differs.

    e3a01001  ->  e3a01000
    (bytes on disk: 01 10 a0 e3  ->  00 10 a0 e3)

Verified against the actual libskia.so pulled from the TV, which is
ARM (not Thumb), not stripped, 2,247,420 bytes.

Usage
-----
    python patch_libskia.py <original.so> <patched.so>
    python patch_libskia.py --verify <patched.so>

Only writes the output file. Never touches the TV.
"""
import hashlib
import os
import sys
from pathlib import Path

OFFSET = 0x1139BC
ORIG = bytes.fromhex('0110a0e3')     # mov r1, #1   (little-endian e3a01001)
PATCHED = bytes.fromhex('0010a0e3')  # mov r1, #0   (little-endian e3a01000)
EXPECTED_SIZE = 2247420


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def disasm(word_bytes):
    """Optional pretty check; falls back silently if capstone is absent."""
    try:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        for ins in md.disasm(word_bytes, OFFSET):
            return '%s %s' % (ins.mnemonic, ins.op_str)
    except Exception:
        return '(install capstone to see the instruction)'


def make(src, dst):
    orig = Path(src).read_bytes()
    if len(orig) != EXPECTED_SIZE:
        print('WARNING: size %d != expected %d. Refusing to guess an offset.' %
              (len(orig), EXPECTED_SIZE))
        print('         Re-locate setDecodeConfig in your own binary first.')
        return 2
    got = orig[OFFSET:OFFSET + 4]
    if got != ORIG:
        print('ERROR: bytes at 0x%X are %s, expected %s. Not this build.' %
              (OFFSET, got.hex(' '), ORIG.hex(' ')))
        return 1

    print('input      : %s' % src)
    print('size       : %d bytes' % len(orig))
    print('sha256     : %s' % sha256(orig))
    print('offset     : 0x%08X (VA == file offset for .text in this .so)' % OFFSET)
    print('before     : %s   %s' % (ORIG.hex(' '), disasm(ORIG)))
    print('after      : %s   %s' % (PATCHED.hex(' '), disasm(PATCHED)))

    out = bytearray(orig)
    out[OFFSET:OFFSET + 4] = PATCHED
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(out)

    check = Path(dst).read_bytes()
    diffs = [i for i, (a, b) in enumerate(zip(orig, check)) if a != b]
    print('output     : %s' % dst)
    print('diff bytes : %d %s' % (len(diffs), ['0x%X' % i for i in diffs[:8]]))
    print('sha256     : %s' % sha256(check))
    if diffs != [OFFSET]:
        print('ERROR: unexpected diff set')
        return 1
    print('OK: exactly one byte changed (0x%X: 0x01 -> 0x00).' % OFFSET)
    return 0


def verify(path):
    b = Path(path).read_bytes()
    print('file       : %s' % path)
    print('size       : %d' % len(b))
    print('sha256     : %s' % sha256(b))
    print('bytes@0x%X: %s  %s' % (OFFSET, b[OFFSET:OFFSET + 4].hex(' '),
                                  disasm(b[OFFSET:OFFSET + 4])))
    ok = b[OFFSET:OFFSET + 4] == PATCHED
    print('patched    : %s' % ('YES' if ok else 'NO (still original)'))
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--verify':
        sys.exit(verify(sys.argv[2]))
    if len(sys.argv) == 3:
        sys.exit(make(sys.argv[1], sys.argv[2]))
    print(__doc__)
    sys.exit(2)
