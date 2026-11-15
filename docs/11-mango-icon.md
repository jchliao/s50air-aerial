# 11 · 芒果TV 首页白色阶梯块（透明通道 / 锯齿）

日期：2026-11-15 · 状态：**根因已定位，修复已写入电视，待重进 app 验证**
设备：Letv S50 Air / Android 4.3 · 芒果TV `7.2.202.390.3.SHAFA_TVAPP.0.0_Release`

## 现象

首页左侧栏「综艺」与「电影」之间有一个**纯白、硬边、阶梯状锯齿**的块（1920×1080 截图 bbox `(64,561)-(200,621)`，136×60），无对应文字。
切到「后会友期」专题页后，**同一位置显示正常的蓝色胶囊 + 白色手写 logo**（`docs/images/mango-left-rail-compare.png`）。

> 用户判断：「就是有很多透明通道处理不对」「可以看出来都是锯齿」—— 取证结果支持这个方向。

## 根因：默认态图标是「全白 RGB + 仅 alpha」型，透明通道在渲染链路被丢

导航栏配置（`getChannels` 响应，okhttp 缓存 `5fc2131bc283c9aa311b02961f68bdeb.1`）中，

- **`vclassId=4772930` / `title=后会友期` / `pageType=-1` 是唯一用图片 logo 代替文字的导航项**；
  其它导航项 `channelIcon` 全是空字符串 —— 正好对应白块是左侧栏唯一异常。
- 默认态 `channelIcon` = `.../20261105/0f9da23663f3461bb7915ddc4f90b480_5993.png`
  - 195×62 RGBA，**12090 个像素的 RGB 全部是 `(255,255,255)`**，唯一信息在 alpha 通道里（白色手写「后会友期」剪影）
  - alpha 分布：opaque 410 / **semi 1204（10%，抗锯齿边缘）** / transparent 10476
- 选中态 `imgFocus` = `.../20261105/db8667b31d874c3c9f5d728954eb96da_4398.png`
  - 195×62，蓝色胶囊 + 白字，opaque 11132（92%）/ semi 234 / transparent 724 —— **主体不依赖透明通道**
  - 这就是专题页看到的正常 logo

证据图：`docs/images/mango-rootcause.png`（截图 / channelIcon / imgFocus 三联）、
`docs/images/mango-alpha-jaggies.png`（截图 / 原始 alpha / alpha 阈值化后的硬边锯齿）。

### 关键分层结论

| 层 | 实测 | 判定 |
|---|---|---|
| 系统 PNG 解码 | 电视端 `BitmapFactory` + `ARGB_8888` 探针解码 `channelIcon`：`195x62 hasAlpha=true opaque=410 semi=1204 transparent=10476`，与 PC Pillow 逐项吻合 | ✅ **解码层 alpha 完整** |
| 系统 WebP 解码 | `libskia.so` 1 字节补丁重启后 18/18 验证通过 | ✅ 已修，但与本例无关 |
| 渲染 / 合成层 | 显示为纯白硬边阶梯块，无任何半透明过渡 | ❌ **alpha 在这里丢了** |

所以之前「补丁对芒果TV 无效」是必然的：补丁修的是 `SkWEBPImageDecoder` 的 **decode 层** alpha，
而这个白块是**渲染 / 图片加载链路**把半透明抗锯齿像素二值化（或按 1-bit mask 处理）的结果 ——
表现就是用户看到的**锯齿**。37 张下载的云端图标里 **28 张带半透明边缘像素**，2 张是「全白 RGB + 仅 alpha」型，
这类资源在这台 4.3 上普遍容易出问题。

> 诚实边界：把 alpha 直接阈值化可以复现「硬边锯齿」，但复现形状与截图白块 IoU 仅 0.306，
> 说明渲染链路里还有降采样 / 占位 drawable 等额外因素，尚未完全反推。不影响修复路径。

## 排除的假设（订正）

| 假设 | 证据 | 判定 |
|---|---|---|
| VP8X `ALPH` 被 Skia 丢弃 | 3790 个云端图片 URL 全为 jpg/png，0 个 webp；皮肤包 174 PNG、0 WebP | ❌ 芒果TV 不走 WebP |
| 缓存里存了坏图 | 用户清缓存重启 app 后白块原样存在 | ❌ |
| 云端图片损坏 / 404 | PC 下载全部候选 HTTP 200、Pillow 正常打开 | ❌ 不是损坏，是**导出方式本身**只有 alpha 承载信息 |
| 系统解码器缺陷 | 电视探针解码 alpha 完整 | ❌ |
| 内置皮肤资源被拉伸 | 213 张候选形状匹配最高 IoU 0.706 | ❌ |
| 电视 DNS/CDN 不可达 | `busybox wget` 连 `www.baidu.com` 也 `bad address`（`net.dns1=192.168.5.1`，`nslookup` 全失败） | ⚠️ busybox 工具链 DNS 本身不通，非 CDN 故障；app 走 Java DNS，专题页 logo 正常 |

## 修复（只改 sdcard 上 app 缓存数据，不动 APK / 系统 / journal）

思路：**避开依赖透明通道的资源**。把导航 JSON 里 `channelIcon` 换成已知能正常显示的 `imgFocus` URL。

- 两个文件名都是 **41 字符**，等长替换 → 解码后 JSON 长度不变（19879 B，仅 34 字节差异）
- `.1` 是 gzip 响应（`.0` 头为 `content-encoding: gzip`、`Transfer-Encoding: chunked`，**无 Content-Length**）
- 重新 gzip 后长度 2560 B，原 journal 记录 `CLEAN <key> 7986 2843`；
  利用 **gzip FEXTRA 字段填充 281 字节**精确对齐回 **2843 B**，
  因此 `journal` / `.0` 全部不用改，DiskLruCache 不会判定 entry 损坏
- 校验：解压后 JSON 合法、`imgFocus` URL 出现 2 次、旧 stub 0 次、sha256 前后一致

脚本：`source/mango-icon/apply_nav_fix.py`

```bash
python apply_nav_fix.py             # 应用（已执行）
python apply_nav_fix.py --check     # 查看当前状态
python apply_nav_fix.py --restore   # 一键回退到原缓存
```

原文件备份：`navfix/5fc2131bc283c9aa311b02961f68bdeb.1`（2843 B）。

> **生效条件**：app 已把导航配置读进内存，必须在电视上**退出芒果TV 再重进**才能看到效果。
> 云端下次重新下发 `getChannels` 会覆盖本改动，重跑脚本即可。

## 待验证 / 后续

1. 重进 app 后抓首页截图，确认白块变成蓝色胶囊 logo。
2. 若仍异常 → 说明该 View 的默认态分支另有占位 drawable，需要反编译 APK 的左侧栏 Adapter。
3. 系统级「透明通道 / 锯齿」是独立课题：当前只绕开了这一个资源，
   若要根治需查渲染层（app 图片库的 `Bitmap.Config` / GPU 合成），不在本次改动范围。

## 资产

完整取证报告 `aerial-tools/build/mango_skin/ICON-INVESTIGATION.md`；
拼图 / 云端 URL 清单 / 下载实物 / 快照 / 探针脚本均在 `aerial-tools/build/mango_skin/`。

> 本轮除写入上述 1 个 app 缓存文件外，未改动电视上任何系统文件；缓存由用户自行清理过一次。
