# AGENTS.md — 给 AI Agent 的 S50 Air 改造手册

你要把一台**乐视 S50 Air**（Android 4.3 / API 18 / Dalvik）从原厂桌面改成 Aerial Lite，并保持主页键、信号源键可用。读完这页你就能干活，不需要再猜。

---

## 0. 先做体检（不要跳过）

**连不上先开 ADB**。S50 Air 的开法不是"连点版本号"，是遥控器序列：

```
按【信号源】键 → 弹出信号源页面 → 依次按 1、4、7
→ 信号源页面自动消失 = ADB 已开启（端口 5555）
```

如果窗口没消失就是没进去，重来一次（中间别按别的键）。开启后可以 `adb disconnect` 关掉，下次需要再按一遍。

```bash
adb connect <IP>:5555 && adb devices          # 常掉，每条命令前都 connect 一次
adb shell getprop ro.build.version.sdk        # 期望 18
adb shell getprop ro.product.model            # 期望 S50 Air
adb shell pm list packages | grep -c package  # 基线：200+ 是原样，130 左右是已精简
adb shell id                                  # uid=2000 = shell，权限受限
```

**脚本怎么调**：全部是 `TV_IP=<IP> [DRY_RUN=0] [ADB=/path/to/adb] bash scripts/xx.sh`。默认 dry-run，**不加 `DRY_RUN=0` 什么都不改**。

**关键前提判断**：`adb shell id` 是 uid 2000 时，**你没有 `INSTALL_PACKAGES`、不能 `pm disable` 受保护包、不能 `am` 注入按键**。这时必须走 uid 1000 通道（见第 2 节）。如果 `adb root` 可用（uid 0），跳过第 2 节。

---

## 1. 环境硬约束（踩过的坑，别再试一遍）

| 约束 | 事实 | 应对 |
|---|---|---|
| shell uid | 2000，无安装/停用权限 | 走 tvhelper uid1000 通道 |
| toybox | **极简**：没有 `head`/`wc`/`sed`/`printf`/here-doc | 过滤统计回 PC 端做；写文件用 PC 生成后 push |
| `wc` | 不存在（试过，rc=127） | 用 `grep -c ''` 或本地统计 |
| adb server | 每次调用前必须 `connect`，否则 `no devices` | 脚本里每条命令前加 connect |
| MSYS/Git-Bash | 会把 `/sdcard/x` 改写成 `C:/Program Files/Git/sdcard/x` | `MSYS2_ARG_CONV_EXCL="*"` + 路径写 `//sdcard/x` |
| `adb install` | uid2000 下直接 `Killed`（不是报错，是进程被杀） | 用 uid1000 通道 `pm install` |
| 编译 | 无 Android SDK | 见第 5 节，aapt 从 build-tools zip 取 |

---

## 2. uid 1000 通道（本方案的地基）

电视上有一个极简 Service `com.tvhelper.root`，以 `android:sharedUserId="android.uid.system"` + 平台签名运行，所以进程 uid = 1000。收到 `am startservice` 就用 `/system/bin/sh` 跑一遍 `/sdcard/Download/root.sh`，输出写 `/sdcard/Download/root.log`。

它不是乐视原厂的，**源码在本仓库 `source/tvhelper/`**（`Shell.java` 73 行 + manifest + 构建命令）。

### 装它的顺序是死的：先"弹安装器"，之后全静默

```
① 装 tvhelper 本身   →  必须先 push + am start 拉起系统安装器，人在电视上点一次
                        （此时还没有提权通道，pm install 会被 Killed）
② 装其他所有包       →  全部走 tvhelper 的 pm install -r，无感
```

**①** 一行搞定，唯一需要遥控器的一次：

```bash
TV_IP=<IP> DRY_RUN=0 bash scripts/00-bootstrap.sh apk/tvhelper.apk
```

它内部做的是：

```bash
adb push tvhelper.apk //sdcard/Download/tvhelper.apk
adb shell "am start --user 0 -a android.intent.action.VIEW \
  -d file:///sdcard/Download/tvhelper.apk -t application/vnd.android.package-archive"
```

