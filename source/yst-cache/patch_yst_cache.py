#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
不重新打包、不重签、不卸载：修复小电视 com.xiaodianshi.tv.yst 的部分图标不显示。

原理（详见 ../../docs/06-vp8x-icon-cache.md）
  1) 图标大多由网络下发，缓存在 sdcard 的 Fresco 磁盘缓存里
     (/sdcard/Android/data/com.xiaodianshi.tv.yst/cache/ImagePipeLine/v2.ols100.1/*/*.cnt)。
     这些是普通文件，与 APK 签名无关，改它不会触发
     PackageParser.collectCertificates 的逐条 SHA1 校验。
  2) Android 的 BitmapFactory 按数据魔数判断格式、不看扩展名，因此
     文件名保持 .cnt 不变、只替换内容即可。
  3) 出问题的都是 WebP VP8X 扩展容器里的图标。注意：系统 Skia 本身能解 VP8X
     （平台签名探针实测 BitmapFactory.decodeFile() 全部成功），所以这**不是系统缺陷**，
     更可能是老版本 Fresco / app native 解码链路对 VP8X 的处理有问题。
     把容器退化成最简单的 VP8 后，全链路都能正常吃下去。
     本机缓存 454 个文件：VP8X 268 / 裸 VP8 153 / PNG 32 / JPEG 1。
     VP8X 内部分三种：
        ICCP + VP8       154  -> 无损降级为裸 VP8（丢弃 ICC 色彩块，VP8 码流原样保留）
        ALPH + VP8       111  -> 带透明通道，重编码为 RGBA PNG
        ICCP+ALPH+VP8      3  -> 同上
     裸 VP8 和 PNG/JPEG 本来就正常，保持不动，避免缓存体积膨胀触发 LRU 淘汰。

用法
  python patch_yst_cache.py                 # 智能修复（默认）
  python patch_yst_cache.py --strategy=png-all   # 全部 WebP 转 PNG（体积大，仅排障用）
  python patch_yst_cache.py --restore      # 从 tmpimg/pipe.bak 还原成原始缓存

依赖：ffmpeg（默认从 PATH 找，可用 FFMPEG 环境变量指定）
流程：PC 端 adb pull 整个 ImagePipeLine 到 tmpimg/pipe -> 本脚本 -> adb push 回电视
可用 YST_CACHE_DIR 覆盖缓存目录（默认 <脚本目录>/tmpimg/pipe）。
"""
import os
import sys
import shutil
import struct
import subprocess
import collections

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("YST_CACHE_DIR", os.path.join(ROOT, "tmpimg", "pipe"))
BAK = SRC + ".bak"
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def kind(d):
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
        return "webp-" + d[12:16].decode("latin1").strip()
    if d[:8] == PNG_MAGIC:
        return "png"
    if d[:2] == b"\xff\xd8":
        return "jpeg"
    if d[:4] == b"GIF8":
        return "gif"
    return "other"


def vp8x_flags(d):
    return d[20] if len(d) > 20 else 0


def has_alpha(d):
    return bool(vp8x_flags(d) & 0x10)


def downgrade(d):
    """把 VP8X 容器无损降级为简单 VP8/VP8L 容器：抽出图像 chunk 重组 RIFF。
    不重新编码，VP8 码流字节完全不变，体积几乎不变。"""
    p = 30                      # 12 RIFF头 + 8 VP8X头 + 10 VP8X数据
    while p + 8 <= len(d):
        four = d[p:p + 4]
        sz = struct.unpack("<I", d[p + 4:p + 8])[0]
        if sz < 0 or p + 8 + sz > len(d):
            return None
        if four in (b"VP8 ", b"VP8L"):
            data = d[p + 8:p + 8 + sz]
            pad = b"\x00" if (sz & 1) else b""
            riff_size = 4 + 8 + sz + len(pad)
            return (b"RIFF" + struct.pack("<I", riff_size) + b"WEBP"
                    + four + struct.pack("<I", sz) + data + pad)
        p += 8 + sz + (sz & 1)
    return None


def to_png(src, dst):
    try:
        r = subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-i", src,
             "-pix_fmt", "rgba", dst],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if r.returncode != 0:
            return False, r.stderr.decode("latin1", "replace").strip()[:120]
        with open(dst, "rb") as f:
            d = f.read()
        return (d[:8] == PNG_MAGIC), ("输出不是 PNG" if d[:8] != PNG_MAGIC else "")
    except Exception as e:
        return False, str(e)[:120]


def main():
    restore = "--restore" in sys.argv
    strategy = "smart"
    for a in sys.argv:
        if a.startswith("--strategy="):
            strategy = a.split("=", 1)[1]

    if not os.path.isdir(SRC):
        sys.exit("找不到缓存目录: " + SRC)

    if restore:
        if not os.path.isdir(BAK):
            sys.exit("没有备份: " + BAK)
        n = 0
        for dp, dn, fn in os.walk(BAK):
            for f in fn:
                s = os.path.join(dp, f)
                t = os.path.join(SRC, os.path.relpath(s, BAK))
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copy2(s, t)
                n += 1
        print("已还原 %d 个原始缓存文件" % n)
        return

    if not os.path.isdir(BAK):
        shutil.copytree(SRC, BAK)
        print("已备份原缓存 -> " + BAK)
    else:
        print("备份已存在，跳过: " + BAK)

    # 清掉上一次中断遗留的临时输出，避免 os.walk 快照里出现已被删除的文件
    cleaned = 0
    for dp, dn, fn in os.walk(SRC):
        for name in fn:
            if name.endswith((".cnt.png", ".cnt.new")):
                os.remove(os.path.join(dp, name))
                cleaned += 1
    if cleaned:
        print("清理临时残留 %d 个" % cleaned)

    stat = collections.Counter()
    before = after = 0
    failures = []

    for dp, dn, fn in os.walk(SRC):
        for name in fn:
            if name.endswith((".cnt.png", ".cnt.new")):
                continue
            p = os.path.join(dp, name)
            if not os.path.isfile(p):
                continue
            with open(p, "rb") as f:
                d = f.read()
            k = kind(d)
            stat[k] += 1
            before += len(d)

            new = None
            if k == "webp-VP8X":
                if strategy == "png-all" or has_alpha(d):
                    tmp = p + ".png"
                    ok, err = to_png(p, tmp)
                    if ok:
                        with open(tmp, "rb") as f:
                            new = f.read()
                        os.remove(tmp)
                        stat["to_png"] += 1
                    else:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                        failures.append((os.path.relpath(p, SRC), k, err))
                        stat["failed"] += 1
                else:
                    new = downgrade(d)
                    if new:
                        stat["downgraded"] += 1
                    else:
                        failures.append((os.path.relpath(p, SRC), k, "找不到 VP8 chunk"))
                        stat["failed"] += 1
            elif strategy == "png-all" and k.startswith("webp-"):
                tmp = p + ".png"
                ok, err = to_png(p, tmp)
                if ok:
                    with open(tmp, "rb") as f:
                        new = f.read()
                    os.remove(tmp)
                    stat["to_png"] += 1
                else:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    failures.append((os.path.relpath(p, SRC), k, err))
                    stat["failed"] += 1

            if new is not None:
                with open(p, "wb") as f:
                    f.write(new)
                after += len(new)
            else:
                after += len(d)

    print("\n=== 策略: %s ===" % strategy)
    for k, v in stat.most_common():
        print("  %-14s %d" % (k, v))
    print("  体积: %.2f MB -> %.2f MB" % (before / 1048576.0, after / 1048576.0))
    if failures:
        print("\n=== 失败明细（前 10）===")
        for f in failures[:10]:
            print(" ", f)


if __name__ == "__main__":
    main()
