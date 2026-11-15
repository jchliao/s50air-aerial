#!/usr/bin/env python3
"""Render a BEFORE/AFTER comparison from the real A/B probe PNGs.

Uses ffmpeg to read each PNG as raw RGBA, composites onto a checkerboard
(so transparency is visible), and writes a self-contained RGB PNG with
pure-stdlib zlib. No Pillow / no external Python packages.
"""
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BUILD = ROOT / 'aerial-tools' / 'build'
PNGS = BUILD / 'patch-libskia' / 'probe_out' / 'skiaprobe'
FFMPEG = Path(r'C:\A\ffmpeg\bin\ffmpeg.exe')
OUT = BUILD / 'patch-libskia' / 'patch-effect-compare.png'

W, H = 700, 580

# 5x7 uppercase font, one 5-bit row per line
F = {
 'A': (0x0E,0x11,0x11,0x1F,0x11,0x11,0x11), 'B': (0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E),
 'C': (0x0F,0x10,0x10,0x10,0x10,0x10,0x0F), 'D': (0x1E,0x11,0x11,0x11,0x11,0x11,0x1E),
 'E': (0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F), 'F': (0x1F,0x10,0x10,0x1E,0x10,0x10,0x10),
 'G': (0x0F,0x10,0x10,0x17,0x11,0x11,0x0F), 'H': (0x11,0x11,0x11,0x1F,0x11,0x11,0x11),
 'I': (0x1F,0x04,0x04,0x04,0x04,0x04,0x1F), 'J': (0x07,0x02,0x02,0x02,0x02,0x12,0x0C),
 'K': (0x11,0x12,0x14,0x18,0x14,0x12,0x11), 'L': (0x10,0x10,0x10,0x10,0x10,0x10,0x1F),
 'M': (0x11,0x1B,0x15,0x15,0x11,0x11,0x11), 'N': (0x11,0x19,0x15,0x13,0x11,0x11,0x11),
 'O': (0x0E,0x11,0x11,0x11,0x11,0x11,0x0E), 'P': (0x1E,0x11,0x11,0x1E,0x10,0x10,0x10),
 'Q': (0x0E,0x11,0x11,0x11,0x15,0x12,0x0D), 'R': (0x1E,0x11,0x11,0x1E,0x14,0x12,0x11),
 'S': (0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E), 'T': (0x1F,0x04,0x04,0x04,0x04,0x04,0x04),
 'U': (0x11,0x11,0x11,0x11,0x11,0x11,0x0E), 'V': (0x11,0x11,0x11,0x11,0x11,0x0A,0x04),
 'W': (0x11,0x11,0x11,0x15,0x15,0x1B,0x11), 'X': (0x11,0x11,0x0A,0x04,0x0A,0x11,0x11),
 'Y': (0x11,0x11,0x0A,0x04,0x04,0x04,0x04), 'Z': (0x1F,0x01,0x02,0x04,0x08,0x10,0x1F),
 '0': (0x0E,0x11,0x13,0x15,0x19,0x11,0x0E), '1': (0x04,0x0C,0x04,0x04,0x04,0x04,0x0E),
 '2': (0x0E,0x11,0x01,0x02,0x04,0x08,0x1F), '3': (0x1F,0x02,0x04,0x02,0x01,0x11,0x0E),
 '4': (0x02,0x06,0x0A,0x12,0x1F,0x02,0x02), '5': (0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E),
 '6': (0x06,0x08,0x10,0x1E,0x11,0x11,0x0E), '7': (0x1F,0x01,0x02,0x04,0x08,0x08,0x08),
 '8': (0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E), '9': (0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C),
 ' ': (0,0,0,0,0,0,0), '.': (0,0,0,0,0,0x0C,0x0C), ':': (0,0x0C,0x0C,0,0x0C,0x0C,0),
 '/': (0x01,0x01,0x02,0x04,0x08,0x10,0x10), '-': (0,0,0,0x1F,0,0,0),
 '=': (0,0x1F,0,0x1F,0,0,0), '(': (0x02,0x04,0x08,0x08,0x08,0x04,0x02),
 ')': (0x08,0x04,0x02,0x02,0x02,0x04,0x08), '+': (0,0x04,0x04,0x1F,0x04,0x04,0),
 ',': (0,0,0,0,0x0C,0x0C,0x04), '!': (0x04,0x04,0x04,0x04,0x04,0,0x04),
 '?': (0x0E,0x11,0x01,0x02,0x04,0,0x04), '%': (0x19,0x1A,0x02,0x04,0x08,0x0B,0x13),
}


