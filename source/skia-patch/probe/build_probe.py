#!/usr/bin/env python3
"""Build the A/B probe dex (javac -> D8). No aapt / no APK signing needed:
app_process loads a bare classes.dex through CLASSPATH.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
BUILD = os.path.join(ROOT, 'aerial-tools', 'build')
OUTDIR = os.path.join(BUILD, 'patch-libskia')

JAVAC = os.path.join(BUILD, 'jdk-17.0.2', 'bin', 'javac.exe')
JAVA = os.path.join(BUILD, 'jdk-17.0.2', 'bin', 'java.exe')
R8 = os.path.join(BUILD, 'shortcut', 'tools', 'r8.jar')
ANDROID_JAR = os.path.join(BUILD, 'android-4.3.1', 'android.jar')
SRC = os.path.join(HERE, 'ProbeMain.java')
CLASSES = os.path.join(OUTDIR, 'probe_classes')
DEX = os.path.join(OUTDIR, 'skiaprobe.dex')

for p in (JAVAC, JAVA, R8, ANDROID_JAR, SRC):
    if not os.path.isfile(p):
        print('MISSING: %s' % p)
        sys.exit(1)

os.makedirs(OUTDIR, exist_ok=True)
if os.path.isdir(CLASSES):
    shutil.rmtree(CLASSES)
os.makedirs(CLASSES)

r = subprocess.run([JAVAC, '-encoding', 'UTF-8', '-source', '8', '-target', '8',
                    '-nowarn', '-classpath', ANDROID_JAR, '-d', CLASSES, SRC],
                   capture_output=True, text=True)
if r.returncode != 0:
    print('JAVAC FAIL\n' + r.stderr[:2000])
    sys.exit(1)
print('javac ok')

classes = []
for root, _, files in os.walk(CLASSES):
    for f in files:
        if f.endswith('.class'):
            classes.append(os.path.join(root, f))

r = subprocess.run([JAVA, '-cp', R8, 'com.android.tools.r8.D8', '--min-api', '18',
                    '--lib', ANDROID_JAR, '--output', OUTDIR] + classes,
                   capture_output=True, text=True)
if r.returncode != 0:
    print('D8 FAIL\n' + r.stdout[:800] + '\n' + r.stderr[:1500])
    sys.exit(1)

# D8 writes classes.dex next to --output; give it the name the runner expects
built = os.path.join(OUTDIR, 'classes.dex')
if not os.path.isfile(built):
    print('D8 did not produce classes.dex')
    sys.exit(1)
shutil.move(built, DEX)
print('dex ok: %s (%d bytes)' % (DEX, os.path.getsize(DEX)))
