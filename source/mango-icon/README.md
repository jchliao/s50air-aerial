# 芒果TV 首页白色阶梯块 — 工具集

**权威结论见 `docs/12-decodeformat-rootcause.md`。**
`docs/11-mango-icon.md` 下半部分基于错误 APK 版本，已过时。

## 状态（2026-11-15 16:50）

- ❌ `apply_nav_fix.py`（改 okhttp 缓存）**已证伪**：`getChannels` URL 带动态
  `ttid`，每次启动都是新缓存 key，app 每次重新联网拉配置。已 `--restore`。
  脚本只作反例与回滚工具保留。
- ❌ `mango-alpha-fixed.apk` / `mango-inplace.apk`（上一版产物）**作废**：
  它们基于本地 `assets/app/mango.apk`（5.16.2），而电视实装的是
  `7.2.202.390.3.SHAFA`（播放器 5.16.3，40,751,159 B / 3190 entries），
  9 个 dex 与证书全不同。**不要安装。**
- ✅ 真正靶点：`ImageLoaderImpl.initImageLoader()` 无条件
  `setDefaultDecodeFormat(PREFER_RGB_565)`。实测
  `ActivityManager.MemoryInfo.lowMemory = false`（1.10 GB 空闲 / 96 MB 阈值），
  `isLowMemory()` 不是生效分支；`isLowQuality()` 全 dex 零调用点。
- ✅ 已按**实装 5.16.3** 重新生成两个补丁包（离线，未写入电视）。
- ✅ 按用户要求安装了当贝版 `7.1.701`（同证书、降级覆盖成功、启动正常，
  但该版本同样带 `setDefaultDecodeFormat`，登录态丢失）。详见 `docs/12` 第 7 节。

## 产物（在 `aerial-tools/build/mango_skin/`，39 MB 级，不入 Git）

| 文件 | 改动 |
|---|---|
| `mango-argb-inplace.apk` | `classes4.dex` 中 `ImageLoaderImpl` 的 `PREFER_RGB_565` → `PREFER_ARGB_8888`（全局根治） |
| `mango-argb-nav-inplace.apk` | 上面 + `NavigateAdapter$ItemViewHolder` L958 `getChannelIcon()` → `getImgFocus()`（双保险） |
| `tv_mango_ondevice.apk` | 电视实装 5.16.3 原包备份（**回退基线**） |

两个包都是 3190 entries、**只有 `classes4.dex` 不同**，原
`META-INF/CERT.RSA/SF/MANIFEST.MF` 逐字节保留（**不重签**）→ 用于「原地替换」。

## 用法

```bash
# 1) 用 Java ZipFile 重建 APK（Python zipfile 会因 zipalign 空 local-header 报错）
python source/mango-icon/build_argb_inplace.py

# 2) 零风险验证：不卸载、不换签名、不丢数据
python source/mango-icon/apply_inplace_patch.py \
  --baseline aerial-tools/build/mango_skin/tv_mango_ondevice.apk \
  --patch   aerial-tools/build/mango_skin/mango-argb-inplace.apk \
  --dry
#   --check / --apply / --restore

# 3) 低内存实测探针（全反射，隐藏 API）
#    javac -classpath android-4.3.1/android.jar MemProbe.java
#    D8 --min-api 18 -> classes.dex
#    ANDROID_DATA=/data/local/tmp/skiadroid CLASSPATH=... app_process /system/bin com.tv.memprobe.MemProbe
```

⚠️ **原地替换只在运行时有效**：PMS 下次开机扫描会逐 entry 验签，
所以 `--restore` 必须在重启前执行。`--apply` 会校验电视上 APK 与
`--baseline` 的 md5 一致，不一致直接拒绝，避免把 5.16.3 的 dex 灌进别的渠道包。

若要持久化，两条路：

```bash
# A) 同证书/签名版：保留数据卸载重装
pm uninstall -k com.starcor.mango     # 4.3 确认支持 -k
pm install -r <signed-apk>

# B) 回退到 5.16.3 原包（同证书、versionCode 更高，可直接覆盖）
pm install -r aerial-tools/build/mango_skin/tv_mango_ondevice.apk
```

## 文件

| 文件 | 说明 |
|---|---|
| `build_argb_inplace.py` | 调 Java Rezip 生成两个保留签名的补丁包 |
| `rezip/Rezip.java` | 按 central directory 重建 APK，容忍 zipalign 空 local-header 文件名 |
| `memprobe/MemProbe.java` | `lowMemory` / `availMem` / `threshold` 实测探针 |
| `apply_inplace_patch.py` | `--dry/--check/--apply/--restore`，带基线 md5 安全校验 |
| `build_patched_apk.py` | 上一版重签流程（基于 5.16.2，仅作参考） |
| `apply_nav_fix.py` | 已证伪的缓存改法，`--restore` 回滚用 |
| `build_fixed_cache.py` | gzip + FEXTRA 缓存体取证脚本（反例） |
| `original-cache-body.gz` / `fixed-cache-body.gz` | 反例缓存体各 2843 B |
