#!/usr/bin/env python3
"""Build a patched mangoTV APK whose left-rail image tabs use imgFocus for the
default state too (so the RGB_565 alpha-less white stub is never displayed).

Only classes4.dex is replaced; all other 8 dex + all resources are copied
byte-for-byte. Signature is regenerated with a local key, so installing this
APK requires uninstalling the original first (app data will be lost).

This script does NOT touch the TV. Output: mango-alpha-fixed.apk
"""
import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / 'aerial-tools' / 'build'
SRC = BUILD / 'assets' / 'app' / 'mango.apk'
NEWDEX = BUILD / 'mango_dex' / 'classes4-new.dex'
HERE = Path(__file__).resolve().parent
UNSIGNED = HERE / 'mango-alpha-unsigned.apk'
SIGNED = HERE / 'mango-alpha-fixed.apk'
KEYSTORE = HERE / 'patch.jks'
JDK = BUILD / 'jdk-17.0.2' / 'bin'
KEYTOOL = str(JDK / 'keytool.exe')
JARSIGNER = str(JDK / 'jarsigner.exe')
PASS = 's50air'
TARGET = 'classes4.dex'

assert SRC.exists(), SRC
assert NEWDEX.exists(), NEWDEX

# ---- 1) rebuild zip, replacing only classes4.dex, dropping old signature ----
changed = []
with zipfile.ZipFile(SRC) as z:
    infos = z.infolist()
    with zipfile.ZipFile(UNSIGNED, 'w') as out:
        for i in infos:
            name = i.filename
            if name.upper().startswith('META-INF/'):
                continue
            data = NEWDEX.read_bytes() if name == TARGET else z.read(name)
            zi = zipfile.ZipInfo(name, date_time=i.date_time)
            zi.compress_type = i.compress_type
            zi.external_attr = i.external_attr
            zi.internal_attr = i.internal_attr
            zi.create_system = i.create_system
            out.writestr(zi, data)
            if name == TARGET:
                changed.append((name, hashlib.sha256(z.read(name)).hexdigest()[:16],
                                hashlib.sha256(data).hexdigest()[:16]))
print('rebuilt:', UNSIGNED, UNSIGNED.stat().st_size, 'bytes')
for n, a, b in changed:
    print('  replaced', n, a, '->', b)

# ---- 2) local signing key ----
if not KEYSTORE.exists():
    subprocess.run([
        KEYTOOL, '-genkeypair', '-keystore', str(KEYSTORE),
        '-alias', 'patch', '-keyalg', 'RSA', '-keysize', '2048',
        '-validity', '10000', '-storepass', PASS, '-keypass', PASS,
        '-dname', 'CN=S50Air Patch, OU=Local, O=Local, L=Local, ST=Local, C=CN',
    ], check=True, capture_output=True, text=True, errors='replace')
    print('keystore created')

# ---- 3) v1 (JAR) signature, required by Android 4.3 ----
SIGNED.unlink(missing_ok=True)
r = subprocess.run([
    JARSIGNER, '-sigalg', 'SHA1withRSA', '-digestalg', 'SHA1',
    '-keystore', str(KEYSTORE), '-storepass', PASS, '-keypass', PASS,
    '-signedjar', str(SIGNED), str(UNSIGNED), 'patch',
], capture_output=True, text=True, errors='replace')
print('jarsigner rc=', r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()[:500])
assert SIGNED.exists()

# ---- 4) static verification ----
v = subprocess.run([JARSIGNER, '-verify', '-verbose', str(SIGNED)],
                   capture_output=True, text=True, errors='replace')
_vout = (v.stdout or '') + (v.stderr or '')
print('verify rc=', v.returncode, 'jar verified:', 'jar verified' in _vout)

with zipfile.ZipFile(SRC) as a, zipfile.ZipFile(SIGNED) as b:
    bnames = set(b.namelist())
    dexes = sorted(n for n in bnames if n.endswith('.dex'))
    print('dex count:', len(dexes), dexes)
    assert len(dexes) == 9, 'dex count changed'
    diffs = []
    for n in a.namelist():
        if n.upper().startswith('META-INF/'):
            continue
        if a.read(n) != b.read(n):
            diffs.append(n)
    print('entries differing from original:', diffs)
    assert diffs == [TARGET], diffs
print('SIGNED APK READY:', SIGNED, SIGNED.stat().st_size, 'bytes')
print('\nNOTE: install requires `pm uninstall com.starcor.mango` first (different signature).')
