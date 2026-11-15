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

### `verify_libskia.py` —— 第 1 层：离线静态强校验

`--verify` 只证明「生成的文件只差 1 字节」。本脚本进一步证明**这 1 字节改在正确位置、喂给正确调用、ELF 仍可加载**：

```bash
python verify_libskia.py <original.so> <patched.so> --json report.json
```

67 项检查：ELF header / PHDR / SHDR、全 section 字节、PT_LOAD 与 `VA==off` 映射、5438 条重定位是否覆盖补丁字、dynsym 符号归属、ARM 指令 xor 语义、`bl` 目标解析、全库 `setIsOpaque` 22 个调用点的影响面、hash/reloc/exidx 等完整性元数据。实测 **67/67 通过，结论 `PATCH STRUCTURALLY VALID`**。

需要 capstone 打印反汇编（可选）：装在 `~/.workbuddy/binaries/python/envs/default`。

### `probe/` —— 第 2、3 层：不刷机的 A/B 动态验证

**不改 `/system`、不重启、不按遥控器**，直接证明补丁行为正确。核心技巧：普通 app 从 zygote fork，继承已 mmap 的系统库，`LD_LIBRARY_PATH` 无效；必须用 `app_process` 启动**非 zygote 进程**，linker 才会重新解析。另需 `ANDROID_DATA` 指向可写目录，否则 dex 无法建缓存、`app_process` 会 SIGSEGV(139)。

```bash
# 1) 编译探针 dex（javac -> D8，不需要 APK / 签名）
python probe/build_probe.py

# 2) 一键在电视上跑 A/B 并判定（自动 push dex/补丁库/样本、拉回报告）
python probe/verify_on_tv.py

# 3) 把导出 PNG 与 PC 端 ffmpeg 参考做逐像素 alpha 比对
python probe/compare_alpha.py
```

实测结果（`aerial-tools/build/patch-libskia/verify_dynamic_run.log`）：

- 对照组加载 `/system/lib/libskia.so`，实验组加载 `/data/local/tmp/skiapatch/libskia.so`（由 `/proc/self/maps` 佐证）；
- 真实 VP8X 图标 `hasAlpha` 由 `false` 变 `true`，出现 244 个半透明 + 780 个全透明像素；
- 合成棋盘 VP8X 的 `alphaSum` 从 1044480 变为 **988981，与源 PNG 精确相等**；
- 6 个不带 alpha 的样本像素 checksum A/B 完全一致，零回归；
- 逐像素比对：补丁后 alpha 与源 PNG、与 PC ffmpeg/libwebp 参考均 **0 差异**；对照组有 437 个像素错误。

完整方法与数据见 [`../../docs/08-system-patch.md`](../../docs/08-system-patch.md) 第 6 节。

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
- 补丁库**没有刷入过电视**；三层验证已证明补丁本身正确，是否刷入、走 OTA 还是裸块设备，由使用者决定。
- A/B 验证会在电视上留下 `/sdcard/Download/{skiaprobe.dex,webptest/,skiaprobe/,skiaprobe_run.sh}` 与 `/data/local/tmp/{skiapatch/,skiadroid/}`，都只是普通数据，重启后可随时删除，不影响系统。
- native 库不进 dalvik-cache，不需要重 dexopt，但 zygote 已 mmap，**写入 `/system` 后必须重启**才生效。
- 副作用：`setIsOpaque(false)` 是无条件的，所有 WebP 的 `hasAlpha()` 都会变成 `true`（像素不变，仅少一条 opaque 绘制快速路径）。
- 回退：把 `0x1139BC` 的 `00` 改回 `01`，或恢复原 so。
