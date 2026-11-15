# 12 · DecodeFormat 决策链复核：真正的开关是 `setDefaultDecodeFormat`

> 2026-11-15 16:22–16:50。起因：用户提出「`isLowMemory(Context)` 读
> `ActivityManager.MemoryInfo.lowMemory`，低内存 → `PREFER_RGB_565`；
> `ImageTask.isLowQuality()` 同样切到 `PREFER_RGB_565`，是不是从这个地方入手」。
> 结论：**方向对，但靶点要上移一层；`isLowMemory` 实测根本没被触发。**

## 1. 先做实测，别再靠推断

用 `app_process` 反射调 `ActivityManagerNative.getDefault().getMemoryInfo()`
（`source/mango-icon/memprobe/MemProbe.java`），在电视上得到：

```
MEMPROBE getFreeMemory = 1,176,649,728    (1.10 GB 空闲)
MEMPROBE lowMemory     = false
         availMem      = 1,176,383,488
         threshold     = 100,663,296      (96 MB)
         totalMem      = 1,585,815,552    (1.48 GB)
```

系统侧也从 `services-smali/com/android/server/am/ActivityManagerService.smali:55574`
读到完整公式：

```java
homeAppMem   = mProcessList.getMemLevel(6);
hiddenAppMem = mProcessList.getMemLevel(HIDDEN_APP_MIN_ADJ);
availMem     = Process.getFreeMemory();
lowMemory    = availMem < homeAppMem + (hiddenAppMem - homeAppMem) / 2;
```

**`lowMemory = false`**，而且余量极大（1.10 GB vs 96 MB 阈值）。所以
`isLowMemory()` 返回 false，按它自己的分支本该选 `PREFER_ARGB_8888`。
之前记的「1.55 GB / 空闲 290 MB、OOM 风险高」是误读旧 `dumpsys meminfo`，
**内存顾虑可以放下**——全局开 `ARGB_8888` 在这台机器上有充足余量。

## 2. 完整的三层决策链（实装版 5.16.3）

| 层 | 位置 | 逻辑 |
|---|---|---|
| ① 全局默认 | `ImageEngine` `init` (L6157–6205) | `if (mImageConfig.getDefaultDecodeFormat() != null) → 直接用它`；**只有为 null 时**才调 `isLowMemory()` 选 `RGB_565`/`ARGB_8888` |
| ② 单次请求覆盖 | `ImageEngine` (L1573–1620) | `task.isHighQuality()` → `ARGB_8888`；`task.isLowQuality()` → `RGB_565` |
| ③ 另一套加载器 | `FrescoImageLoader` (L411–455) / `ReplaceHookManager.getPipelineConfig` | 默认 `Bitmap.Config.RGB_565`，只有 `ApiDataProvider.getDeviceModel().equalsIgnoreCase("X08A")` 才 `ARGB_8888` |

`isLowMemory()` 被 ① 短路了，因为 **`getDefaultDecodeFormat()` 恒非 null**：

```smali
# classes4/com/mgtv/tv/imageloader/ImageLoaderImpl.smali  ~L1234
sget-object v1, Lcom/bumptech/glide/load/DecodeFormat;->PREFER_RGB_565:...
invoke-virtual {v0, v1}, Lcom/mgtv/image/ImageConfig$Builder;->setDefaultDecodeFormat(...)
```

`initImageLoader()` 里这一行**无条件执行**，没有任何配置读取或条件分支。
`ImageLoaderImpl` 就是 `ProxyInject` 映射的 `IImageLoader` 实现
（`com.mgtv.tv.proxy.imageloader.IImageLoader` → `com.mgtv.tv.imageloader.ImageLoaderImpl`），
也就是 `BaseNavigateTabItemView.setImage` → `vl/p.s0` → `ImageLoaderProxy` 最终走的链。

另外确认：实装包 9 个 dex 中 `lowQuality` **只有 `ImageTask$Builder` 的定义、
零调用点**，`setLowQuality/lowQuality(Z)` 没有任何地方调用 → ② 的
`isLowQuality()` 分支当前也不生效。

> `FrescoImageLoader` 的 `X08A` 白名单属于 `com.mgtv.adproxy`（广告图片）链，
> 与导航图标不是同一条；`getDeviceModel()` 最终落到
> `DeviceInfoFetcher.getDeviceModel()` → `Build.MODEL`（本机 `Letv S50 Air`）。

