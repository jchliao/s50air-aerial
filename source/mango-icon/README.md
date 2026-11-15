# 芒果TV 首页白色阶梯块 — 根因与修复包

完整结论见 `docs/11-mango-icon.md`。

## 状态（重要）

- ❌ **`apply_nav_fix.py`（改 okhttp 缓存）已证伪**：`getChannels` URL 带动态 `ttid`，
  每次启动都是新缓存 key，app 每次重新联网拉配置（logcat 抓到 `httpCode: 200`），
  旧缓存文件永远不会被读。该脚本仅保留作**反例与缓存回滚工具**，已执行 `--restore`。
- ✅ **真正原因**：app 把 Glide / Fresco 的解码格式降级为 **`RGB_565`（无 alpha 通道）**
  （`ImageEngine.isLowMemory()`、`FrescoImageLoader` 机型白名单 `"X08A"`、
  `ReplaceHookManager` 等 6 个 dex 多处）。云端 `channelIcon` 是「全白 RGB + 仅 alpha」PNG，
  alpha 被丢后变纯白不透明块，半透明边缘被二值化 → 用户看到的**硬边锯齿**。
- ✅ **`mango-alpha-fixed.apk` 已离线生成并校验**，尚未安装到电视（需用户确认）。

## 修复思路（方案 A，精准、不动其它 dex）

只改 `classes4.dex` 的 `NavigateAdapter$ItemViewHolder` 一行 smali：

```smali
# 958 行：默认态参数 getChannelIcon() -> getImgFocus()
invoke-virtual {p1}, TitleDataModel->getImgFocus()Ljava/lang/String;
```

默认态与选中态都改用不依赖 alpha 的蓝色胶囊 logo → 两个白块消失。
**934 行的 `getChannelIcon()` 必须保留**（它只用于判断该项是否为图片型导航项）。

## 构建与校验

```bash
# 1) 反编译（需 aerial-tools/smalitools/ + build/jdk-17.0.2/）
java -cp "smalitools/*" org.jf.baksmali.Main d classes4.dex -o classes4
# 2) 改上面那一行 -> classes4-patched
java -cp "smalitools/*" org.jf.smali.Main a classes4-patched -o classes4-new.dex
# 3) 重打包 + 重签 v1 + 静态校验
python build_patched_apk.py
```

`build_patched_apk.py` 校验：9 个 dex 齐全、**只有 `classes4.dex` 与原包不同**、
其余 3141 个 entry 逐字节相同、`jarsigner -verify` rc=0；
并会再反编译新 dex 确认 934/958/966 三行符合预期。

产物：`aerial-tools/build/mango_skin/mango-alpha-fixed.apk`（39.6 MB，本地 key 签名）。

## 安装（⚠️ 会丢 app 数据）

签名与原包不同，**必须先卸载**：

```bash
# 走 uid1000 通道（uid2000 无 INSTALL_PACKAGES / 无 FORCE_STOP_PACKAGES）
adb push mango-alpha-fixed.apk /sdcard/Download/
pm uninstall com.starcor.mango
pm install -r /sdcard/Download/mango-alpha-fixed.apk
```

回退：`pm uninstall com.starcor.mango` 后重装原包 `aerial-tools/build/assets/app/mango.apk`。

> 重启 app 的正确姿势：`monkey -p com.starcor.mango -c android.intent.category.LAUNCHER 1`
> （4.3 的 `am start` 不支持 `-p`；`force-stop` 需 uid1000）。

## 其它方案

| 方案 | 说明 |
|---|---|
| B 全局强制 `ARGB_8888` | 6 个 dex 全改，能根治「很多透明图不对」，但 Bitmap 内存翻倍、1.5 GB 老电视有 OOM 风险 |
| C 换官方 TV 版 / 旧版 | 成本最低但不确定降级策略是否不同 |
| D 接受 | 仅装饰性图标 |

## 文件

| 文件 | 说明 |
|---|---|
| `build_patched_apk.py` | 重打包 + 重签 + 静态校验（推荐方案） |
| `apply_nav_fix.py` | 已证伪的缓存改法，`--restore` 回滚用 |
| `build_fixed_cache.py` | 生成 gzip+FEXTRA 缓存体的取证脚本（反例） |
| `original-cache-body.gz` / `fixed-cache-body.gz` | 反例缓存体各 2843 B |
