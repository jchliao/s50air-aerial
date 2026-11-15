# 给系统打补丁：libskia.so 的 1 字节修复

> 前置阅读：[`07-system-webp-alpha.md`](07-system-webp-alpha.md)（确认系统缺陷的像素级证据）
> 状态：**补丁已通过三层验证（静态结构 / 不刷机的 A/B 动态 / 逐像素 alpha 比对），结论为「改对了」；仍未刷入电视**。本文记录靶点、补丁、验证方法与三条写入通道。

## 1. 结论

之前写「不给系统打补丁」是在「靶子不明、要改 ARM native 大段代码」的前提下。2026-11-15 直接反汇编电视上拉回的 `libskia.so` 后，结论翻案：

- 缺陷精确定位到 **1 条指令**；
- 补丁只需要改 **1 个字节**；
- 而且这台机器是 `test-keys`，**能签出系统认可的 OTA 更新包**。

所以「能不能打补丁」的答案是 **能**，剩下的只是选哪条写入通道、以及是否接受重启与刷机风险。

## 2. 逆向靶点（以实际二进制为准，不用 AOSP 源码猜）

`/system/lib/libskia.so`（2,247,420 B）是 **ELF32 ARM / ARM 指令模式 / 未 stripped**，`.text` 的虚拟地址与文件偏移相同，反汇编条件很好。

- `DT_NEEDED` 里**没有** `libwebp.so`；dynsym 里定义了 303 个 WebP/VP8 符号 → **Skia 静态链接了整套完整版 libwebp**。改 `/system/lib/libwebp.so`、`libwebpimage.so` 都打不中靶子。
- `SkWEBPImageDecoder::setDecodeConfig`（`0x11394C`）末尾：

```
001139b4  bl   SkBitmap::setConfig
001139b8  mov  r0, r8
001139bc  mov  r1, #1          <-- 靶点
001139c0  bl   SkBitmap::setIsOpaque
```

**无条件 `setIsOpaque(true)`** —— 所有经 `BitmapFactory` 解出的 WebP 都被标成不透明。

- 解码器本身没问题：`onDecode` / `onDecodeRegion` 把 `WebPDecBuffer.colorspace` 设成 **MODE_RGBA(1)**、`is_external_memory=1`、stride 与 size 按 4 字节/像素计算；静态 libwebp 里有 `VP8DecompressAlphaRows`。**alpha 确实写进了像素，是 Skia 事后把它丢了**。这与 `docs/07` 的像素级实测完全吻合。

## 3. 补丁

| 项 | 值 |
|---|---|
| 文件偏移 | `0x1139BC`（VA 相同） |
| 原 | `01 10 a0 e3` = `mov r1, #1` |
| 新 | `00 10 a0 e3` = `mov r1, #0` |
| 语义 | `setIsOpaque(true)` → `setIsOpaque(false)` |
| 原库 sha256 | `4642931be450d0f16747d2930a13aea851249ff14815abfc571f446a05bb23d7` |
| 补丁库 sha256 | `f8e4328c5fea2aef49542013386fce76f57252156059ddcaeda2fe2718ecaef7` |
| diff | 恰好 1 字节 |

指令长度、控制流、栈、重定位都不变。影响面仅限 WebP 解码（该函数只被 `SkWEBPImageDecoder` 调用）；不带 alpha 的图视觉结果不变，只是少一个 opaque 绘制优化。

工具：[`../source/skia-patch/`](../source/skia-patch/)，`patch_libskia.py` 会校验原字节、只允许这一种输入，并复查输出只差 1 字节。

## 4. 硬约束

| 检查 | 结果 |
|---|---|
| `/system` 挂载 | ext4 `ro,nosuid` |
| `mount -o rw,remount /system`（uid1000） | Operation not permitted |
| `touch /system/...` | 失败 |
| uid1000 / uid2000 的 `CapEff` | 都是 0 |
| `/system` 剩余 | 15.1 MB |

普通 `cp` 到 `/system/lib` 走不通。

## 5. 三条写入通道

### A. 伪装为系统更新（推荐，签名条件已打通）

