# 刷入方案：走 OTA、改内存，还是直接写块设备？

> 前置阅读：[`08-system-patch.md`](08-system-patch.md)（靶点、补丁、三层验证）
> 状态：**已完成** —— 2026-11-15 14:39 写入 1 字节并独立校验；用户手动重启后，`probe/verify_after_reboot.py` **18/18 项通过**（VFS sha256 = `f8e4328c…`、无替代库的探针与补丁基线逐像素一致）→ 补丁已生效。本文记录通道实测对比、操作步骤与执行记录。

## 0. 一句话结论

**两条都别走，走第三条：直接对 `/dev/block/mmcblk0p9` 写 1 个字节。**

- **OTA**：签名条件虽好，但这台机器的 recovery 是 MStar 私有（高熵/需私有签名）镜像，不是标准 AOSP Edify recovery，构造可用更新包的成本远高于改 1 字节。
- **改内存**：无 root、zygote 是 root、各 app 不同 uid，`ptrace` 全部被拒；即使能改也只影响单个 COW 私有页，重启即失效 —— 做不到全局、持久生效。

而裸块写入的全部前置条件已经实测通过：物理偏移算出来了、原字节读回来了、uid1000 写权限确认了。

## 1. 实测证据（2026-11-15）

### 1.1 OTA 路线：签名能过，但 recovery 不是标准 AOSP

| 检查 | 实测结果 |
|---|---|
| `/system/etc/security/otacerts.zip` | 仅 `testkey.x509.pem`，AOSP 公开 testkey，模数与 `android-4.3_r1` 的 `testkey.pk8` **MATCH** |
| `/cache/recovery/` | `system:cache 0770`，uid1000 可写（已实测 touch 成功） |
| `mmcblk0p6` (recovery) 大小 | **8192 KB = 8 MB**（已完整 dump，非只取头部） |
| recovery 前 8 MB 内容 | 非零率 **99.6%**，`ANDROID!` / `res/keys` / `META-INF` / `update-binary` / `edify` / `ELF` / `PK\x03\x04` **全部 0 命中** |
| `/system/etc/install-recovery.sh` | `dd if=/system/recovery.img of=.../by-name/recovery`，随后调用 `./system/update_recovery_sign recovery /system/secure_info_recovery.bin` |
| 运行中的相关服务 | `init.svc.usbremoteupgrade=running`、`usbupgrade`、`flash_recovery` |
| 升级相关包 / 服务 | `com.stv.systemupgrade`、`android.letvremoteupgrademanager: LetvRemoteUpgradeService` |
| `recovery-resource.dat` | 1.94 MB 的 ZIP（PNG 字体资源），只是 UI 资源，不是镜像 |

解读：

1. `otacerts.zip` 是 testkey 只解决了 **Android 框架层** `RecoverySystem.verifyPackage()` 的验签；它不能证明底层 recovery 会执行标准 `META-INF/com/google/android/updater-script`。
2. 8 MB 分区全高熵且无任何 AOSP 特征 → 这是 MStar 私有（很可能加密/签名）镜像，`install-recovery.sh` 里的 `update_recovery_sign` 正是私有签名工具。
3. 实际升级入口是 MStar USB 升级服务与 `com.stv.systemupgrade` / `LetvRemoteUpgradeService`，走乐视私有包格式；需要 ARM `update-binary`、私有包封装和 MStar 签名，**都还没打通**。

> 诚实边界：不能 100% 排除「高熵数据后面还藏着标准 ramdisk」或「私有升级服务最终仍会调用 Edify」。但即便如此，为了改 1 个字节去逆向整套私有 OTA 格式，代价与风险都远大于直接写块设备。

### 1.2 「改内存」路线：权限上就走不通

| 检查 | 实测结果 |
|---|---|
| zygote (PID 1275) | `Uid: 0 0 0 0`，`CapEff: ffffffffffffffff` |
| system_server (PID 1571) | `Uid: 1000`，`CapEff: 0000000007c13c20`（**不含 CAP_SYS_PTRACE, bit19**） |
| 芒果TV (PID 3517) | `Uid: u0_a29`，独立 uid |
| `/proc/<pid>/mem` 属主 | 分别 `root:root` / `system:system` / `u0_a29:u0_a29`，均 `0600` |
| uid2000(shell) 读 `/proc/1275/maps` | **Permission denied** |
| uid2000(shell) 读 `/proc/1275/mem` | **Permission denied**（`dd` rc=1） |
| uid1000 读 `/proc/1571/mem` | 同样被拒；只有同 uid 且 dumpable 才可能 ptrace |
| `setprop wrap.<pkg>` | `setprop` 返回 0，但 `getprop` 返回**空**（属性未落地）→ `wrap.*` + `LD_LIBRARY_PATH` 的免刷机路线也不通 |

三个独立的技术障碍：

