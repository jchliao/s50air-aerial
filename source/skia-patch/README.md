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

### `probe/make_effect_compare.py` —— 效果对比图

把 A/B 导出的**真实解码像素**合成到灰白棋盘背景（用于显示透明），生成补丁前后对比图。纯标准库 + ffmpeg 读 PNG，无需 Pillow。产物 `aerial-tools/build/patch-libskia/patch-effect-compare.png`，仓库副本 `docs/images/libskia-patch-effect.png`。

### `flash_via_block.sh` + `flash_on_tv.py` —— 刷入（默认 dry-run）

**OTA 与「改内存」两条路都已实测否决，推荐直接对裸块设备写 1 字节。** 完整证据与操作手册见 [`../../docs/09-flash-decision.md`](../../docs/09-flash-decision.md)。

实测常量（本机、本分区，勿套用到别的机器）：

```
system 分区          /dev/block/mmcblk0p9   512 MB, system:system 0660
libskia.so 物理起始  30818304  (0x1D64000)  整文件与备份逐字节相同
补丁点物理偏移        31947196  (0x1E779BC)  = 起始 + 0x1139BC
原 8 字节             01 10 a0 e3 90 7a fd eb
uid1000 写权限        test -w = 0, dd count=0 = 0
```

```bash
# ① 整盘备份（512MB，留在电视 sdcard；不要 pull，0.5MB/s 太慢）
python flash_on_tv.py --mode backup

# ② 干跑：只校验，不写任何字节（已实测 DRY_RUN_OK）
python flash_on_tv.py --mode dry

# ③ 确认无误后才写 1 字节；需要显式二次确认
python flash_on_tv.py --mode apply --confirm-write-system

# ④ 手动重启电视（脚本不会自动重启、不会按任何遥控器按键）

# 回退
python flash_on_tv.py --mode rollback --confirm-write-system
```

电视端脚本会独立校验 uid=1000、块设备可写、ELF 锚点、补丁点前后 8 字节，先备份所在 4K 块，写入后 `sync` 并**从块设备读回**比对（不能从 `/system/lib/` 读，page cache 可能仍旧值）。`apply` 前 PC 端还会检查 512MB 整盘备份是否存在。

## 注意

- **本目录不含任何私钥**。OTA 路线用的 AOSP 公开 `testkey.pk8` 来自 `aosp-mirror/platform_build` 的 `android-4.3_r1` 分支；实测表明 OTA 通道并不合适（recovery 是 MStar 私有镜像），见 `docs/09`。
- 补丁库**没有刷入过电视**：三层验证证明补丁本身正确，刷入脚本已实测 `DRY_RUN_OK`，但 `apply` 尚未执行。是否写入 `/system` 由使用者决定。
- `busybox grep` 不支持 `-b`；toolbox `grep -b` 给的是行偏移。物理偏移必须靠「拉回 dump + 本地字节级扫描 + 4K 对齐 / ELF / 整文件比对」确认，不能靠 grep 直接算。
- A/B 验证会在电视上留下 `/sdcard/Download/{skiaprobe.dex,webptest/,skiaprobe/,skiaprobe_run.sh}` 与 `/data/local/tmp/{skiapatch/,skiadroid/}`，都只是普通数据，重启后可随时删除，不影响系统。
- native 库不进 dalvik-cache，不需要重 dexopt，但 zygote 已 mmap，**写入 `/system` 后必须重启**才生效。
- 副作用：`setIsOpaque(false)` 是无条件的，所有 WebP 的 `hasAlpha()` 都会变成 `true`（像素不变，仅少一条 opaque 绘制快速路径）。
- 回退：把 `0x1139BC` 的 `00` 改回 `01`，或恢复原 so。