- `ro.build.tags=test-keys` / `userdebug` / 标准 AOSP `full_mstarnapoli` fingerprint。
- `/system/etc/security/otacerts.zip` 只有 `testkey.x509.pem`（AOSP 标准 testkey，serial `936EACBE07F201DF`）。
- 从 `aosp-mirror/platform_build` 的 `android-4.3_r1` 取公开 `testkey.pk8`，openssl 模数比对 **MATCH = True** → **能签出 `RecoverySystem.verifyPackage()` 接受的 OTA 包**。
  （私钥来自 AOSP 公开仓库，**不在本仓库**，也不做任何密钥分发。）
- `/cache` 是 rw；`/cache/recovery/` = `drwxrwx--- system:cache`，uid1000 在 cache 组，实测可写。
- 触发：给平台签名的 `tvhelper.apk` 加 `android.permission.REBOOT`，调 `RecoverySystem.installPackage()`；或直接写 `/cache/recovery/command`。
- `updater-script` 只需替换 `/system/lib/libskia.so`（或 `apply_patch` 打 1 字节）。recovery 有 root，能正常 remount、验签、原子替换。

**尚未确认（下一步）**：recovery 分区前 8 MB 是 MStar 私有镜像（无 `ANDROID!`、无明文 `res/keys`），需 dump 完整分区确认是否支持标准 Edify OTA、验签公钥是否同为 testkey；还需要 ARM `update-binary`；`com.stv.systemupgrade` 可能用乐视私有包格式，需反编译确认。

### B. 裸块设备 1 字节写（不依赖 recovery）

- `/dev/block/mmcblk0p9` = `brw-rw---- system:system 0660` → **uid1000 可直接读写裸块设备**；实测 `busybox dd` 读 64 MB 成功（14.4 MB/s）。
- 设备 `grep -b` 可用 → 用 ASCII 锚点（如 `SkWEBPImageDecoder`）在分区 dump 里定位 so 的物理偏移，再加 `0x1139BC`，只写 1 字节 `0x00`。
- 风险：绕过 VFS page cache（必须重启）、误写会破坏 ext4。**必须先整盘 `dd` 备份 system 分区**（504 MB，本地约 36 s）。

### C. SUID 提权（备选，不推荐）

`/system/xbin/tcpdump`、`librank`、`procmem`、`procrank` 是 SUID，`/system/etc/dvfs_scaling.sh` 也有 setuid 位。理论上旧版 tcpdump 的 `-Z root -z <cmd>` 可 root 执行 → remount + cp，但属于漏洞利用、行为不稳定。

## 6. 如何验证「补丁改得对不对」（三层已实测通过）

`patch_libskia.py --verify` 只回答「生成的文件是否只差 1 字节」。这**不足以**证明改对了：字节可能落在错误的函数、喂给错误的调用、破坏 ELF 加载，或者虽然改了标志位但行为没修好。完整的验证分三层，另有刷入后的一层。

### 第 1 层：离线静态强校验 —— `source/skia-patch/verify_libskia.py`

对原库与补丁库做 **67 项检查，67 项通过**（报告 `patch-libskia/verify_static.log` / `.json`）：

