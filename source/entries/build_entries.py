"""构建三个 HDMI 直达入口迷你 APK（每源一包，Aerial 按包去重所以必须独立包名）
复用本目录的工具链: javac(JDK17) -> D8 -> aapt -> openssl v1 签名(用户证书)
"""
import base64
import hashlib
import os
import shutil
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

JDK = r"..\jdk-17.0.2\bin"
AAPT = r"bt\android-8.1.0\aapt.exe"
D8 = [os.path.join(JDK, "java.exe"), "-cp", r"tools\r8.jar", "com.android.tools.r8.D8"]
JAVA = os.path.join(JDK, "javac.exe")

ENTRIES = [
    ("com.tv.hdmi1", "HDMI 1", "HDMI 1"),
    ("com.tv.hdmi2", "HDMI 2", "HDMI 2"),
    ("com.tv.hdmi3", "HDMI 3", "HDMI 3"),
]

TEMPLATE = open("entry_template/JumpActivity.java", encoding="utf-8").read()

MANIFEST_TMPL = '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="%s"
    android:versionCode="3"
    android:versionName="1.0">
    <application android:label="%s">
        <activity android:name=".JumpActivity" android:label="%s" android:exported="true"
            android:theme="@android:style/Theme.Translucent.NoTitleBar"
            android:screenOrientation="landscape">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
'''


def build_one(pkg, label, port):
    wd = os.path.join("entries", pkg)
    if os.path.exists(wd):
        shutil.rmtree(wd)
    src = os.path.join(wd, "src", *pkg.split("."))
    cls = os.path.join(wd, "classes")
    os.makedirs(src)
    os.makedirs(cls)
    open(os.path.join(src, "JumpActivity.java"), "w", encoding="utf-8").write(
        TEMPLATE.replace("PKGPLACEHOLDER", pkg).replace("PORTPLACEHOLDER", port))
    open(os.path.join(wd, "AndroidManifest.xml"), "w", encoding="utf-8").write(
        MANIFEST_TMPL % (pkg, label, label))

    r = subprocess.run([JAVA, "-encoding", "UTF-8", "-source", "8", "-target", "8",
                        "-classpath", "tools/android.jar", "-d", cls,
                        os.path.join(src, "JumpActivity.java")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("JAVAC FAIL", pkg, r.stderr[:500]); return False

    r = subprocess.run(D8 + ["--min-api", "18", "--output", wd,
                             os.path.join(cls, pkg.replace(".", "\\"), "JumpActivity.class").replace("\\", "/")],
                       shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("D8 FAIL", pkg, r.stdout[:300], r.stderr[:300]); return False

    r = subprocess.run([AAPT, "p", "-f", "-M", os.path.join(wd, "AndroidManifest.xml"),
                        "-I", "tools/android.jar", "-F", os.path.join(wd, "unsigned.apk")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("AAPT FAIL", pkg, r.stderr[:300]); return False

    # 签名 (v1, 用户证书)
    with zipfile.ZipFile(os.path.join(wd, "unsigned.apk")) as z:
        ent = [(i.filename, i.compress_type, z.read(i.filename)) for i in z.infolist()]
    ent.append(("classes.dex", zipfile.ZIP_DEFLATED,
                open(os.path.join(wd, "classes.dex"), "rb").read()))

    def b64(d):
        return base64.b64encode(hashlib.sha1(d).digest()).decode()

    mf = bytearray(b"Manifest-Version: 1.0\r\nCreated-By: 1.0 (SourceSign)\r\n\r\n")
    secs = []
    for name, _, data in ent:
        sec = ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n" % (name, b64(data))).encode()
        secs.append((name, sec)); mf += sec
    mf = bytes(mf)
    sf = bytearray(("Signature-Version: 1.0\r\nCreated-By: 1.0 (SourceSign)\r\n"
                    "SHA1-Digest-Manifest: %s\r\n\r\n" % b64(mf)).encode())
    for name, sec in secs:
        sf += ("Name: %s\r\nSHA1-Digest: %s\r\n\r\n" % (name, b64(sec))).encode()
    open("MANIFEST.MF", "wb").write(mf)
    open("CERT.SF", "wb").write(sf)
    subprocess.run(["openssl", "smime", "-sign", "-noattr", "-binary", "-in", "CERT.SF",
                    "-signer", "user.x509.pem", "-inkey", "user.key",
                    "-outform", "DER", "-md", "sha1", "-out", "CERT.RSA"], check=True)

    out = os.path.join("entries", pkg.split(".")[-1] + ".apk")
    with zipfile.ZipFile(out, "w") as z:
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
    print("built", out, os.path.getsize(out), "bytes")
    return True


ok = all(build_one(*e) for e in ENTRIES)
print("ALL OK" if ok else "SOME FAILED")
