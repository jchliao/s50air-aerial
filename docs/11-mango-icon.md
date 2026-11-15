# 11 · 芒果TV 首页白色阶梯块（透明通道 / RGB_565 降级）

日期：2026-11-15 · 状态：**根因已定位；缓存改法已证伪**  
设备：Letv S50 Air / Android 4.3 · 芒果TV `7.2.202.390.3.SHAFA_TVAPP.0.0_Release`

> ⚠️ **本页下半部分基于错误的 APK 版本，已被 `docs/12` 取代。**
> 2026-11-15 16:35 复核发现：电视实装的是 `7.2.202.390.3.SHAFA`（播放器 5.16.3，
> 40,751,159 B / 3190 entries），而之前反编译与打包用的 `assets/app/mango.apk`
> 是更旧的 5.16.2（39,368,093 B / 3142 entries），**9 个 dex 与证书全不同**。
> 因此 `mango-alpha-fixed.apk` / `mango-inplace.apk` 对实装版无效，**不要安装**。
> 另外实测 `ActivityManager.MemoryInfo.lowMemory = false`（1.10 GB 空闲 / 96 MB 阈值），
> `isLowMemory()` 不是生效分支；真正写死 `PREFER_RGB_565` 的是
> `ImageLoaderImpl.initImageLoader()` 的 `setDefaultDecodeFormat(...)`。
> 完整决策链、纠正后的补丁包与替代方案见 **`docs/12-decodeformat-rootcause.md`**。

## 现象

首页左侧栏「综艺」与「电影」之间（以及另一处）*有***纯白、硬边、阶梯状锯齿**的块，  
1920×1080 截图 bbox `(64,561)-(200,621)`（136×60）。切到「后会友期」专题页后，  
同一位置显示正常的蓝色胶囊 + 白色手写 logo（`docs/images/mango-left-rail-compare.png`）。

用户判断：「就是有很多透明通道处理不对」「可以看出来都是锯齿」—— **取证完全支持，且找到了全局原因**。

## 结论：app 把图片解码强制成 RGB_565（无 alpha 通道）

反编译 `assets/app/mango.apk`（39.4 MB / 9 dex）后定位到多处**解码降级**：

| 位置                                                         | 逻辑                                                                                                                                                                                  |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `classes.dex` → `com/mgtv/image/ImageEngine`               | `isLowMemory(Context)` 读 `ActivityManager.MemoryInfo.lowMemory`；低内存 → `Glide DecodeFormat.PREFER_RGB_565`，否则 `PREFER_ARGB_8888`。另有 `ImageTask.isLowQuality()` 同样切到 `PREFER_RGB_565` |
| `classes.dex` → `FrescoImageLoader`                        | 默认 `Bitmap.Config.RGB_565`；只有机型 `equalsIgnoreCase("X08A")` 才用 `ARGB_8888`                                                                                                           |
| `classes.dex` → `ReplaceHookManager` / `DrawableOptEngine` | 同样的 `RGB_565` 分支，机型白名单 `"X08A"`                                                                                                                                                     |
| `classes4.dex` → `ImageLoaderImpl`                         | 同样引用 `RGB_565`                                                                                                                                                                      |

**`Bitmap.Config.RGB_565` 每像素 2 字节、没有 alpha 位**。这是 app 为老设备省内存的兼容性降级，  
代价是**所有透明图在解码时就被压成不透明**：

- 云端 `channelIcon` 是「**所有像素 RGB 全白 (255,255,255)、只靠 alpha 勾勒白色手写体**」的 PNG  
  （195×62，`opaque=410 / semi=1204(10% 抗锯齿边缘) / transparent=10476`）
- alpha 被丢 → 整张图变成纯白不透明块；半透明边缘被二值化 → **硬边阶梯锯齿**
- `imgFocus`（蓝色胶囊，92% 像素不透明）几乎不依赖 alpha，所以专题页/选中态正常

