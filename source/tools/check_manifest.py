"""检查 APK 的 AndroidManifest 中 application 的 persistent / versionCode / versionName"""
import struct
import sys
import zipfile

ATTR_PERSISTENT = 0x0101000D
ATTR_VERSION_CODE = 0x0101021B
ATTR_VERSION_NAME = 0x0101021C
ATTR_NAME = 0x01010003


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


def walk(data):
    """遍历所有 start tag，返回 (tag_name, {attr_id: (name, raw, type, data)})"""
    if data[:4] != b"\x03\x00\x08\x00":
        raise SystemExit("not binary AXML")
    total = struct.unpack("<I", bytes(data[4:8]))[0]
    pool = None
    pos = 8
    res = []
    while pos < total:
        ctype, hsize, csize = struct.unpack("<HHI", data[pos:pos + 8])
        if csize <= 0:
            break
        if ctype == 0x0001:
            pool = parse_string_pool(data, pos)
        elif ctype == 0x0180:  # resource map
            pass
        elif ctype == 0x0102:  # start tag
            ext = pos + 16
            ns_i, name_i, attribute_start, attribute_size, attribute_count = struct.unpack(
                "<IIHHH", data[ext:ext + 14])
            tag = pool[name_i] if pool and name_i < len(pool) else "?"
            attrs = {}
            attr_base = ext + attribute_start
            for i in range(attribute_count):
                a = attr_base + i * attribute_size
                an = struct.unpack("<I", data[a + 4:a + 8])[0]
                araw = struct.unpack("<I", data[a + 8:a + 12])[0]
                atype = data[a + 15]
                adata = struct.unpack("<I", data[a + 16:a + 20])[0]
                aname = pool[an] if pool and an < len(pool) else "?"
                raw_s = pool[araw] if pool and 0 < araw < len(pool) else None
                attrs[aname] = (atype, adata, raw_s)
            res.append((tag, attrs))
        pos += csize
    return res


def check(path):
    z = zipfile.ZipFile(path)
    data = z.read("AndroidManifest.xml")
    print("=" * 60)
    print(path)
    print("  apk entries:", len(z.namelist()))
    tags = walk(data)
    for tag, attrs in tags:
        if tag not in ("manifest", "application"):
            continue
        print("  [%s]" % tag)
        for k, (atype, adata, raw_s) in attrs.items():
            if atype == 0x03:
                val = raw_s
            elif atype == 0x12:
                val = "true" if adata else "false"
            else:
                val = adata
            print("     %-22s type=0x%02x value=%s" % (k, atype, val))
    # 专门报 persistent
    for tag, attrs in tags:
        if tag == "application":
            p = attrs.get("persistent")
            if p:
                print("  >>> persistent =", "TRUE" if p[1] else "FALSE", "(type 0x%02x data %d)" % (p[0], p[1]))
            else:
                print("  >>> persistent 属性不存在")
            n = attrs.get("name")
            if n:
                print("  >>> application.name =", n[2] if n[2] else n[1])
            break


for f in sys.argv[1:]:
    check(f)
