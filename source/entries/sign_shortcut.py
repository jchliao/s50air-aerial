"""打包 + v1(JAR) 签名: AndroidManifest.xml + classes.dex -> sourceshortcut.apk
普通自签证书 (user.x509.pem/user.key)，非平台签名。
Android 4.3 只认 v1 签名，流程与 build/sign_apk.py 一致。
"""
import base64
import hashlib
import os
import subprocess
import zipfile

WORK = os.path.dirname(os.path.abspath(__file__))
os.chdir(WORK)

# base = aapt 产出的 unsigned.apk（含官方二进制 manifest），合入 classes.dex
with zipfile.ZipFile("unsigned.apk") as z:
    base_ent = [(i.filename, i.compress_type, z.read(i.filename)) for i in z.infolist()]
ent = [e for e in base_ent if not e[0].upper().startswith("META-INF/")]
ent.append(("classes.dex", zipfile.ZIP_DEFLATED, open("classes.dex", "rb").read()))


def b64(d):
    return base64.b64encode(hashlib.sha1(d).digest()).decode()


mf = bytearray(b"Manifest-Version: 1.0\r\nCreated-By: 1.0 (SourceSign)\r\n\r\n")
secs = []
for name, _, data in ent:
    sec = ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n" % (name, b64(data))).encode()
    secs.append((name, sec))
    mf += sec
mf = bytes(mf)

sf = bytearray(("Signature-Version: 1.0\r\nCreated-By: 1.0 (SourceSign)\r\n"
                "SHA1-Digest-Manifest: %s\r\n\r\n" % b64(mf)).encode())
for name, sec in secs:
    sf += ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n" % (name, b64(sec))).encode()
sf = bytes(sf)

open("MANIFEST.MF", "wb").write(mf)
open("CERT.SF", "wb").write(sf)
subprocess.run(["openssl", "smime", "-sign", "-noattr", "-binary",
                "-in", "CERT.SF", "-signer", "user.x509.pem", "-inkey", "user.key",
                "-outform", "DER", "-md", "sha1", "-out", "CERT.RSA"], check=True)

OUT = "sourceshortcut.apk"
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
print("entries:", zipfile.ZipFile(OUT).namelist())