**所以：全局 `RGB_565` 是 app 主动写死的，不是内存判断的结果，也不是机型判断。**
这解释了「很多透明通道处理不对」（全局降级）和「libskia 补丁对它无效」
（补丁修的是系统 decode 层的 WebP，这里是 app 主动选了无 alpha 的 Bitmap 格式）。

## 3. 由此得到的修复靶点（按治本程度排序）

1. **改一行，全局根治**：`ImageLoaderImpl.smali` L1234
   `PREFER_RGB_565` → `PREFER_ARGB_8888`。所有走 Glide 的图片恢复 alpha，
   锯齿一起消失。内存翻倍但实测余量 1.10 GB。
2. **双保险**：在 1 的基础上再改 `NavigateAdapter$ItemViewHolder` L958
   `getChannelIcon()` → `getImgFocus()`（保留 L934 判断），让默认态直接用
   92% 不透明的蓝色胶囊 logo。
3. 只改 2（上一版方案）只能修那两个白块，治不了其它透明图。

`FrescoImageLoader` 那条链要单独处理：要么伪装 `ro.product.model=X08A`
（改 `/system/build.prop` + 重启，全局影响所有 app 和服务端设备识别），
要么也 patch 它的白名单判断。

## 4. ⚠️ 重大纠错：之前反编译/打包用错了 APK

| | 电视实装（拉回 `tv_mango_ondevice.apk`） | 本地 `assets/app/mango.apk` |
|---|---|---|
| versionName | `7.2.202.390.3.SHAFA_TVAPP.0.0_Release` | 更旧的渠道版 |
| versionCode | 26110616 | — |
| 大小 / entries | 40,751,159 B / 3190 | 39,368,093 B / 3142 |
| 9 个 dex | 全部不同（classes4 sha `20ea7510…`） | classes4 sha `0638dd1f…` |
| CERT.RSA | 不同（但证书指纹与当贝版相同） | 不同 |
| 播放器 so | `libImgoMediaPlayer_5.16.3.so` | `…5.16.2.so` |

**`mango-alpha-fixed.apk` / `mango-inplace.apk` 是基于 5.16.2 生成的，
对电视实装版无效，不要安装。** 好消息是重新反编译实装包后确认：
`ImageEngine`、`FrescoImageLoader`、`ImageLoaderImpl`、
`NavigateAdapter$ItemViewHolder`（934/958/966）在新版里结构完全一致，
改动方式不变。

本轮已按**实装 5.16.3** 重新生成（见第 6 节）。

## 5. 「不卸载重装」的可选方法（回应上一轮提问）

| 方案 | 是否卸载 | 是否丢数据 | 是否持久 | 说明 |
|---|---|---|---|---|
| **`pm uninstall -k` + 装签名版** | 是 | **否** | 是 | 4.3 `pm` 帮助确认存在 `pm uninstall [-k] PACKAGE`，`-k` 保留 `/data/data/<pkg>`。上一轮我说「会丢登录和观看历史」是错的 |
| **原地 dex 替换（不重签）** | 否 | 否 | **否，重启前须还原** | uid1000 实测 `/data/app/com.starcor.mango-2.apk` 与 `packages.xml` 均可写（`test -w`=0）。生成只换 `classes4.dex`、**META-INF 原样保留**的 APK，`cp` 覆盖 + force-stop 重开。Dalvik 运行时不重验 jar 签名；**但下次开机 PMS 会逐 entry 验签**，所以仅作可逆验证 |
| **伪装机型 X08A** | 否 | 否 | 是 | 只影响 Fresco/adproxy 链；需改 `/system/build.prop` + 重启，全局副作用 |
| **网络层替换图片** | 否 | 否 | 取决于 PC | 3790 个 URL 里 3678 个 https、122 个 http；getChannels URL 带动态 `ttid`，改旧缓存已证伪。要 MITM + 装 CA，成本高 |
| **系统级 patch** | 否 | 否 | 是 | 在 `libandroid_runtime.so`/`libskia.so` 拦截 RGB_565 请求升级为 ARGB_8888，沿用 libskia 1 字节补丁的工具链；影响全局、需刷入+重启 |
| **app 设置页「功能兼容性管理」** | 否 | 否 | 是 | UI 里确实有该入口，但反编译 `ImageDelegateImpl` 显示 `imageDegradedType` / `imageDecodeAllowAll` / `imageDisallowHardware` 是 `SysPlayerInfo` 云端配置，管的是 AVIF/WEBP 降级与 URL 重构，**不是 Bitmap.Config**；大概率无效，但零成本可试 |
| **换版本** | — | — | — | 见第 7 节，当贝版同样带 `setDefaultDecodeFormat`，已排除 |

