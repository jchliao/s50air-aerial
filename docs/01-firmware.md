# 原厂架构：这台电视是怎么被组织起来的

了解这些，你才知道哪些能动、哪些不能动。

## 系统层级

```
Android 4.3 (API 18) / Dalvik / LetvUi 3.x
├── /system/framework/
│   ├── framework.jar           ← 被乐视定制过（DesktopManager、TvMaster 代理）
│   ├── services.jar            ← ActivityManagerService 定制（mTvMasterProxy）
│   └── android.policy.jar      ← PhoneWindowManager 定制（HOME/信号源键拦截）
├── /system/app/                ← 系统应用（38 个乐视自有 + 少量第三方预装）
├── /system/etc/installpkg.conf ← 预装包 MD5 清单（36 条），由 libletvutil.so 读取
└── /data/app/                  ← 用户安装 + 我们覆盖的包
```

## 关键系统应用

| 包名 | APK | 职责 | 我们的处理 |
|---|---|---|---|
| `com.stv.appdaemon` | AppDaemon.apk | 桌面守护、主页键落地、信号源键广播、开机启动桌面 | **魔改**（修递归 bug） |
| `com.stv.signalsourcemanager` | SignalSourceManager.apk | 信号源管理与切换 | **魔改**（去崩溃点） |
| `com.stv.deskplatform` | DeskPlatform.apk | 乐视桌面 | 停用（Aerial 替代） |
| `com.stv.litemode` | LiteMode.apk | 简洁模式桌面 | 停用 |
| `com.stv.helper.service` | StvHelperService.apk | TV管家服务（AMS 代理） | **必须保留** |
| `com.stv.helper.main` | StvHelper.apk | TV管家界面 | 停用 |
| `com.stv.lekey` | LeKey.apk | 遥控按键分发 | 保留 |
| `com.stv.commonservice` | CommonService.apk | 公共系统服务 | 保留 |
| `com.stv.t2.globalsetting` | GlobalSetting.apk | 全局设置 | 保留 |

### 不是原厂的：`com.tvhelper.root`

这个包**不是乐视预装的**，是我们为了绕过 uid 2000 权限限制自己造的通道（`/data/app` 里，4.5 KB，平台签名 + `sharedUserId=android.uid.system`）。它只做一件事：收到 `am startservice` 就把 `/sdcard/Download/root.sh` 以 uid 1000 跑一遍。

源码在 `source/tvhelper/`，原理和构建见 `02-uid1000-channel.md`。名字虽然叫 tvhelper，但和乐视的 TV管家（`com.stv.helper.*`）毫无关系 —— 这是唯一一处容易搞混的地方。

## 三个按键的完整链路

### 主页键

```
遥控器 HOME (keycode 3)
→ PhoneWindowManager.interceptKeyBeforeDispatching  [android.policy.jar 定制]
  → DesktopManager.handleHomeKey()
    → AIDL → appdaemon DaemonHandler.handleIntent
      → isBootStart()?  看 sysprop "boot.start.flag"
      → jumpLauncherNeedCheck(...)  [我们改的就是这里]
```

### 信号源键

```
遥控器信号源键 (keycode 269, 不是 178!)
→ PhoneWindowManager 定制分支
  → 广播 com.letv.android.str.TV_ACTION_ON (按下) / TV_ACTION_OFF (松开)
    → 由 appdaemon 的 StrBroadcastReceiver 接收
      → 打开信号源管理器的 Tab 界面
```

原版还有个"信号源标志"机制：`Launcher.xml` 里的 `flag.clear.str` 存一组 sysprop 名单，`TV_ACTION_OFF` 时清空 `boot.start.flag` / `letv.cibn.show.flag` / `service.launcher.boot.ready`。**但这些 sysprop 都没有 `persist.` 前缀，重启即丢** —— 所以原版没有跨重启的界面记忆。想自己加"开机进上次的信号源"，要用 `persist.` 前缀的属性（存 `/data/property`，断电不丢）。

### 开机

```
Bootloader → Kernel → init.rc
→ zygote → system_server
  → AMS 启动，绑定 TvMaster 代理 (helper.service)
  → appdaemon（persistent）被 fork
    → 读 sysprop "boot.start.flag"
       ├─ 空 → 开机分支：读偏好 launcher/bootlauncher → 启动桌面
       └─ 非空 → 热启动分支
```

`boot.start.flag` 是"非开机"标记：由 `StrBroadcastReceiver` 在收到 `TV_ACTION_OFF` 时设置，用来区分"开机第一次"和"后续主页键"。没有 `persist.` 前缀，重启自动清空 —— 这个设计是刻意的。

## appdaemon 的偏好文件

`Launcher.xml`（`/data/data/com.stv.appdaemon/shared_prefs/`）关键项：

```xml
<string name="launcher">app.orchard.tv.lite/com.orchard.tv.lite.HomeActivity</string>
<string name="bootlauncher">app.orchard.tv.lite/com.orchard.tv.lite.HomeActivity</string>
```

把这两项指向 Aerial 是"温和接管"的第一步。但因为 `jumpLauncherNeedCheck` 的 bug，光改偏好不够（见 `03-appdaemon.md`）。

**修改方法**（需要 uid1000 通道 + 重启 appdaemon）：

```bash
# 1. 备份
adb pull /data/data/com.stv.appdaemon/shared_prefs/Launcher.xml Launcher.xml.bak

# 2. 改成 Aerial（PC 端改好）
# 3. push 回去（注意：必须同时改 owner，否则 appdaemon 读不到）
adb push Launcher.xml /sdcard/Download/Launcher.xml
# uid1000 脚本里：
#   cp /sdcard/Download/Launcher.xml /data/data/com.stv.appdaemon/shared_prefs/Launcher.xml
#   chown $(stat -c %u:%g /data/data/com.stv.appdaemon) /data/data/com.stv.appdaemon/shared_prefs/Launcher.xml
#   chmod 660 ...

# 4. 重启 appdaemon 生效（persistent 应用不能 kill -9，要重启电视）
```

## 开机速度：能改的和不能改的

实测数据（`/data/app` 共 28 包 344MB）：

- **不能改**：bootloader、kernel、init 序列、乐视 SystemServer 的大量定制初始化
- **能改但收益小**：停用的包仍被 PMS 扫描；纯第三方可删的只有 5 个约 78MB
- **收益最大**：停 `com.stv.bootadmanager`（消除开机广告等待）。广告播放本身的等待时间（10-30 秒）比任何 dex 优化都值钱

结论：**别在开机速度上花太多精力**，停广告包 + 换轻桌面就是主要收益。

## 预装恢复机制

`/system/etc/installpkg.conf` 有 36 条记录，格式是 `包名|MD5`。`/system/lib/libletvutil.so` 在开机时读取，发现缺失就尝试重装（从固件的隐藏分区或网络）。

**含义**：删掉的**乐视自有预装包**可能被装回来。第三方包（如 QQ音乐 TV）实测不会被装回。

**应对**：优先 `pm disable-user` 而不是 `pm uninstall`。