| 类别 | 关键结论 |
|---|---|
| 字节 diff | 恰好 1 字节（`0x1139BC`：`01`→`00`），两库 sha256 与文档一致 |
| ELF 结构 | ELF32/LE/EM_ARM/ET_DYN；ELF header、PHDR 表、SHDR 表字节一致；除 `.text` 那 1 字节外，**全部 24 个 section 完全一致** |
| 地址映射 | 补丁在可执行 PT_LOAD（flags=5）内；`VA == off == 0x1139BC`；`.text addr == off`；`va2off` 往返一致（原报告「VA==文件偏移」的假设被证实，不是想当然） |
| 重定位 | 5438 条 REL 中**没有**任何一条覆盖该字 → linker 不会在加载时把补丁覆盖回去 |
| 符号归属 | dynsym 确认该字属于 `_ZN18SkWEBPImageDecoder15setDecodeConfigEP8SkBitmapii`（`0x11394C`, size=132） |
| 指令语义 | `0xE3A01001 ^ 0xE3A01000 = 1`，**只有立即数变化**，opcode/条件码/寄存器不变；条件码仍为 AL |
| 调用目标 | 紧随其后的 `bl 0x72408` 由 ELF dynsym 解析为 `_ZN8SkBitmap11setIsOpaqueEb`，补丁前后该 BL 完全相同（控制流不变） |
| 影响面 | 全库 22 处 `setIsOpaque` 调用：另有 6 处硬编码 `#1`，**全部在 BMP/JPEG/WBMP**（这些格式本就不含 alpha）；PNG 是动态参数。→ **WebP 是唯一「格式支持 alpha 却硬编码 opaque」的解码器**，正是异常点 |
| 可加载性 | `.hash/.dynsym/.dynstr/.rel.dyn/.rel.plt/.ARM.exidx/.ARM.extab/.gnu_debuglink/.dynamic/.got/.plt` 全未变；Android linker 不校验 build-id / debuglink CRC，哈希表只哈希符号名 → 无需重签名、无需重 dexopt |

### 第 2 层：不刷机、不重启的 A/B 动态验证 —— `source/skia-patch/probe/`

**原理**：普通 app 从 zygote fork，继承了已 mmap 的 `/system/lib/libskia.so`，`LD_LIBRARY_PATH` 对它无效。必须用 `app_process` 直接启动**非 zygote 进程**，linker 才会重新解析 `DT_NEEDED` 并优先查 `LD_LIBRARY_PATH`。把补丁库命名成 `libskia.so` 放在 `/data/local/tmp/skiapatch`，同一探针跑两次：

```sh
# A 对照组：系统原库
ANDROID_DATA=/data/local/tmp/skiadroid \
  CLASSPATH=/sdcard/Download/skiaprobe.dex \
  app_process /system/bin com.tv.skiaprobe.ProbeMain orig

# B 实验组：只多一个 LD_LIBRARY_PATH
LD_LIBRARY_PATH=/data/local/tmp/skiapatch:/vendor/lib:/system/lib:/system/lib/egl \
  ANDROID_DATA=/data/local/tmp/skiadroid \
  CLASSPATH=/sdcard/Download/skiaprobe.dex \
  app_process /system/bin com.tv.skiaprobe.ProbeMain patched
```

**踩过的坑**：`/data/dalvik-cache` 是 `system:system 0771`，uid2000 无法创建 dex 缓存 → dex 加载失败 → `app_process` 报 `could not find class` 后在 `0xdeadd00d` 故意 SIGSEGV（退出码 139）。用 `ANDROID_DATA` 把 dexopt 缓存指向可写目录即可解决。

探针会打印 `/proc/self/maps` 中 `libskia.so` 的真实路径（**证明这次到底加载了哪份库**），再解码 8 个样本，输出 `hasAlpha / alphaSum / opaque / semi / transparent / 像素 checksum`。实测 **12/12 检查通过**：

| 样本 | A 原库 | B 补丁库 |
|---|---|---|
| `LIBSKIA_MAPS` | `/system/lib/libskia.so` | `/data/local/tmp/skiapatch/libskia.so` |
| `02_vp8x_alph.webp`（真实小电视图标，32×32） | `hasAlpha=false`, opaque=1024, semi=0, transparent=0 | `hasAlpha=true`, opaque=0, **semi=244, transparent=780** |
| `11_checker_vp8x.webp`（合成棋盘，64×64） | `hasAlpha=false`, alphaSum=1044480, opaque=4096 | `hasAlpha=true`, **alphaSum=988981**, opaque=3659, semi=437 |
| `10_checker.png`（源 RGBA 参考） | alphaSum=988981, opaque=3659, semi=437 | 同左（PNG 不受影响） |
| 6 个不带 alpha 的样本 | checksum | **与 A 完全相同 → 零回归** |

最有力的一点：补丁后 VP8X 的 **alphaSum 与源 PNG 精确相等**（988981），而颜色 checksum 不同（VP8 有损压缩），说明补丁只恢复了 alpha、没有碰颜色解码。

