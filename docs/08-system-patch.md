# 给系统打补丁：libskia.so 的 1 字节修复

> 前置阅读：[`07-system-webp-alpha.md`](07-system-webp-alpha.md)（确认系统缺陷的像素级证据）
> 状态：**已完成离线逆向与出包，未刷入电视**。本文记录靶点、补丁与三条写入通道，供后续决策。

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

## 6. 回退与验证

- 原库已完整备份在本地；补丁只差 1 字节，回退即改回 `0x01` 或恢复原 so。
- 刷入前整盘备份 system 分区；native so 不进 dalvik-cache，**不需要重 dexopt**，但 zygote 已 mmap，**必须重启**。
- 验证：重跑 `webpprobe` 像素级探针，VP8X+ALPH 应 `hasAlpha()==true`、透明区不再黑块；芒果TV / 小电视 / 乐视桌面图标应同时恢复；PNG 海报仍 diff 0。
- 按项目约定，**不主动测试任何遥控器按键**。

## 7. 本机资料位置

调查用的完整取证报告与原始日志不在仓库内（含设备快照），在 `aerial-tools/build/`：

- `skia-patch-feasibility-2026-11-15.md`（完整报告）
- `skia_disasm_all.txt` / `skia_helpers.txt` / `skia_callers.txt`（反汇编）
- `survey_*.log`（权限、挂载、OTA 探查）
- `patch-libskia/libskia-patched.so`（补丁产物）