def png_size(p):
    b = Path(p).read_bytes()
    return struct.unpack('>II', b[16:24])


def rgba(p):
    w, h = png_size(p)
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-i', str(p),
                        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'],
                       capture_output=True)
    if r.returncode != 0 or len(r.stdout) != w * h * 4:
        raise RuntimeError('decode failed: %s (%d bytes, expect %d)' %
                           (p, len(r.stdout), w * h * 4))
    return r.stdout, w, h


def fill(buf, x, y, w, h, c):
    for j in range(y, min(y + h, H)):
        for i in range(x, min(x + w, W)):
            o = (j * W + i) * 3
            buf[o], buf[o + 1], buf[o + 2] = c


def checker(buf, x, y, w, h, cell=20):
    for j in range(h):
        for i in range(w):
            c = 205 if ((i // cell + j // cell) % 2 == 0) else 240
            o = ((y + j) * W + x + i) * 3
            buf[o], buf[o + 1], buf[o + 2] = c, c, c


def blit(buf, src, sw, sh, x, y, dw, dh):
    """Nearest-neighbour scale + alpha composite onto the checkerboard."""
    for j in range(dh):
        sy = j * sh // dh
        for i in range(dw):
            sx = i * sw // dw
            s = (sy * sw + sx) * 4
            a = src[s + 3] / 255.0
            if a == 0:
                continue
            o = ((y + j) * W + x + i) * 3
            for k in range(3):
                buf[o + k] = int(buf[o + k] * (1 - a) + src[s + k] * a)


def text(buf, s, x, y, scale=2, c=(255, 255, 255)):
    cx = x
    for ch in s.upper():
        rows = F.get(ch, F['?'])
        for r in range(7):
            for col in range(5):
                if rows[r] & (1 << (4 - col)):
                    fill(buf, cx + col * scale, y + r * scale, scale, scale, c)
        cx += 6 * scale


def chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data +
            struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))


def main():
    if not FFMPEG.is_file():
        print('ffmpeg missing')
        return 2
    buf = bytearray(W * H * 3)
    fill(buf, 0, 0, W, H, (18, 20, 24))

    text(buf, 'LIBSKIA.SO WEBP ALPHA PATCH', 20, 18, 3, (235, 238, 242))
    text(buf, 'BEFORE: ORIGINAL', 40, 66, 2, (255, 130, 120))
    text(buf, 'AFTER: PATCHED', 460, 66, 2, (130, 225, 150))

    # row 1: the real broken icon from the TV cache
    text(buf, 'REAL ICON 32X32 X5', 40, 92, 1, (170, 175, 185))
    for x in (40, 460):
        checker(buf, x, 112, 200, 200)
    for name, x in (('orig_02_vp8x_alph_webp.png', 60),
                    ('patched_02_vp8x_alph_webp.png', 480)):
        src, sw, sh = rgba(PNGS / name)
        blit(buf, src, sw, sh, x, 132, 160, 160)

    # row 2: synthetic checker with a known semi-transparent circle
    text(buf, 'ALPHA CHECKER 64X64 X3', 40, 326, 1, (170, 175, 185))
    for x in (40, 460):
        checker(buf, x, 346, 200, 200)
    for name, x in (('orig_11_checker_vp8x_webp.png', 44),
                    ('patched_11_checker_vp8x_webp.png', 464)):
        src, sw, sh = rgba(PNGS / name)
        blit(buf, src, sw, sh, x, 350, 192, 192)

    text(buf, 'ALPHA=255  TRANSPARENT AREA SHOWS AS BLACK BLOCK', 40, 556, 1, (255, 130, 120))
    text(buf, 'ALPHA OK  BACKGROUND VISIBLE', 460, 556, 1, (130, 225, 150))

    rows = b''.join(b'\x00' + bytes(buf[y * W * 3:(y + 1) * W * 3])
                    for y in range(H))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(rows, 9))
           + chunk(b'IEND', b''))
    OUT.write_bytes(png)
    print('wrote %s (%d bytes)' % (OUT, len(png)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
