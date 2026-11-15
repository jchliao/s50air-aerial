#!/usr/bin/env python3
"""Build the two in-place (signature-preserving) patch APKs for the installed
mangoTV 5.16.3 build.

Why Java: Python's zipfile rejects APKs whose zipalign/data-descriptor entries
have an empty local-header filename ("File name in directory ... and header
b'' differ"). java.util.zip.ZipFile reads via the central directory and is fine.

Usage:
  python build_argb_inplace.py \
      --baseline aerial-tools/build/mango_skin/tv_mango_ondevice.apk \
      --dex-dir aerial-tools/build/mango_dex/tv
"""
import argparse, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JDK = ROOT / 'aerial-tools' / 'build' / 'jdk-17.0.2' / 'bin'
OUT = ROOT / 'aerial-tools' / 'build' / 'mango_skin'

VARIANTS = [
    ('classes4-argb.dex', 'mango-argb-inplace.apk', 'global DecodeFormat -> ARGB_8888'),
    ('classes4-argbplus.dex', 'mango-argb-nav-inplace.apk', 'ARGB_8888 + navigate icon -> imgFocus'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', default=str(OUT / 'tv_mango_ondevice.apk'))
    ap.add_argument('--dex-dir', default=str(ROOT / 'aerial-tools' / 'build' / 'mango_dex' / 'tv'))
    a = ap.parse_args()
    base, dexdir = Path(a.baseline), Path(a.dex_dir)
    classes = HERE / 'rezip' / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    src = HERE / 'rezip' / 'Rezip.java'
    javac, java = JDK / 'javac.exe', JDK / 'java.exe'
    r = subprocess.run([str(javac), '-d', str(classes), str(src)],
                       capture_output=True, text=True)
    if r.returncode:
        print('javac failed:', r.stderr[:800])
        return 1
    for dex, dst, desc in VARIANTS:
        d, o = dexdir / dex, OUT / dst
        if not d.is_file():
            print('MISSING dex:', d, '(run baksmali + smali rebuild first)')
            continue
        r = subprocess.run([str(java), '-cp', str(classes), 'Rezip',
                            str(base), str(d), str(o)],
                           capture_output=True, text=True)
        print('%-34s %s' % (dst, desc), r.stdout.strip() or r.stderr.strip()[:200])
        if o.is_file():
            print('   bytes', o.stat().st_size)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
