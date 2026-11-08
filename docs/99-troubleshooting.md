# 故障排查

按症状查。每条都标注了**怎么确认**和**怎么修**。

---

## 连不上电视

### `adb devices` 是空的 / `unable to connect`

**先确认 ADB 到底开没开**。S50 Air 的开法是遥控器序列，不在设置里：

```
按【信号源】键 → 信号源页面弹出 → 依次按 1、4、7
→ 页面自动消失 = ADB 已开（端口 5555）
```

没消失就重来，中间不要按别的键。

**再确认网络**：
```bash
ping <电视IP>
adb connect <电视IP>:5555
```

**其他常见原因**：
- 电视的 IP 变了（路由器 DHCP 重新分配）→ 去路由器后台查
- 电脑和电视不在同一网段 / 电视连的是 5G 而电脑在 2.4G 的隔离网络
- 有另一个 adb server 占着端口 → `adb kill-server && adb start-server`

### 能连上但命令全失败 / `device offline`

`adb disconnect` 再 `adb connect`。这条通道在乐视固件上很容易掉，所以 `scripts/lib.sh` 里每条命令前都会自动 connect 一次。

---

## 主页键

### 按主页键黑屏 / 没反应 / 卡一下才回来

**确认**：
```bash
adb shell logcat -d | grep -E "StackOverflowError|appdaemon" | tail -20
```
看到 `StackOverflowError` 且伴随 appdaemon 进程反复重启 → 中了原厂 bug。

**修**：`bash scripts/03-appdaemon.sh`（装改过的 appdaemon）。
**临时绕过**：`adb shell pm uninstall com.stv.appdaemon`（回原版，主页键会回乐视桌面但至少不崩）。

---

### 按主页键回到乐视桌面

**确认**：
```bash
adb shell "dumpsys package com.stv.appdaemon | grep versionCode"
adb shell "am start -n app.orchard.tv.lite/.HomeActivity"   # 手动能起来吗
```

手动能起但主页键不灵 → 固件把 HOME 锁死了。

**修**：改 appdaemon，或者改 `Launcher.xml` 里的 `launcher` / `bootlauncher` 两项。

---

### 改了 appdaemon，当时好了，重启又变回去

**确认**：
```bash
adb shell "dumpsys package com.stv.appdaemon | grep -E 'versionCode|codePath'"
```
`codePath` 指回 `/system/app/...` → 版本号没抬高，被系统压掉了。

**修**：重签，versionCode 必须 **大于** `/system` 里那个。

---

### 安装 appdaemon 报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`

签名不匹配。这个包必须用**电视自己的平台密钥**签。

**修**：见 `docs/03-appdaemon.md` 4.4 节。拿不到密钥就只能放弃这条路，改用系统默认桌面弹窗方案。

---

## 信号源

### 按信号源键没反应

**确认**：
```bash
adb shell "am broadcast -a com.letv.android.str.TV_ACTION_ON"
adb shell logcat -d | grep -i "TV_ACTION"
```
广播没被处理 → appdaemon 崩了（见上）或 `str` 接收器被禁用。

注意键码是 **269**，不是 178。用 `getevent` 确认：
```bash
adb shell getevent -l   # 按信号源键，看是哪个 keycode
```

---

### HDMI 入口点了，跑到"上一次用过的 HDMI"

`extraPort` 传了 `"HDMI"`（不带序号）。它走 `handleHardKeyPort()` = 模拟硬键。

**修**：改成 `"HDMI 1"`（有空格，有数字）。

---

### HDMI 入口点了没反应

**确认**：
```bash
adb shell "am start -n com.stv.signalsourcemanager/.MainActivity --es extraPort 'HDMI 2'"
```
命令行也不行 → 信号源管理器被停用或包名变了。

**修**：`adb shell pm enable com.stv.signalsourcemanager`；或 `pm path` 确认包名。

---

### HDMI 入口闪一下白屏/黑屏

Activity 没设透明主题。

**修**：manifest 里加 `android:theme="@android:style/Theme.Translucent.NoTitleBar"`。

---

## 桌面

### Aerial 一离开前台就被杀（切出去回来就重载）

**确认**：
```bash
adb shell logcat -d | grep -E "Force stopping app.orchard.tv.lite|isIllegalApp"
adb shell "dumpsys activity services com.stv.helper | head -5"
```

`helper.service` 被停用 → AMS 的 TvMaster 代理为 null。

**修**：
```bash
adb shell pm enable com.stv.helper.service
adb reboot
```
然后**不要**再停它，只停 `com.stv.helper.main`（UI）。

---

### Aerial 磁贴不刷新 / 装了新 app 不出现

**确认**：
```bash
adb shell "am force-stop app.orchard.tv.lite"
adb shell "am start -n app.orchard.tv.lite/.HomeActivity"
```

Aerial 在应用变化时会刷新，但 4.x 上偶尔漏掉广播。

---

### 想让某个磁贴改名/换图标

不要改 APK。用 Aerial 的手机配置页：控制中心 → 个性化 → 扫码 → 主屏幕页。

---

## 安装

### `adb install` 输出 `Killed`

uid 2000 没有安装权限。走 uid1000 通道：

```bash
adb push x.apk //sdcard/Download/x.apk
echo "pm install -r /sdcard/Download/x.apk" | ...   # 见 docs/02
```

---

### `pm disable-user` 报 `Permission denial`

同上，uid 2000。走 uid1000。

---

### 删掉的包过一阵又回来了

`/system/etc/installpkg.conf` 的预装恢复机制。

**修**：改用 `pm disable-user`，不要 `pm uninstall`。

---

### 重装某个包后，它的 disabled 状态没了

`pm install` 会重置 disabled 状态。装完要重新 `pm disable-user`。

---

## 工具链

### D8 报 `Illegal char <*>`

Windows 上 Java 不展开 glob。

**修**：`$(find classes -name "*.class")` 由 bash 先展开。

---

### javac 报大量乱码错误

编码问题。

**修**：`-encoding UTF-8`。

---

### javac 报 `Unable to find package java.lang`

用了 `-bootclasspath android.jar`，把 JDK 的类也替换掉了。

**修**：改用 `-classpath android.jar`。

---

### 生成的 APK 装不上，报 `Corrupt XML binary file`

手写二进制 AXML 的错误（缺 RESMAP chunk、字符串池没对齐）。

**修**：**不要手写**。用 aapt：
```bash
aapt p -f -M AndroidManifest.xml -I android.jar -F out.apk
```

---

### `Intent.EXTRA_SHORTCUT_DUPLICATE` cannot find symbol

那是 API 17 的常量，API 16 的 android.jar 没有。

**修**：用字面量 `"duplicate"`。

---

## 电视不响应 adb

```bash
ping <TV_IP>
adb connect <TV_IP>:5555
```

- ping 通但 5555 拒绝 → adbd 没跑，电视上重新开 ADB（或重启）
- 都通但 `adb devices` 显示 `offline` → `adb kill-server && adb connect ...`
- 乐视 ADB 端口有时被固件改掉，扫描一下：`nmap -p 5555 <TV_IP>`
