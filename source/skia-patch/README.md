# skia-patch：libskia.so WebP alpha 补丁工具

修复 Letv S50 Air（Android 4.3）上「带透明通道的 WebP 小图标变黑/白块」的系统级缺陷。
完整原理见 [`../../docs/08-system-patch.md`](../../docs/08-system-patch.md)，取证报告见 `docs/07`。

## 工具

### `patch_libskia.py`

把电视上拉回的 `/system/lib/libskia.so` 打 1 字节补丁。

```bash
# 生成
python patch_libskia.py <original-libskia.so> <patched-libskia.so>

# 只校验
python patch_libskia.py --verify <patched-libskia.so>
```

行为：

- 校验输入大小 = 2,247,420 B，且 `0x1139BC` 处必须是 `01 10 a0 e3`；
- 改成 `00 10 a0 e3`（`mov r1,#1` → `mov r1,#0`，即 `SkBitmap::setIsOpaque(true)` → `false`）；
- 复查输出与输入**只差 1 字节**，否则报错；
- 可选装 capstone 来打印反汇编指令。**不连接电视、不写系统文件。**

已知哈希：

```
original  sha256  4642931be450d0f16747d2930a13aea851249ff14815abfc571f446a05bb23d7
patched   sha256  f8e4328c5fea2aef49542013386fce76f57252156059ddcaeda2fe2718ecaef7
```

### `flash_via_block.sh`

**电视端模板，默认 DRY-RUN，未执行过**。走 `/dev/block/mmcblk0p9` 裸块设备写 1 字节。
使用前必须：

1. 整盘备份 system 分区；
2. 用 `grep -a -b -o -F 'SkWEBPImageDecoder' system_full.img` 定位 so 的物理起始偏移；
3. 把 `PHYS_OFFSET` 改成 `起始 + 0x1139BC`；
4. 先保留 `DRY_RUN=1` 跑一遍，确认读出的字节是 `01`；
5. 再改 `DRY_RUN=0` 写入。

风险与回退见 `docs/08`。

## 注意

- **本目录不含任何私钥**。OTA 路线用的 AOSP 公开 `testkey.pk8` 来自 `aosp-mirror/platform_build` 的 `android-4.3_r1` 分支，需自行下载并用 openssl 模数比对后再用。
- 补丁库**没有刷入过电视**；是否刷入、走 OTA 还是裸块设备，由使用者决定。
- native 库不进 dalvik-cache，不需要重 dexopt，但 zygote 已 mmap，**必须重启**生效。
- 回退：把 `0x1139BC` 的 `00` 改回 `01`，或恢复原 so。
