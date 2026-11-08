import hashlib
import base64
import os
import subprocess
import sys
import zipfile

BASE = sys.argv[1]
DEX = sys.argv[2]
OUTNAME = sys.argv[3]

WORK = os.path.dirname(os.path.abspath(__file__))
os.chdir(WORK)
OUT = os.path.join(WORK, OUTNAME)

ent = []
with zipfile.ZipFile(BASE) as z:
    for info in z.infolist():
        if info.filename.upper().startswith("META-INF/"):
            continue
        ent.append((info.filename, info.compress_type, z.read(info.filename)))

dex = open(DEX, "rb").read()
ent = [e for e in ent if e[0] != "classes.dex"]
ent.append(("classes.dex", zipfile.ZIP_DEFLATED, dex))
print("apk entries:", [e[0] for e in ent])


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

subprocess.run([
    "openssl", "smime", "-sign", "-noattr", "-binary",
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
print("CERT.RSA:", os.path.getsize("CERT.RSA"), "bytes")

# self check
with zipfile.ZipFile(OUT) as z:
    print("zip ok:", z.testzip() is None)
