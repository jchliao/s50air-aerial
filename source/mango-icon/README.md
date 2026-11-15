# 芒果TV 首页白色阶梯块 — 缓存层修复

详见 `docs/11-mango-icon.md`。

## 问题

首页左侧栏「综艺 / 电影」之间显示纯白硬边阶梯块。根因是「后会友期」导航项
（唯一用图片 logo 代替文字的项）的**默认态 `channelIcon`** 是一张
「195×62、所有像素 RGB 全白、只靠 alpha 通道勾勒白色手写体」的 PNG，
约 10% 像素是半透明抗锯齿边缘。电视上渲染链路把 alpha 二值化后就成了锯齿白块。

系统 `BitmapFactory` 解码层实测 alpha 完整（`opaque=410 / semi=1204 / transparent=10476`），
所以这是**渲染 / 图片加载层**问题，与 `libskia.so` 的 WebP 补丁不是同一层。

## 修复原理

把 `getChannels` 响应里 `channelIcon` 的 URL **等长替换**成同一配置里已经正常显示的
`imgFocus` URL（蓝色胶囊 logo，92% 像素不透明，几乎不依赖透明通道）。

- 两个文件名均 41 字符 → JSON 解码后 19879 B 不变，仅 34 字节差异
- 响应体是 gzip 且无 `Content-Length`；重新压缩后用 **gzip FEXTRA 字段填充 281 字节**
  精确对齐回原长度 2843 B → `journal` 的 `CLEAN <key> 7986 2843` 依然有效
- 只写 `/sdcard/Android/data/com.starcor.mango/cache/okttp/5fc2131bc283c9aa311b02961f68bdeb.1`
  一个文件；**不动 APK、不动系统、不动 `.0`、不动 journal**

## 用法

```bash
python source/mango-icon/apply_nav_fix.py             # 应用
python source/mango-icon/apply_nav_fix.py --check     # 查看当前状态
python source/mango-icon/apply_nav_fix.py --restore   # 一键回退
```

前置：`aerial-tools/platform-tools/adb.exe` 存在、电视 ADB `192.168.5.9:5555` 已连接。

**生效条件**：app 已把导航配置读入内存，必须在电视上**退出芒果TV 再重进**。
云端下次重新下发 `getChannels` 会覆盖，重跑脚本即可。

## 文件

| 文件 | 说明 |
|---|---|
| `apply_nav_fix.py` | 应用 / 检查 / 回退，自包含 |
| `original-cache-body.gz` | 原始 gzip 缓存体（2843 B），回退用 |
| `fixed-cache-body.gz` | 修复后 gzip 缓存体（2843 B，含 FEXTRA 填充） |
| `build_fixed_cache.py` | 生成 `fixed` 的取证脚本（依赖 `aerial-tools/build/mango_skin/` 里的截图与图标素材） |

## 待验证

重进 app 后抓首页截图，确认白块变成蓝色胶囊 logo。若仍异常，说明该 View 默认态分支
另有占位 drawable，需要反编译 APK 左侧栏 Adapter。