> **`--user 0` 不能省**。不加会报 `Permission Denial: startActivity asks to run as user -2 but is calling from user 0; this requires INTERACT_ACROSS_USERS_FULL`。

**②** 之后 `scripts/lib.sh` 的 `install_apk()` 三级降级会自动选对路：`pm install`(uid2000) → `pm install`(uid1000 通道) → 系统安装器（兜底）。正常情况走到第二级就 `Success`。

### 验收标准是"实测 uid"，不是查 manifest

```bash
# 错误做法：uid 2000 没有 DUMP 权限，dumpsys package 返回空，看起来像签名不对
# adb shell dumpsys package com.tvhelper.root | grep sharedUser     ← 别这么验

# 正确做法：让它跑一次，看拿到的 uid
printf 'echo alive; id\n' > root.sh
MSYS2_ARG_CONV_EXCL="*" adb push root.sh //sdcard/Download/root.sh
adb shell "am startservice --user 0 -n com.tvhelper.root/.Shell"
sleep 8 && adb shell "cat /sdcard/Download/root.log"
# 看到 uid=1000(system) 才算通
```

> 这个坑我实测踩过：`00-bootstrap.sh` 最初用 `dumpsys` 核验，结果空输出被判成"签名不对"，白忙一轮。

**用法**：把脚本写到 `/sdcard/Download/root.sh`，触发服务，读 `/sdcard/Download/root.log`。

```bash
printf 'pm list packages -d > /sdcard/Download/root.log 2>&1\n' > root.sh
MSYS2_ARG_CONV_EXCL="*" adb push root.sh //sdcard/Download/root.sh
adb shell "am startservice --user 0 -n com.tvhelper.root/.Shell"
sleep 8
adb shell "cat /sdcard/Download/root.log"
```

**铁律**：
- **每行必须自己 `>> /sdcard/Download/root.log 2>&1`**。服务只写自己的 `rc` 行，**不捕获脚本 stdout** —— 不加重定向，日志里只剩 `=== rc=0 ===`，你会以为命令没执行。这一条我实测踩过。
- 脚本必须是 **纯 LF**，不能有 `\r`（Git-Bash 容易带 CRLF）。否则 `rm -f xxx\r` 删不掉文件，判断全错。
- 脚本第一行 `rm -f /sdcard/Download/root.log`，避免读到上一次的结果。
- 每条可能失败的命令后面跟 `echo "EXIT=$?" >> root.log`。
- 写脚本用 PC 端 `printf`/Write 生成，**不要**在电视上生成。
- 直接 `source scripts/lib.sh`，用它的 `root_exec`（已处理上面两件事）。

**版本查询的坑**：`dumpsys package com.stv.appdaemon` 会输出**两段**（`/data` 覆盖版 + `/system` 原版），`grep -m1` 只取第一条才对。取错了会误判成"装的是原版"。

---

## 3. 改造顺序（严格按序，每步验证）

### 3.0 装 uid1000 通道（一切的前提，唯一需要遥控器的一步）

```bash
TV_IP=<IP> DRY_RUN=0 bash scripts/00-bootstrap.sh apk/tvhelper.apk
```

脚本会自动：push → 拉起系统安装器 → 提示你到电视上点"安装" → 实测 `uid=1000` 才算通过。
**这一步没通过之前，后面全部会失败**，别往下走。

### 3.1 停用广告/上报包（最先做，风险最低）

```bash
adb shell pm disable-user --user 0 com.stv.bootadmanager
```
如果报 `Permission denial`，走 uid1000 通道执行同样的命令。

完整清单见 `docs/04-packages.md`，共 36 个，**分三批**：

| 批 | 内容 | 说明 |
|---|---|---|
| A | 广告/上报/推送/反馈（5 个） | 零风险，先做 |
| B | 内容/购物/游戏/儿童/天气/酷云（13 个） | 低风险 |
| C | 桌面/升级/账户/其它（18 个） | **看注释再动**，有 3 个不能停 |

