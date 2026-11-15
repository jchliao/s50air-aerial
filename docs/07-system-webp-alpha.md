# 系统级缺陷：Android 4.3 的 Skia WebP 解码器丢弃 VP8X 透明通道

2026-11-15 实测。**这是 `docs/06` 那次「不是系统缺陷」结论的修正与完整证据。**

触发：用户发现芒果TV 的首页分类图标也显示异常，且乐视自带桌面早年也有同类现象，
怀疑是系统层面的问题。实测证明这个直觉是对的。

> 实验资产（探针、样本、导出 PNG、截图、拉回的系统库）都在本机工作目录
> `aerial-tools/build/` 下，**未入仓库**（体积大且属于一次性取证材料）。
> 探针源码在 `aerial-tools/build/webpprobe/`，可随时重建复现。

---

## 1. 上次错在哪

11-14 的 `webpprobe` v1 只做了：

```java
bm = BitmapFactory.decodeFile(path);
Log.i(TAG, bm == null ? "NULL" : bm.getWidth() + "x" + bm.getHeight()
        + " alpha=" + bm.hasAlpha());
```

**只判断「是否返回 null」，没检查像素。** 当时 VP8X 全部返回非 null、
`hasAlpha()` 一律 false，就被解读成「系统能解 VP8X、不是系统缺陷」。
实际上 `hasAlpha() == false` 正是缺陷本体的信号。

## 2. 实验设计

探针 v2（平台签名，versionCode 2，装完卸载清理）：

- 每个样本解码两遍：**设备默认配置** + 强制 `ARGB_8888`
- `getPixels()` 导出全部像素，记录 config / hasAlpha / checksum / alpha 直方图 / 采样点
- `Bitmap.compress(PNG)` 把**系统解码结果**写到 sdcard 供拉取
- PC 端 ffmpeg 解同一文件作「正确解码」参考，统一转 raw RGBA 逐字节比对

8 个样本：3 个来自小电视真实缓存（VP8X+ICCP、VP8X+ALPH、裸 VP8）、
2 个无损降级版、1 张合成 64×64 已知图案 PNG（四色块 + 半透明圆）、
2 张由该 PNG 经 ffmpeg 转出的 VP8X / 裸 VP8。

## 3. 结果

设备 `MStar/full_mstarnapoli/...:4.3/...:userdebug/test-keys`，SDK 18，
默认 bitmap 配置就是 `ARGB_8888`（排除「设备色彩格式是 RGB_565」这一假设）。

| 输入 | 系统 `BitmapFactory` 的结果 |
|---|---|
| PNG 棋盘 | 与原图 **diff 0 / 16384 字节**，alpha 直方图一致（3659 全不透明 + 437 半透明） |
| VP8X + ICCP（无 alpha） | 颜色正确（与 ffmpeg 平均偏差 **0.91/255**、最大 28）；与「降级成裸 VP8 后再解」**diff 0 / 133712 字节**，checksum 相同 |
| VP8X + ALPH（真实 32×32 图标） | 正确解应有 780 全透明 + 244 半透明；系统解 **1024 个像素全部 alpha=255**、`hasAlpha=false`，其中 448 个变纯黑 (0,0,0)，其余变白/灰不透明块 |
| VP8X + ALPH（合成棋盘） | 正确解有 437 个半透明像素；系统解 **4096 个全部 alpha=255**，与参考 diff 5733/16384 |

导出的图直观看：正确解是白色对勾 + 透明背景，系统解变成黑白方块马赛克。

**结论：`libskia.so` 的 `SkWEBPImageDecoder` 忽略 VP8X 扩展头、直接吃 `VP8 ` 码流
（颜色对），但不处理 `ALPH` chunk、不调用 `setHasAlpha(true)`。所有带透明通道的
WebP 小图标被渲染成不透明黑/白底方块。**

## 4. 「系统 libwebp.so 是新版」为什么不能洗白

从电视 `/system/lib/` 拉回的 4 个库：

| 库 | 内容 |
|---|---|
| `libwebp.so` 193KB | **完整版**：`WebPGetDemuxVersion`、`WebPGetFeaturesInternal`、`ALPHNew`、`VP8LDecodeImage`，支持 VP8X |
| `libwebpimage.so` 26KB | Fresco 的 JNI 封装 `com/facebook/imagepipeline/webp/WebPImage` |
| `libimagepipeline.so` / `libgifimage.so` | Fresco native 组件，被乐视放进系统 |
| `libskia.so` 2.2MB | 自己静态带一份 WebP 解码：`SkWEBPImageDecoder::onDecode`、`WebPParseHeaders`、`WebPINewYUVA`… |

