# 11 · 芒果TV 首页白色花块图标（调查中）

日期：2026-11-15 · 状态：**定位中，尚未修复** · 芒果TV `7.2.202.390.3.SHAFA_TVAPP.0.0_Release`

## 现象

首页左侧栏「综艺」与「电影」之间有一个**纯白、硬边、阶梯状**的块（1920×1080 截图里约 `(64,561)-(200,621)`），
无对应文字。放大图见 `docs/images/mango-white-block.png`。

## 决定性对比

用户切到「后会友期」专题页后，**同一个位置显示的是正常的蓝色胶囊 + 白色手写 logo**（`docs/images/mango-left-rail-compare.png`）。

> 这说明：View 渲染、app 布局、系统解码器**全部正常**。
> 问题只锁定在「首页时该导航项的**默认态（未选中）云端图标**」，选中态图是好的。

## 已排除的假设

| 假设 | 证据 | 判定 |
|---|---|---|
| VP8X `ALPH` 被 Skia 丢弃 | 云端 API JSON 提取 **3790 个图片 URL：3288 jpg + 482 png + 20 其它，0 个 webp**；3 个皮肤包共 174 PNG、0 WebP | ❌ 芒果TV 根本不走 WebP，系统补丁对它无效是必然 |
| 缓存里存了坏图 | 用户清缓存重启 app 后白块原样存在 | ❌ |
| 云端图片损坏 | PC 经代理下载全部候选图标，HTTP 200、Pillow 正常打开 | ❌ |
| 内置皮肤资源损坏/被拉伸 | 213 张候选 PNG 做 alpha 形状模板匹配，最高 IoU 仅 0.706，无精确匹配 | ❌ |
| 系统解码缺陷 | `libskia.so` 补丁重启后 18/18 验证通过；PNG 解码原本正常 | ❌ |

## 取证要点

- **okhttp 缓存结构**：`.0` = URL 元数据（首行即 URL）、`.1` = 响应体（约一半 gzip）。
  73 个响应**全是 API JSON，0 张图片** → 图片缓存在 app 私有目录，不可读。
- 导航栏配置文档 `5fc2131bc283c9aa311b…`（含「播客」「短剧」），字段
  `channelIcon` / `imgFocus` / `bgImgUrl` / `subscriptImg2` / `extendFieldB`。
- 11 个 `subscriptImg2` URL 在 PC 上均返回同一张 2219 B 的 32×20「V」VIP 角标。
- 29 个导航 URL 下载得 26 张正常图（芒果必看 / 11.11大促 / 后会友期 logo、1920×1080 背景图）。
- `uiautomator dump` 在这台 4.3 上被 kill（rc=137）；芒果TV 自写日志清缓存后 0 字节。
- 拉缓存快照的正确写法：`busybox tar -czf /sdcard/Download/x.tgz <绝对路径>`，**不要用 `-C`**（这台 busybox 会失败）。

## 下一步方向

1. 切回首页并把光标移到白块那一项（选中态），看是否显示正常 logo → 若正常，即可确认只是默认态那张云端图的问题。
2. **换版本**：当前为沙发管家渠道版，Android 4.3 兼容性存疑，装官方 TV 版或旧版对比（成本最低）。
3. **反编译 APK**（39.4 MB / 9 dex / `libboost_multidex.so`），定位左侧栏 Adapter 的 icon View 与加载失败占位分支。
4. **抓包**：`/system/bin/tcpdump` SUID root 可用，确认电视上是否有某个图标请求失败（4.3 对现代 TLS/SNI 支持差，PC 能下不代表电视能下）。
5. 接受：仅一个装饰性图标，不影响功能。

## 资产

完整报告 `aerial-tools/build/mango_skin/ICON-INVESTIGATION.md`；
拼图 / 云端 URL 清单 / 下载实物 / 快照均在 `aerial-tools/build/mango_skin/`。

> 本轮未改动电视上任何系统文件或 app 数据；缓存由用户自行清理。