**白名单（绝对不能停）**：

- `com.stv.helper.service` ← **AMS 依赖它**，停了 Aerial 会被秒杀（详见 `docs/05-helper-service.md`）
- `com.stv.signalsourcemanager` ← 信号源管理器，改了它才能用 HDMI 直达
- `com.stv.lekey` ← 遥控按键分发
- `com.stv.filemanager` ← 装 APK 要用
- `com.stv.commonservice` ← 停过，会导致部分系统能力缺失，已恢复

### 3.2 装 Aerial Lite

```bash
adb install -r apk/aerial-lite.apk          # uid 2000 会 Killed → 用 uid1000 通道 pm install
adb shell pm grant app.orchard.tv.lite android.permission.WRITE_SECURE_SETTINGS
adb shell am start -n app.orchard.tv.lite/.HomeActivity
```

第二行：Android 4.x 会报错，**可以忽略**（官方说明也说忽略）。但如果你的电视能 grant 成功（本机就是），亮度调节能用。

### 3.3 主页键接管

按主页键观察行为，分三种情况：

| 现象 | 原因 | 方案 |
|---|---|---|
| 弹出"使用哪个应用"，选 Aerial + 始终后正常 | 系统允许换默认桌面 | **无需改 appdaemon**，到此结束 |
| 按主页键回到乐视桌面 | 固件把 HOME intent 锁在自己桌面 | 改 appdaemon（3.4） |
| 按主页键黑屏 / 反复回桌面 / 卡顿 | **appdaemon 递归崩溃** | 改 appdaemon（3.4），这是主要场景 |

### 3.4 改 appdaemon（关键步骤，需要平台签名包）

直接装 `apk/appdaemon-v3.apk`：

```bash
# uid1000 通道
pm install -r /sdcard/Download/appdaemon-v3.apk
# 装完必须确认 versionCode 比 /system 原版高，否则重启会被压掉
dumpsys package com.stv.appdaemon | grep versionCode
```

**为什么必须抬高 versionCode**：`/data/app` 的包和 `/system/app` 的包同包名时，系统重启扫描会比对 versionCode，`/data` 不高于 `/system` 就被丢弃 —— 这是"改了重启就失效"的真因。

原理、smali 改法、自己签一份的完整流程见 `docs/03-appdaemon.md`。

### 3.5 信号源管理器（可选，只为去掉切换崩溃点）

```bash
pm install -r /sdcard/Download/ssm-v3.apk   # versionCode 3
```

改动：`enableSignalDesktop()` 恒返回 false（隐藏 Tab、返回键直接 finish）+ `toRightDesktop()` 空实现（摘掉切乐视桌面的崩溃点）。原版可用 `pm uninstall com.stv.signalsourcemanager` 回退。

### 3.6 验证

```bash
# 主页键
adb shell am start -an app.orchard.tv.lite/.HomeActivity   # 手动触发一次
adb shell dumpsys window | grep mCurrentFocus               # 应看到 app.orchard.tv.lite/.HomeActivity

# 信号源键（keycode 269，不是 178）
adb shell am broadcast -a com.letv.android.str.TV_ACTION_ON

# appdaemon 没在崩
adb shell logcat -d | grep -c "StackOverflowError"          # 应为 0
```

---

## 4. HDMI 直达磁贴（可选，纯加分）

**背景**：Aerial Lite 在 4.x 上没有信号源磁贴。乐视信号源管理器有一个未公开的直切入口。

**接口**（反编译 `com.stv.signalsourcemanager` 得到）：

```
显式 Intent → com.stv.signalsourcemanager/.MainActivity
  extra "extraPort": "HDMI 2"
```

链路：`onCreate/onNewIntent` → `switchPort(Intent,Z)` → `doSwitchPort` → `Source$SIGNAL.strValueOf(port)` → `switchPort(String)`。

**合法值**（大小写、空格都要一致）：