**如实记录副作用**：`setIsOpaque(false)` 是无条件的，所以 B 组里**所有** WebP（包括无 alpha 的裸 VP8）`hasAlpha` 都变成 `true`。这不改变任何像素（checksum 全同），只是少走一条 opaque 绘制快速路径，属于可接受的性能代价。

### 第 3 层：与独立参考逐像素比对 —— `probe/compare_alpha.py`

为避免「只是翻转了标志位」的误判，把探针导出的 PNG 用 PC 端 ffmpeg 解成 raw RGBA，直接比对 **alpha 平面**：

| 比对 | 结果 |
|---|---|
| A 组 WebP alpha vs 源 PNG | 4096 像素中 **437 个不同**，maxdelta=127（半透明圆被抹平） |
| B 组 WebP alpha vs 源 PNG | 4096 像素 **0 差异** |
| B 组 WebP alpha vs PC ffmpeg/libwebp 参考 | 4096 像素 **0 差异** |
| B 组真实图标 alpha vs PC ffmpeg 参考 | 1024 像素 **0 差异** |
| 无 alpha 样本 R/G/B 三通道 A vs B | 全部 **0 差异** |

结论：**`ALPH` 通道被逐像素完整恢复，不只是标志位变化**。

### 第 4 层：刷入后才做（尚未执行）

前三层证明的是「补丁库本身正确」。真正写进 `/system` 之后还要单独确认写入与生效：

1. 读回 `/system/lib/libskia.so` 的 sha256 必须是 `f8e4328c…`（或分区镜像里该字节为 `00`）—— 排除写错块 / 写坏 ext4。
2. **重启**（zygote 已 mmap 旧库，native 库不进 dalvik-cache，无需重 dexopt，但必须重启）。
3. 重启后查 `/proc/<zygote 或 system_server>/maps`，确认映射的是新的 `/system/lib/libskia.so`；重跑 `webpprobe` 或直接看图标。
4. 回归：PNG 海报、裸 VP8、芒果TV / 小电视 / 乐视桌面三类图标。
5. 按项目约定，**不主动测试任何遥控器按键**。

## 7. 回退

- 原库完整备份在本地（`build/assets/implib/libskia.so`）；补丁只差 1 字节，回退即把 `0x00` 改回 `0x01`，或恢复原 so 后重启。
- 刷入前**整盘 dd 备份 system 分区**（504 MB）；若走 OTA，另备一份可恢复的更新包。
- 验证脚本与产物都在 `source/skia-patch/` 与 `build/patch-libskia/`，A/B 验证全程**不写 `/system`、不重启、不按遥控器**。

## 8. 资料与工具位置

仓库内：

- `source/skia-patch/patch_libskia.py` —— 生成 / 基础校验 1 字节补丁
- `source/skia-patch/verify_libskia.py` —— 第 1 层：离线静态强校验（67 项）
- `source/skia-patch/probe/ProbeMain.java` + `build_probe.py` —— 第 2 层：电视端 A/B 探针
- `source/skia-patch/probe/verify_on_tv.py` —— 一键 push + 跑 A/B + 判定
- `source/skia-patch/probe/compare_alpha.py` —— 第 3 层：逐像素 alpha 比对
- `source/skia-patch/flash_via_block.sh` —— 电视端模板，**默认 DRY-RUN，从未执行**

调查用的完整取证报告与原始日志不在仓库内（含设备快照），在 `aerial-tools/build/`：

- `skia-patch-feasibility-2026-11-15.md`（完整报告）
- `skia_disasm_all.txt` / `skia_helpers.txt` / `skia_callers.txt`（反汇编）
- `survey_*.log`（权限、挂载、OTA 探查）
- `patch-libskia/libskia-patched.so`（补丁产物）
- `patch-libskia/verify_static.log` / `.json`、`verify_dynamic_run.log` / `.json`、`verify_alpha.log`（三层验证实测记录）
- `patch-libskia/probe_out/skiaprobe/*.png`（A/B 两组导出的解码结果）