1. **权限**：改别的进程内存要 `PTRACE_MODE_ATTACH`。uid1000 既不属 root（zygote），也不属各 `u0_aXX`（app），且无 `CAP_SYS_PTRACE` → 一个都碰不了。SUID 提权拿到 root 之后，直接 remount/cp 更简单，改内存反而多此一举。
2. **作用范围**：`libskia.so` 的 `.text` 是 `MAP_PRIVATE` 文件映射。就算写进某个进程，也只产生一个 COW 私有页，其它进程完全不受影响。要全局生效必须改 zygote 并重启所有 app —— 而 zygote 恰恰是 root 进程。
3. **持久性**：磁盘没变，**一重启全丢**。图标是在各 app 进程里解码的，改 system_server 的内存对它们毫无作用。

> 「临时不刷机看效果」这个需求其实已经做完了：`08` 第 6 节的 `app_process` + `LD_LIBRARY_PATH` A/B 探针，就是不碰 `/system`、不重启的行为级验证。

### 1.3 裸块 1 字节写：全部前置条件已闭合

| 项 | 实测值 |
|---|---|
| system 分区 | `/dev/block/mmcblk0p9`，524288 KB = **512 MB**，ext4 `ro,nosuid` |
| `libskia.so` 物理起始 | **30,818,304** = `0x1D64000`（4K 对齐） |
| 该处 4 字节 | `7f 45 4c 46`（ELF magic） |
| 分区 dump 中整个 so | 与本地备份 **2,247,420 字节逐字节完全相同**（无压缩/加密/稀疏） |
| 补丁点文件内偏移 | `0x1139BC` = 1,128,892 |
| **补丁点物理偏移** | **31,947,196** = `0x1E779BC`（扇区 62396 的 +444 字节） |
| 从块设备读回该处 8 字节 | `01 10 a0 e3 90 7a fd eb` ✓ 与本地原库一致 |
| uid1000 `test -w /dev/block/mmcblk0p9` | **rc=0** |
| uid1000 `dd of=<blk> count=0 conv=notrunc` | **rc=0**（只打开不写数据，零副作用） |
| `busybox sync` | rc=0 |

定位方法：`grep -a -b -F 'SkWEBPImageDecoder'` 在 toybox/busybox 上给的是**行偏移**，不可直接用；已改为把前 64 MB dump 拉回本地，用 Python 找 `SkWEBPImageDecoder` 全部 5 个命中 + 反推 5 个 so 内偏移，取交集后用「4K 对齐 + ELF magic + 整文件逐字节相等」三重确认，唯一解 `30,818,304`。

> 注意：`busybox grep` **不支持 `-b`**（`invalid option -- 'b'`），支持 `-b` 的是 toolbox 的 `/system/bin/grep`，且给的是行偏移。旧版 `flash_via_block.sh` 里 `grep -b` 直接算偏移的做法是错的，本版已改为写入实测常量并做多重校验。

## 2. 三条通道对比

| | A. 签名 OTA | B. 改内存 | **C. 裸块 1 字节写** |
|---|---|---|---|
| 需要 root | 不需要（recovery 有） | **需要**（且拿到后不必用它） | 不需要，uid1000 即可 |
| 需要签名 | 需要（testkey 已有） | — | 不需要 |
| 需要 `update-binary` / Edify | **需要，且格式未打通** | — | 不需要 |
| 需要进入 recovery | 需要 | — | 不需要 |
| 改动面 | 整个 so 替换或 apply_patch | 若干进程的代码页 | **1 字节** |
| 精确回退 | 需要另一个 OTA 包 | 改回去 / 重启 | **写回 `0x01`** |
| 重启 | 要（进 recovery） | **每次开机都要重做** | 要（zygote 重新 mmap） |
| 主要风险 | 私有包格式不对→变砖 / 卡 recovery | 改错进程→系统崩溃；且根本不持久 | 误写块→破坏 ext4（可备份） |
| 当前可行性 | **未打通** | **权限不允许** | **已实测闭合** |

## 3. 推荐做法：C，且默认 DRY-RUN

工具在 `source/skia-patch/`：

| 文件 | 作用 |
|---|---|
| `flash_via_block.sh` | 电视端脚本，`dry` / `apply` / `rollback` 三模式，**默认 dry** |
| `flash_on_tv.py` | PC 端一键驱动：生成校验样本 → push → 走 uid1000 通道 → 读日志判定 |
| `patch_libskia.py` / `verify_libskia.py` / `probe/` | 生成补丁、静态强校验、A/B 行为验证（见 `08`） |

### 3.1 脚本内置的多重保险

1. 强制 `uid=1000`，否则退出；
2. 块设备存在且 `test -w` 通过；
3. 从块设备读 `SO_START` 处 4 字节必须等于 `7f 45 4c 46`；
4. 从块设备读补丁点 8 字节必须等于 `01 10 a0 e3 90 7a fd eb`（未打）或 `00 10 a0 e3 90 7a fd eb`（已打），其它值一律 ABORT；
5. **写入前先把补丁点所在 4K 块备份**到 `/sdcard/Download/skiaflash/_block4k.bak`（可 pull 回 PC）；
6. 写 1 字节 → `sync` → **从块设备读回** 8 字节再 `cmp` 校验（不从 `/system/lib/` 读，因为 VFS page cache 可能仍旧值）；
7. `apply` 需要 PC 端显式二次确认参数，默认永远只 dry-run。