**两份解码器不是同一个东西**：`/system/lib/libwebp.so` 是给 Fresco native 用的，
`BitmapFactory` 走 `libskia.so` 内部那份。前者支持 VP8X ≠ 后者支持。

另外 `/system/etc/*packages.xml`（dynamic_memory / 4K / OSD 白名单）、
`services`（端口表）、`authority.dat`（应用等级定义）都与图片解码无关，已排除。

## 5. 三个 app 的共同链路

Fresco 及多数图片库在 Android 上把**静态 WebP 交给系统 `BitmapFactory`**，
只有 animated WebP / 特殊配置才走 native `WebPImage`。因此：

- **云视听小电视**：缓存 268 个 VP8X（114 个带 `ALPH`）→ 图标黑块/破图
- **芒果TV**：自带 `libstatic-webp.so` / `libimagepipeline.so`，静态图仍走系统解码 →
  首页左侧分类图标出现白色像素化花块，海报大图全部正常
- **乐视自带桌面**：用户早年观察到的同类现象，推测同源

芒果TV 的皮肤包（`skinResDown/*.zip`、`skinApp/*.zip`）里 286 个资源全是 PNG/JPEG，
没有 WebP，且系统解 PNG 完全正常 → 问题图标来自**网络下发**，不在皮肤包里。
其图片缓存在 `/data/data/com.starcor.mango/`，system uid 读不到、`adb root` 也不可用，
**本次未拿到实际图标文件做格式确认**，这是唯一未闭环的一环。

## 6. 为什么 `docs/06` 的缓存降级仍然有效

| 缓存类型 | 处理 | 绕开了什么 |
|---|---|---|
| 无 alpha 的 `ICCP+VP8`（154 个） | 抽 `VP8 ` chunk 重组裸 RIFF | 对系统解码器无感（像素逐字节相同），但让 Fresco 的容器解析路径拿到最简输入 |
| 带 `ALPH` 的（114 个） | ffmpeg 转 **RGBA PNG** | 改走 `SkPNGImageDecoder`，实测 alpha 保真 |

所以带 alpha 的**不能只降级、必须转 PNG**。这也是用户实测「修复有效」的原因。

## 7. 「要不要打系统补丁」重新评估

上次不打补丁的理由「系统本来能解 VP8X」**已作废**。2026-11-15 又做了一轮纯二进制逆向，**结论再次翻案**：

- 靶点已精确到 1 条指令：`SkWEBPImageDecoder::setDecodeConfig` 在 `0x1139BC` 无条件 `mov r1,#1` → `SkBitmap::setIsOpaque(true)`。解码器本身用 `MODE_RGBA`，alpha 已经写进像素，只是被这个标志丢掉。
- 补丁是 **1 个字节**（`01` → `00`），不需要改 ARM 大段代码、不需要重 dexopt。
- `/system` 确实 `ro` 且 `CapEff=0`，但拿到了三条写入通道，其中 **OTA（`test-keys` + 公开 testkey）最规范**。

| 方案 | 评价 |
|---|---|
| 给 `libskia.so` 打 1 字节补丁（新） | **可行**：一劳永逸、所有 app 同时受益、可回退；代价是要重启 + 刷入有风险 |
| 替换 `/system/lib/libwebp.so` | 打不中靶子（Skia 静态链接了自己的 libwebp） |
| framework 层 hook `BitmapFactory` | 影响面比 libskia 更大 |
| 维持缓存降级（当前） | 零系统改动、可还原、已实测有效；缺点是按 app 分别处理，新下载图标会复发 |

**当前状态**：补丁包与取证报告已完成，**尚未刷入**。完整靶点、三条通道、签名验证与回退见 [`08-system-patch.md`](08-system-patch.md)，工具在 `source/skia-patch/`。

## 8. 复现清单

| 文件（均在 `aerial-tools/build/`） | 内容 |
|---|---|
| `webpprobe/` | 像素探针 v2 源码 / manifest / `build.py` / `prep_pixel_test.py` |
| `webptest/` | 8 个测试样本 |
| `probe_out/probe_out/` | 系统解码导出的 16 张 PNG + `report.txt` |
| `probe_ref/` | ffmpeg 正确解码参考图 |
| `pixel_probe.log` | 完整探针报告 |
| `assets/implib/` | 拉回的 4 个系统图像库 |
| `assets/mango/` | 芒果TV 皮肤包 / okhttp 缓存样本 |
| `mango_home.png` | 芒果TV 首页截图（可见异常图标） |

电视侧已还原：探针卸载，`webptest` / `probe_out` / `webpprobe.apk` 删除，
只覆盖过临时执行器 `/sdcard/Download/root.sh`。
