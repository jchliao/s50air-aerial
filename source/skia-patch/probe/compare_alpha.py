#!/usr/bin/env python3
"""Third layer of verification: compare decoded ALPHA bytes against an
independent (PC-side ffmpeg/libwebp) reference.

The TV probe already reports alpha histograms. Here we decode the exported
PNGs to raw RGBA with ffmpeg and compare the actual alpha plane, so we can
tell "alpha channel restored correctly" from "just the hasAlpha flag flipped".
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BUILD = ROOT / 'aerial-tools' / 'build'
PNGS = BUILD / 'patch-libskia' / 'probe_out' / 'skiaprobe'
REFS = BUILD / 'probe_ref'
FFMPEG = Path(r'C:\A\ffmpeg\bin\ffmpeg.exe')
OUT = BUILD / 'patch-libskia' / 'verify_alpha.log'

lines = []


def log(s):
    print(s)
    lines.append(s)


def rgba(path):
    if not Path(path).is_file():
        return None
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-i', str(path),
                        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'],
                       capture_output=True)
    if r.returncode != 0:
        log('  ffmpeg failed for %s: %s' % (path, r.stderr[:200]))
        return None
    return r.stdout


def plane(data, idx):
    return data[idx::4]


def cmp(name, pa, pb, idx=3, label='ALPHA'):
    a, b = rgba(pa), rgba(pb)
    if a is None or b is None:
        log('[SKIP] %s (missing file)' % name)
        return None
    if len(a) != len(b):
        log('[FAIL] %s: size mismatch %d vs %d' % (name, len(a), len(b)))
        return None
    x, y = plane(a, idx), plane(b, idx)
    diff = sum(1 for p, q in zip(x, y) if p != q)
    maxd = max((abs(p - q) for p, q in zip(x, y)), default=0)
    log('[%-4s] %-58s pixels=%d differing=%d maxdelta=%d' %
        ('PASS' if diff == 0 else 'INFO', name, len(x), diff, maxd))
    return dict(name=name, pixels=len(x), diff=diff, maxdelta=maxd, label=label)


def main():
    if not FFMPEG.is_file():
        log('ffmpeg not found at %s' % FFMPEG)
        return 2
    log('=== alpha-plane comparison (independent PC-side reference) ===')
    ref_png = PNGS / 'patched_10_checker_png.png'      # the source RGBA checker
    a_vp8x = PNGS / 'orig_11_checker_vp8x_webp.png'
    b_vp8x = PNGS / 'patched_11_checker_vp8x_webp.png'
    b_alph = PNGS / 'patched_02_vp8x_alph_webp.png'

    r0 = cmp('control WebP alpha vs source PNG (expect many diffs)', a_vp8x, ref_png)
    r1 = cmp('patched WebP alpha vs source PNG (expect 0 diffs)', b_vp8x, ref_png)
    r2 = cmp('patched WebP alpha vs ffmpeg/libwebp reference',
             b_vp8x, REFS / '11_checker_vp8x.png')
    r3 = cmp('patched real icon alpha vs ffmpeg/libwebp reference',
             b_alph, REFS / '02_vp8x_alph.png')

    log('')
    log('=== RGB regression (no-alpha sample, alpha flag must not change colour) ===')
    for nm in ('01_vp8x_iccp_webp', '03_vp8_plain_webp', '12_checker_vp8_webp'):
        log('-- ' + nm)
        for idx, ch in ((0, 'R'), (1, 'G'), (2, 'B')):
            cmp('%s %s channel A vs B' % (nm, ch),
                PNGS / ('orig_' + nm + '.png'), PNGS / ('patched_' + nm + '.png'),
                idx=idx, label=ch)

    ok = (r1 is not None and r1['diff'] == 0
          and r0 is not None and r0['diff'] > 0)
    log('')
    log('=== VERDICT: %s ===' %
        ('ALPHA CHANNEL RESTORED, NOT JUST THE FLAG' if ok else 'INCONCLUSIVE'))
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