## 6. 本轮产物（均基于实装 5.16.3）

- `aerial-tools/build/mango_skin/mango-argb-inplace.apk` — 只改 ① 全局 DecodeFormat
- `aerial-tools/build/mango_skin/mango-argb-nav-inplace.apk` — ① + ② 双改动
- 两者：3190 entries，**只有 `classes4.dex` 不同**，原 `META-INF/CERT.RSA/SF/MANIFEST.MF`
  逐字节保留（不重签）→ 用于第 5 节的「原地替换」验证
- `source/mango-icon/rezip/Rezip.java` — 用 Java `ZipFile`（按 central directory 读，
  容忍 zipalign 造成的空 local-header 文件名）重建 APK；Python `zipfile` 会因
  `File name in directory ... and header b'' differ` 失败
- `source/mango-icon/memprobe/MemProbe.java` — `lowMemory` 实测探针
- `source/mango-icon/apply_inplace_patch.py` — `--dry` / `--apply` / `--restore` / `--check`

> 还没往电视写这些补丁。当前电视装的是当贝版（见第 7 节），若要应用需先回退
> 5.16.3：`pm install -r aerial-tools/build/mango_skin/tv_mango_ondevice.apk`
> （同证书、versionCode 更高，可直接覆盖回去）。

## 7. 当贝版 7.1.701 安装记录（用户要求「安装一下看看」）

`C:/Users/jch/Downloads/mgtvDBEI_7.1.701_dangbei.apk`

- `com.starcor.mango`，versionCode **26080318**，
  versionName `7.1.701.383.3.DBEI_TVAPP.0.0_Release`，播放器 so 5.14.6
- **证书指纹与实装版相同**（SHA1 `51:69:43:73:30:B0:6E:C7:1C:33:FE:F4:B5:E8:BB:3A:7F:DF:AF:FC`），
  `CERT.RSA` 字节不同但同一张证书 → 可直接 `pm install -r` 覆盖，**无需卸载**
- uid1000 静默安装：`Success`，路径变为 `/data/app/com.starcor.mango-1.apk`
- 启动正常（**无 Android 4.3 兼容性崩溃**），但停在登录页 →
  **降级覆盖后登录态丢失**；按一次 BACK 后进入「设置」页
- **离线预判**：当贝版 `classes4.dex` 里仍有 `setDefaultDecodeFormat` +
  `PREFER_RGB_565` → 换版本绕不开这个降级，白块大概率仍在
- 设置页有「功能兼容性管理」入口，但按第 5 节分析它管的是网络格式降级

截图：`docs/images/mango-dangbei-login.png`（登录页）、
`docs/images/mango-dangbei-settings.png`（设置页，可见「功能兼容性管理」入口）。

## 8. 回退

```bash
# 回 5.16.3（同证书、versionCode 更高，直接覆盖）
pm install -r aerial-tools/build/mango_skin/tv_mango_ondevice.apk

# 若用了原地 dex 替换
python source/mango-icon/apply_inplace_patch.py --restore   # 重启前必须做
```

## 9. 环境补记

- `pm help` 在 4.3 不存在（`pm` 无参数即打印 usage），`pm uninstall [-k] PACKAGE` 确认支持
- uid1000 `id` = `uid=1000(system) gid=1000(system) groups=…41000(u0_a31000)`；
  `test -w` 对 `/data/app/<apk>` 与 `/data/system/packages.xml` 均为 0
- `/data/dalvik-cache/data@app@com.starcor.mango-2.apk@classes.dex` 只有主 dex 的 odex；
  其余 dex 由 app 的 multidex 处理
- `dumpsys meminfo` 在 4.3 无 `Total RAM/Free RAM` 汇总，测 `lowMemory` 必须写 Java 探针
- `android-4.3.1/android.jar` 里 `ActivityManagerNative` / `Process.getFreeMemory()` /
  `MemoryInfo.hiddenAppThreshold` 都是隐藏 API，编译探针要全反射
- `AppUtils.getSignaturesMD5()` 只是取签名 MD5 上报，没发现硬编码比对 → 换签名不会直接拒绝启动
- APK 自带 Tinker + `HotfixSdkManager`（有 `open_hotfix_local_debug` 与
  `getExternalStorageDirectory()`），理论上可本地加载补丁，但 tinker_id/签名校验门槛高