```
"Analog TV"  "Digital TV"  "Composite"  "YPBPR"  "VGA"
"HDMI 1"     "HDMI 2"      "HDMI 3"
```

**两个致命坑**：

1. **不要用 `"HDMI"`（不带序号）**。它走 `handleHardKeyPort()`，模拟遥控器 HDMI 键 = "切回上一次的 HDMI 口"，不是 HDMI1。我第一次就踩了这个，表现为"点 HDMI1 回到上次的口"。
2. **不要用 `"Super TV"`**，同上走硬键分支。

**实现要点**：
- Aerial 磁贴**按包名去重** —— 一个 APK 注册 3 个 LAUNCHER Activity 只显示 1 个磁贴。所以必须**每个信号源一个独立 APK**。
- Activity 用 `android:theme="@android:style/Theme.Translucent.NoTitleBar"`，否则会闪一下黑/白窗口。
- `onCreate` 里 `startActivity(target)` 后立刻 `finish()`。
- 改名（如 PS4）：Aerial 控制中心 → 个性化 → 手机扫码 → 主屏幕页改名/换图标。**不要改桌面的数据库**。

构建：`cd source/entries && python build_entries.py`（详见该目录 README）。

---

## 5. 从零构建 APK（没有 Android SDK 时）

工具链（本仓库 `source/tools/` 已含下载脚本）：

| 组件 | 来源 | 用法 |
|---|---|---|
| javac | JDK 17 | `javac -encoding UTF-8 -source 8 -target 8 -classpath android.jar` |
| android.jar | `com.google.android:android:4.1.1.4`（API 16，自带 `resources.arsc`） | `-classpath`，**不要**用 `-bootclasspath` |
| D8 | r8 8.2.42（Google Maven） | `java -cp r8.jar com.android.tools.r8.D8 --min-api 18` |
| aapt | build-tools r26.0.2（Google） | `aapt p -f -M AndroidManifest.xml -I android.jar -F out.apk` |
| 签名 | openssl | v1 JAR 签名，Android 4.3 只认 v1 |

**注意**：
- javac 必须 `-encoding UTF-8`（Windows 默认 GBK 会炸）。
- D8 在 Windows 上不展开 glob，用 `$(find classes -name "*.class")` 由 bash 展开。
- **不要手写二进制 AXML**。我试过，native 解析器报 `Corrupt XML binary file`（缺 RESMAP chunk、字符串池未对齐），排查了三轮。用 aapt，一步到位。
- `Intent.EXTRA_SHORTCUT_DUPLICATE` 是 API 17 的常量，API 16 的 android.jar 里没有，用字面量 `"duplicate"`。

---

## 6. 已证伪的假设（省下你的时间）

| 假设 | 结论 |
|---|---|
| Aerial 支持 INSTALL_SHORTCUT 广播 | **不支持**。1.19 / 1.20 / 1.21 的 dex 里都没有接收器，manifest 里也没有。发了没用。 |
| 一个 APK 多个入口能出多个磁贴 | **不行**，Aerial 按包名去重。 |
| Aerial 有 favorites 数据库 / content provider | **没有**。磁贴 = 已安装 App（MAIN/LEANBACK_LAUNCHER）+ 文件夹 + 信号源（4.x 无）。 |
| 改 `/system/app` 里的 APK 就行 | 不行，要改 **`/data/app` 覆盖** 且抬高 versionCode。 |
| 停 `com.stv.helper.service` 能省内存 | **千万别**，见白名单。 |
| 停 `com.stv.helper.main` 会连带 helper.service | 不会，可以安全停 UI。 |
| tvmaster.db 的 applevel 白名单能长期生效 | 会被 TV管家 定期重建（网络配置覆盖），且 helper.service 正常后不再需要。 |
| `keyevent 178` 是信号源键 | 是 **269**。 |
| Android 4.3 对同版本 `pm install -r` 会正常覆盖 | 会返回 `INSTALL_FAILED_INVALID_URI`。要覆盖就抬 versionCode。 |
| `dumpsys package <系统包>` 只输出一段 | 输出**两段**（/data + /system），取第一条才是生效的。 |
| 小电视图标不显示 = Android 4.3 的 Skia 不支持 VP8X | **证伪**。平台签名探针实测系统 `BitmapFactory.decodeFile()` 能解全部 VP8X 样本（只是 `hasAlpha()` 为 false）。问题在 app 侧解码链路，别去给系统打补丁。见 `docs/06`。 |
| 改小电视 APK 里的 `.webp` 资源再重签能修图标 | **无效**。图标由网络下发，落在 sdcard 的 Fresco 缓存里（`yst-final.apk` 是打偏靶子的产物，**别装**）。 |
| 修图标要给系统/native so 打 VP8X 补丁 | **不做**。系统本来能解；改 sdcard 缓存降级为 VP8 即可，可还原、可重复。见 `docs/06`。 |