### 3.2 建议顺序

```bash
# ① 整盘备份（512MB，留在电视 sdcard 上，约 36s；不要 pull，0.5MB/s 太慢）
#    由 flash_on_tv.py --backup 触发，或手动：
#    busybox dd if=/dev/block/mmcblk0p9 of=/sdcard/Download/system_backup.img bs=1M

# ② 干跑：只校验、不写任何字节
python source/skia-patch/flash_on_tv.py --mode dry

# ③ 确认日志全部 PASS 后，才真正写 1 字节
python source/skia-patch/flash_on_tv.py --mode apply --confirm-write-system

# ④ 重启电视（手动；脚本不会自动重启、不会按任何遥控器按键）
```

### 3.3 刷入后验证清单（对应 `08` 第 6 节第 4 层）

1. 从**块设备**读回 `0x1E779BC` 应为 `00 10 a0 e3 90 7a fd eb`；
2. 重启后读 `/system/lib/libskia.so` 的 sha256 应为 `f8e4328c5fea2aef49542013386fce76f57252156059ddcaeda2fe2718ecaef7`；
3. 查 zygote / app 进程 `maps` 确认映射新的 `/system/lib/libskia.so`；
4. 重跑 `webpprobe`：VP8X+ALPH 应 `hasAlpha=true`、alpha 与参考 0 差异；
5. 回归：PNG 海报、裸 VP8、小电视 / 芒果TV / 乐视桌面三类图标。

回退：`python flash_on_tv.py --mode rollback`，把 `0x00` 写回 `0x01`，重启即可；极端情况用 `system_backup.img` 整盘 dd 恢复。

## 4. 风险与边界（务必先读）

- **这是直接写系统分区**，绕过 VFS page cache 与 ext4 journal。虽然只动 1 个数据字节、不动元数据，理论上不会破坏一致性，但**偏移写错或写错设备会损坏 ext4**。整盘备份是硬性前提。
- 写入后到重启前，已 mmap 旧库的进程内存里仍是旧指令；`/system/lib/libskia.so` 经文件 page cache 读也可能仍旧值。**必须重启**才全局生效，期间的读回校验一律以块设备为准。
- 原生库不进 dalvik-cache，**不需要重 dexopt**。
- 补丁副作用：`setIsOpaque(false)` 是无条件的，所有 WebP 的 `hasAlpha()` 都会变 `true`（像素不变，仅少一条 opaque 绘制快速路径）。
- 按项目约定：**脚本不会自动重启、不会自动测试任何遥控器按键**。

## 5. 执行记录（2026-11-15 14:38–14:39）

用户确认后按顺序执行，日志在 `aerial-tools/build/patch-libskia/`：

| 步骤 | 结果 |
|---|---|
| `--mode backup` | 512.0 MB / 39.7 s，`dd_rc=0`，`/sdcard/Download/system_backup.img` = **536,870,912 B**（`flash_backup.log`） |
| `--mode dry`（写入前复核） | `DRY_RUN_OK`，`state=orig`，ELF 锚点 `7f 45 4c 46`，4K 块备份 byte=`01`（已 pull 到本地 `block4k.before.bin`，sha256 `9a35f850…`）（`flash_dry_before_apply.log`） |
| `--mode apply --confirm-write-system` | 写 `0x00` @ 31947196，`write_rc=0`、`sync OK`、块设备读回 `00 10 a0 e3 90 7a fd eb` → **`FLASH_OK`**（`flash_apply.log`） |
| 独立复核 | 从**块设备**重新 dump 整个 so 区域（4K×549 块）并拉回本地：sha256 = **`f8e4328c…`，与 `libskia-patched.so` 完全相同**；与原库只差 **1 字节**，位置 `0x1139BC`，值 `0x00`（`flash_verify_after.log`） |

系统健康检查：写入后 `/system` 仍 `ro,nosuid` 挂载正常，zygote(1275) / system_server(1571) 均存活，无崩溃。

**一个重要的实测现象**：写入后通过 VFS 读 `/system/lib/libskia.so` 的 sha256 仍是**原库** `4642931b…`（md5 `98ec7a44…`），而块设备读到的是补丁库。这正是文档预判的 **VFS page cache 与块设备页不一致** —— 所以「刷入后读回校验必须从块设备读」，也**必须重启**让 zygote 重新 mmap。

### 重启后待办（`08` 第 6 节第 4 层）

1. `/system/lib/libskia.so` sha256 应变为 `f8e4328c…`；
2. 查 zygote / app 进程 `maps` 确认映射新的 `/system/lib/libskia.so`；
3. 重跑 `webpprobe`：VP8X+ALPH 应 `hasAlpha=true`、alpha 与参考 0 差异；
4. 看小电视 / 芒果TV / 乐视桌面三类图标，PNG 海报与裸 VP8 回归。

回退（若重启后异常）：`python flash_on_tv.py --mode rollback --confirm-write-system` → 写回 `0x01` → 重启；或用 `/sdcard/Download/system_backup.img` 整盘 dd 恢复。