> 这解释了三件此前对不上的事：① libskia 的 WebP 补丁对它无效（补丁修的是 **decode 层 WebP**，  
> 这里是 **app 主动选了无 alpha 的 Bitmap 格式**）；② 电视 `BitmapFactory` 探针解码  
> `channelIcon` 的 alpha 完整（系统解码器没问题）；③ 用户看到「很多」透明图不对、  
> 「都是锯齿」—— 因为是**全局解码降级**，不是某一张图坏了。

### 配置侧证据

导航配置 `getChannels` 的响应里共有 **38 个 `channelIcon` 字段，只有 3 个非空**：

| channelIcon                                 | 内容                                 |
| ------------------------------------------- | ---------------------------------- |
| `95a93221723545af99867c0f3aacdd4e_4019.png` | 普通彩色图，不依赖 alpha                    |
| `0f9da23663f3461bb7915ddc4f90b480_5993.png` | **全白 RGB + 仅 alpha**（「后会友期」白色手写剪影） |
| `1a0376ceb69845a8b043485f0cacb2e6_3757.png` | **全白 RGB + 仅 alpha**（同类型）          |

正好对应截图里的**两个白块**；其余 35 项用文字，不受影响。

渲染链路（smali 实证）：

```
NavigateAdapter$ItemViewHolder.onBind
  -> TitleDataModel.getChannelIcon() 非空时
  -> BaseNavigateTabItemView.setImage(channelIcon, imgFocus, state)
  -> tl.p.s0(context, url, 0, mOriginHeight, ImageLoadListener)
  -> Glide / Fresco  [DecodeFormat / Bitmap.Config = RGB_565]  <-- alpha 在这里被丢
```

## 为什么上一版「改 okhttp 缓存」无效（已证伪）

上一版把 `channelIcon` 等长替换成 `imgFocus` URL 并写入  
`cache/okttp/5fc2131bc283c9aa311b02961f68bdeb.1`（gzip + FEXTRA 对齐 2843 B，journal 不动）。  
写入与回读校验都通过，但**重进 app 后白块仍在**。原因：

- 清空 logcat 后用 uid1000 `am force-stop` + `monkey` 重启，抓到：  
  `I/Network-OkhttpImpl: ... requestPath:https://inottchl.api.mgtv.com/v2/tvapp/channel/getChannels ... httpCode: 200,isSuccess:true`
- **URL 里 `ttid` 每次启动都变**（`0_1a1de4174ef_WBYGmDhF`），okhttp 缓存 key 是 URL 的 MD5  
  → 每次都是新 key → app **每次启动都重新联网拉配置**，旧缓存文件永远不会被读
- `--check` 显示改动还在缓存里，只是「没人读」

其它数据层路线也已封死：`/data/data/com.starcor.mango/` 在 **uid1000 下也是 Permission denied**，  
`run-as` 不可执行（app 非 debuggable），sdcard 全量扫描**没有任何图片缓存文件**  
（`yfnet/cache` 的 `.mgcf` 是 TS 视频分片 P2P 缓存，不是图片）。  
所以 **改数据这条路走不通，只能改代码**。

## 修复方案

### A（已离线生成，推荐）精准魔改 `classes4.dex` 一行

把 `NavigateAdapter$ItemViewHolder` 绑定时传给 `setImage` 的**默认态参数**从  
`getChannelIcon()` 改成 `getImgFocus()`：

```smali
# 改前（第 958 行附近）
invoke-virtual {p1}, TitleDataModel->getChannelIcon()Ljava/lang/String;   # p4 = 默认态
invoke-virtual {p1}, TitleDataModel->getImgFocus()Ljava/lang/String;      # v0 = 选中态
invoke-virtual {p3, p4, v0, p2}, BaseNavigateTabItemView->setImage(...)

# 改后：只改这一行
invoke-virtual {p1}, TitleDataModel->getImgFocus()Ljava/lang/String;      # p4 = 选中态
```

注意**保留第 934 行**那个 `getChannelIcon()`（它只是判断该导航项是否为图片型，不能改）。

效果：默认态与选中态都用不依赖 alpha 的蓝色胶囊 logo → 两个白块消失。  
其它图片的内存占用不变，不需要动另外 8 个 dex。

