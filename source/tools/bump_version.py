"""把 APK AndroidManifest.xml 里的 versionCode 抬高（并重签名），
让 /data/app 的同名包在重启扫描时不被 /system/app 的旧版覆盖掉。
"""
import base64
import hashlib
import os
import struct
import subprocess
import sys
import zipfile

BASE = sys.argv[1]
OUTNAME = sys.argv[2]
NEW_VC = int(sys.argv[3])

WORK = os.path.dirname(os.path.abspath(__file__))
os.chdir(WORK)
OUT = os.path.join(WORK, OUTNAME)

ATTR_VERSION_CODE = 0x0101021b
TYPE_INT_DEC = 0x10


def parse_string_pool(data, off):
    ctype, hsize, csize = struct.unpack("<HHI", data[off:off + 8])
    count, style_count, flags, strings_start, styles_start = struct.unpack(
        "<IIIII", data[off + 8:off + 28])
    utf8 = (flags & 0x100) != 0
    offsets = struct.unpack("<%dI" % count, data[off + 28:off + 28 + 4 * count])
    base = off + strings_start
    end = off + csize
    out = []
    for o in offsets:
        p = base + o
        if p >= end:
            out.append("")
            continue
        if utf8:
            n = data[p]
            p += 2 if (n & 0x80) else 1
            n2 = data[p]
            if n2 & 0x80:
                n2 = ((n2 & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                p += 1
            out.append(data[p:p + n2].decode("utf-8", "replace"))
        else:
            n = struct.unpack("<H", data[p:p + 2])[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack("<H", data[p:p + 2])[0]
                p += 2
            out.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
    return out


def read_version_code(data):
    total = struct.unpack("<I", bytes(data[4:8]))[0]
    off = 8
    strings = None
    resmap = []
    cur = None
    while off + 8 <= total:
        ctype, hsize, csize = struct.unpack("<HHI", bytes(data[off:off + 8]))
        if csize <= 0:
            break
        if ctype == 0x0001:
            strings = parse_string_pool(data, off)
        elif ctype == 0x0180:
            n = (csize - hsize) // 4
            resmap = list(struct.unpack("<%dI" % n, bytes(data[off + hsize:off + hsize + 4 * n])))
        elif ctype == 0x0102 and strings is not None:
            name_idx = struct.unpack("<I", bytes(data[off + 8 + 12:off + 8 + 16]))[0]
            elem = strings[name_idx] if name_idx < len(strings) else ""
            if elem == "manifest":
                attr_start, attr_size, attr_count = struct.unpack("<HHH", bytes(data[off + 24:off + 30]))
                aoff = off + 16 + attr_start
                for i in range(attr_count):
                    p = aoff + i * attr_size
                    ns_i, nm_i, raw_i = struct.unpack("<III", bytes(data[p:p + 12]))
                    rid = resmap[nm_i] if nm_i < len(resmap) else 0
                    if rid == ATTR_VERSION_CODE:
                        return struct.unpack("<I", bytes(data[p + 16:p + 20]))[0], p
        off += csize
    raise SystemExit("versionCode attribute not found")


def patch_manifest(data):
    data = bytearray(data)
    if data[:4] != b"\x03\x00\x08\x00":
        raise SystemExit("not a binary AXML manifest")
    old, p = read_version_code(data)
    print("old versionCode = %d" % old)
    struct.pack_into("<H", data, p + 12, 8)   # size
    data[p + 15] = TYPE_INT_DEC               # type
    struct.pack_into("<I", data, p + 16, NEW_VC)
    print("new versionCode = %d" % NEW_VC)
    return bytes(data)


ent = []
manifest_patched = None
with zipfile.ZipFile(BASE) as z:
    for info in z.infolist():
        if info.filename.upper().startswith("META-INF/"):
            continue
        d = z.read(info.filename)
        if info.filename == "AndroidManifest.xml":
            d = patch_manifest(d)
            manifest_patched = d
        ent.append((info.filename, info.compress_type, d))

if manifest_patched is None:
    raise SystemExit("no AndroidManifest.xml in apk")


def b64(d):
    return base64.b64encode(hashlib.sha1(d).digest()).decode()


mf = bytearray(b"Manifest-Version: 1.0\r\nCreated-By: 1.0 (PlatformSign)\r\n\r\n")
secs = []
for name, _, data in ent:
    sec = ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n" % (name, b64(data))).encode()
    secs.append((name, sec))
    mf += sec
mf = bytes(mf)

sf = bytearray(("Signature-Version: 1.0\r\nCreated-By: 1.0 (PlatformSign)\r\n"
                "SHA1-Digest-Manifest: %s\r\n\r\n" % b64(mf)).encode())
for name, sec in secs:
    sf += ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n" % (name, b64(sec))).encode()
sf = bytes(sf)

open("MANIFEST.MF", "wb").write(mf)
open("CERT.SF", "wb").write(sf)

openssl = "openssl"
for cand in ("openssl", "C:/Program Files/Git/usr/bin/openssl.exe"):
    try:
        subprocess.run([cand, "version"], capture_output=True, check=True)
        openssl = cand
        break
    except Exception:
        continue

subprocess.run([
    openssl, "smime", "-sign", "-noattr", "-binary",
    "-in", "CERT.SF",
    "-signer", "platform.x509.pem", "-inkey", "platform.key",
    "-outform", "DER", "-md", "sha1", "-out", "CERT.RSA",
], check=True)

with zipfile.ZipFile(OUT, "w") as z:
    for nm, fn in (("META-INF/MANIFEST.MF", "MANIFEST.MF"),
                   ("META-INF/CERT.SF", "CERT.SF"),
                   ("META-INF/CERT.RSA", "CERT.RSA")):
        zi = zipfile.ZipInfo(nm, date_time=(2018, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, open(fn, "rb").read())
    for name, ct, data in ent:
        zi = zipfile.ZipInfo(name, date_time=(2018, 1, 1, 0, 0, 0))
        zi.compress_type = ct
        zi.external_attr = 0o644 << 16
        z.writestr(zi, data)

print("signed apk:", OUT, os.path.getsize(OUT), "bytes")
with zipfile.ZipFile(OUT) as z:
    print("zip ok:", z.testzip() is None)