---

## 7. 出问题怎么办

```bash
DRY_RUN=0 bash scripts/99-restore.sh                 # 全恢复
DRY_RUN=0 bash scripts/99-restore.sh --only-appdaemon # 只回退 appdaemon
```

常见症状对照：

| 症状 | 最可能原因 | 处理 |
|---|---|---|
| 主页键没反应 / 黑屏 | appdaemon 崩溃循环 | 看 `logcat \| grep StackOverflow`；卸 appdaemon 回原版 |
| Aerial 一离开前台就被杀 | helper.service 被停 | `pm enable com.stv.helper.service` + 重启 |
| 装完重启失效 | versionCode 没抬高 | 重新签，versionCode +1 |
| 改的包被系统压回原版 | `/data` 版本 ≤ `/system` | 同上 |
| 装 APK 提示 Killed | uid 2000 | 走 uid1000 通道 |
| 乐视预装的包删了又回来 | `/system/etc/installpkg.conf` | 只 `disable`，不要 `uninstall` |
| 小电视部分图标空白/破图 | 缓存里的 WebP VP8X 容器 | `bash source/yst-cache/refresh_yst_cache.sh`，见 `docs/06` |

---

## 8. 如果你要扩展

- **加更多信号源入口**：`source/entries/build_entries.py` 的 `ENTRIES` 列表加一行（端口串见第 4 节），重跑即可，versionCode 记得 +1。
- **适配其他乐视机型**：先 `pm path` 找到信号源管理器和 appdaemon，反编译核对 `SourceBase.doSwitchPort` 和 `DaemonHandler.jumpLauncherNeedCheck` 是否同构。包名一样但版本不同的，方法签名可能变。
- **其他品牌电视**：第 4 节的 extraPort 是乐视私有接口。别家（小米/TCL/创维）大概率也有类似的外部切源入口，可以按同样思路挖，但不要假设参数一样。

---

## 9. 应用侧：小电视图标（独立于桌面改造）

云视听小电视（`com.xiaodianshi.tv.yst`）部分图标空白，原因是网络图标的 Fresco 缓存用了 WebP **VP8X 扩展容器**。做法是**手动打补丁、把 VP8X 降级为简单 VP8**：

```bash
cd source/yst-cache
TV_IP=192.168.5.9 ADB=/path/to/adb.exe bash refresh_yst_cache.sh   # pull -> 转换 -> push
```

- 缓存路径：`/sdcard/Android/data/com.xiaodianshi.tv.yst/cache/ImagePipeLine/v2.ols100.1/*/*.cnt`
- 无 alpha 的 VP8X：抽出 `VP8 ` chunk 重组 RIFF，**无损**；带 alpha 的（`ALPH`）：ffmpeg 转 RGBA PNG
- 实测 268 个 VP8X → 0，7.22 MB → 18.01 MB，用户确认有效
- **不动 APK、不重签、不动系统、不丢登录态**；`--restore` 可还原；新图标复发时重跑即可
- 系统 Skia 本身能解 VP8X，**不要给系统打补丁**；详见 `docs/06-vp8x-icon-cache.md`