产物：`aerial-tools/build/mango_skin/mango-alpha-fixed.apk`（本地 key 重签 v1）。  
构建脚本 `build_patched_apk.py` 会做静态校验：9 个 dex 齐全、**只有 `classes4.dex` 与  
原包不同**、其余 3141 个 entry 逐字节相同、`jarsigner -verify` 通过。

**代价 / 前提**：签名变了，**必须先 `pm uninstall com.starcor.mango`（会丢登录/历史等 app 数据）**  
再装魔改包；云端后续改版不会覆盖这个代码改动。

```bash
# 安装（需 uid1000 通道）
pm uninstall com.starcor.mango
pm install -r /sdcard/Download/mango-alpha-fixed.apk
# 回退：pm uninstall com.starcor.mango 后重装原包 assets/app/mango.apk
```

### B（更彻底，风险高）全局强制 ARGB_8888

把 6 个 dex 里所有 `RGB_565` / `PREFER_RGB_565` 换成 `ARGB_8888` / `PREFER_ARGB_8888`  
（分布：`classes.dex` 2 / `classes2.dex` 3 / `classes4.dex` 1 / `classes6.dex` 1 /  
`classes8.dex` 1 / `classes9.dex` 2）。  
能根治用户说的「很多透明通道处理不对」，但 **Bitmap 内存翻倍**，这台 1.5 GB 总内存、  
空闲约 290 MB 的老电视有 OOM 风险，且要动 6 个 dex。暂不推荐。

### C 换官方 TV 版 / 旧版（成本最低但不确定）

当前是沙发管家渠道版，其它版本的降级策略可能不同。

### D 接受：仅装饰性图标，不影响功能。

## 已排除的假设

| 假设                    | 证据                                                                          | 判定             |
| --------------------- | --------------------------------------------------------------------------- | -------------- |
| VP8X `ALPH` 被 Skia 丢弃 | 3790 个云端 URL 0 个 webp；皮肤包 174 PNG、0 WebP                                    | ❌ 芒果TV 不走 WebP |
| 缓存坏图 / 云端图 404        | 用户清缓存后白块原样；PC 下载全部候选 HTTP 200                                               | ❌              |
| 系统解码器缺陷               | 电视探针解码 `channelIcon` 的 alpha 完整（410/1204/10476）                             | ❌              |
| APK 内置 PNG 直接渲染       | 1417 个 `res/drawable*` PNG 形状匹配最高 IoU 0.715，无精确命中                           | ❌              |
| 改 okhttp 导航缓存         | URL 带动态 `ttid`，app 每次启动联网重拉（logcat 200 OK 实证）                               | ❌ 已证伪          |
| 电视 DNS/CDN 故障         | `busybox wget` 连 `www.baidu.com` 也 `bad address`（工具链 DNS 不通）；app 走 Java DNS | ❌              |



> 诚实边界：alpha 阈值化能复现「硬边锯齿」，但形状参数搜索最高 IoU 仅 0.306/0.496，  
> 说明 RGB_565 之外可能还有缩放/占位因素；不影响方案 A 的针对性。

## 资产

- 反编译产物 `aerial-tools/build/mango_dex/`（`classes1/` 6442 smali、`classes4/` 3064 smali、`classes4-patched/`）
- 取证截图 `tv_now_1602.png`（两个白块）/ `tv_after_restart_1610.png`（重启后）
- `logcat_relaunch.txt`（关键：`getChannels` 200 OK 实证）、`private_scan.log`、`sdcard_scan.log`
- 证据图 `docs/images/mango-rootcause.png` / `mango-alpha-jaggies.png` / `mango-left-rail-compare.png`
- 完整报告 `aerial-tools/build/mango_skin/ICON-INVESTIGATION.md`
- 上一版缓存脚本 `source/mango-icon/apply_nav_fix.py`（保留作反例 / `--restore` 回滚）

> 本轮在电视上做了：抓屏、清 logcat、uid1000 `force-stop` + 重启芒果TV（已拉回首页）、  
> 只读扫描；**未写入任何系统文件，未安装任何 APK**。上一版缓存改动仍在 sdcard，可用  
> `apply_nav_fix.py --restore` 回滚。
