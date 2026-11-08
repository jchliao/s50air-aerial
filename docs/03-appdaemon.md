# appdaemon：主页键为什么失灵，以及怎么修

## 1. 这个包是干什么的

`com.stv.appdaemon`（乐视「应用守护」）是乐视桌面的常驻守护进程，职责：

- 开机时决定启动哪个桌面（读偏好 `launcher` / `bootlauncher`）
- 接收主页键事件，把当前前台强行拉回乐视桌面
- 接收信号源键（keycode **269**），广播 `com.letv.android.str.TV_ACTION_ON/OFF`
- 维持乐视桌面的"前台性"，防止被系统回收

它是个 `persistent` 应用（`android:persistent="true"`），由系统 fork 并常驻，**普通应用无法替代，杀不掉，只能替换 APK**。

## 2. 主页键的完整链路

```
遥控器 HOME
  → PhoneWindowManager.interceptKeyBeforeDispatching
    → DesktopManager（乐视定制，framework 里）
      → 通过 AIDL 绑定 com.stv.appdaemon
        → DaemonHandler.handleIntent(intent, ...)
          → isBootStart()?  看 sysprop "boot.start.flag" 是否为空
              ├─ 空 → 开机分支：读 Launcher.xml 的 launcher/bootlauncher
              └─ 非空 → 热键分支：直接跳桌面
            → jumpLauncherNeedCheck(pkg, cls, intent)
```

## 3. 致命 bug：无限递归 → StackOverflowError

原版 `jumpLauncherNeedCheck` 的伪代码：

```java
void jumpLauncherNeedCheck(String pkg, String cls, Intent i) {
    if (isLauncherAlive(pkg)) {           // 存活？
        bringToFront(i);                  // 拉到前台
    } else {
        startLauncher(pkg, cls);          // 尝试启动
        // ← 没有 else 失败处理！
    }
}
```

问题在两处叠加：

1. **`startLauncher` 失败时不处理失败**。启动失败（返回 false / 抛异常）后没有任何标记，函数正常返回。
2. **上层有重试**。`DesktopManager` 发现"桌面还是没起来"，立刻再调一次，间隔约 100ms。

于是：启动失败 → 重试 → 失败 → 重试 …… **无限递归**，最终 `StackOverflowError`，进程崩溃 → persistent 应用被系统立刻重启 → 又崩。表现：

- 主页键完全没反应（appdaemon 大部分时间在崩溃重启中）
- 信号源键也失灵（同一个进程处理）
- 系统卡顿（每 100ms 一次崩溃重启）

### 为什么 Android 4.3 上特别容易触发

Aerial（`app.orchard.tv.lite`）安装后从未被手动启动过时，包管理器会把它标成 **`stopped=true`**（Android 3.1+ 的 "stopped state" 机制，防止新装应用被隐式 Intent 拉起）。而 `startLauncher` 用的是**隐式** `Intent(ACTION_MAIN/CATEGORY_HOME)` 或普通显式 Intent —— 系统直接拒绝启动 stopped 应用，返回失败。

**这就是"换了第三方桌面后主页键废掉"的真正原因**：不是桌面不兼容，是原厂守护进程崩了。

## 4. 修法

### 4.1 我们的改法（最小改动，最稳）

把 `jumpLauncherNeedCheck` 里"检查 + 启动"整段逻辑**替换成直接 startActivity 到 Aerial**，并加上 `INCLUDE_STOPPED_PACKAGES` 标志：

```smali
# com/stv/appdaemon/DaemonHandler.smali
.method public jumpLauncherNeedCheck(...)V
    # new-instance Intent
    new-instance v0, Landroid/content/Intent;
    invoke-direct {v0}, Landroid/content/Intent;-><init>()V

    # setClassName("app.orchard.tv.lite", "app.orchard.tv.lite.HomeActivity")
    const-string v1, "app.orchard.tv.lite"
    const-string v2, "app.orchard.tv.lite.HomeActivity"
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->setClassName(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    # addFlags(0x10200020)
    #   = FLAG_ACTIVITY_NEW_TASK(0x10000000)
    #   | FLAG_ACTIVITY_RESET_TASK_IF_NEEDED(0x00200000)
    #   | FLAG_INCLUDE_STOPPED_PACKAGES(0x00000020)   ← 关键
    const v1, 0x10200020
    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;

    # 兜底：catch 一切异常，绝不让它抛出去
    :try_start
    invoke-virtual {p0}, Lcom/stv/appdaemon/DaemonHandler;->getContext()Landroid/content/Context;
    move-result-object v1
    invoke-virtual {v1, v0}, Landroid/content/Context;->startActivity(Landroid/content/Intent;)V
    :try_end
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :catch_ok

    :catch_ok
    return-void
.end method
```

三个要点，缺一不可：

1. **`FLAG_INCLUDE_STOPPED_PACKAGES`（0x20）** —— 允许启动处于 stopped 状态的包，直接消灭触发条件。
2. **显式 ComponentName** —— 不依赖 Intent 解析，`app.orchard.tv.lite/.HomeActivity` 写死。
3. **try-catch 吞掉异常** —— 即使真的失败也不再往上抛，递归链从源头断掉。

> 为什么不改成"失败就 return false 并让上层停止重试"？因为上层（`DesktopManager`）在 framework 里，也要改 jar 并平台签名，成本高得多。直接把失败变成"不可能发生"更省事。

### 4.2 编译与签名

```bash
# 反编译（需要 baksmali）
java -jar baksmali.jar d appdaemon.apk -o appdaemon-smali

# 改 DaemonHandler.smali 后回编译
java -jar smali.jar a appdaemon-smali -o classes.dex

# 抬高 versionCode（必须！）—— 改 AXML 里的 versionCode 字段
python bump_version.py appdaemon.apk <新versionCode>

# 平台签名（关键：必须用电视认可的证书）
python sign_apk.py <base.apk> classes.dex appdaemon-v3.apk
```

`sign_apk.py` 用的是 `openssl smime -sign -md sha1` 做 v1 JAR 签名。Android 4.3 只认 v1。

### 4.3 版本号为什么必须抬高

安装到 `/data/app` 后，包管理器每次开机扫描会做一件事：

```
/data/app/com.stv.appdaemon-x.apk   ← versionCode 2019060620
/system/app/AppDaemon.apk           ← versionCode 2019060618
```

**两个同包名包共存时，系统保留 versionCode 高的那个。** 如果 `/data` 的不高于 `/system`，重启时 `/data` 版本被丢弃（静默），系统回到原版 —— 这就是很多人反馈"改了当时有效，重启就还原"的真因。所以必须 `versionCode + 1`（我们的成品是 `2019060620`，原版 `2019060618`）。

### 4.4 关于平台签名

`com.stv.appdaemon` 是 `persistent` + `sharedUserId` 关联系统，**必须用平台签名**才能覆盖安装，否则 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。

平台签名密钥的获取（你自己的电视）：

```bash
# 方法 A：从 /system/framework 里找带 platform 证书的包，导出
adb pull /system/app/SomeSystemApp.apk
unzip -p SomeSystemApp.apk META-INF/CERT.RSA > cert.der
# 只能得到公钥；私钥需要从固件签名密钥提取（一般拿不到）

# 方法 B：如果电视 root 且 /system 里有签名工具/密钥，直接取
adb shell "find / -name '*.pk8' -o -name 'platform.x509.pem' 2>/dev/null"

# 方法 C：老乐视部分固件把 platform key 放在 /system/etc/security/
```

**拿不到平台签名怎么办**：放弃改 appdaemon，改用第 3.3 节的"系统弹窗选默认桌面"路径（多数固件够用）。或者用无障碍服务模拟（Aerial 完整版就是这么做的，但 4.x 上不稳定）。

> 本仓库 `apk/appdaemon-v3.apk` 是用本机电视的密钥签的，**在别的电视上装不上**（签名不匹配）。你可以卸掉它然后用自己的密钥重签 `source/appdaemon/` 里的 smali。

### 4.5 回退

```bash
adb shell pm uninstall com.stv.appdaemon
# 系统立刻回退到 /system/app 里的原版，无需重装，无需重启
```

## 5. 验证清单

```bash
# 1. 版本号对
adb shell dumpsys package com.stv.appdaemon | grep versionCode

# 2. 没在崩
adb shell logcat -d | grep -c "StackOverflowError"     # 0

# 3. 主页键有效（手动触发等价路径）
adb shell am start -n app.orchard.tv.lite/.HomeActivity
adb shell dumpsys window | grep mCurrentFocus           # app.orchard.tv.lite/.HomeActivity

# 4. 开机后仍有效（必须重启验证！）
adb reboot && sleep 60
adb shell dumpsys package com.stv.appdaemon | grep versionCode   # 还是新的
adb shell dumpsys window | grep mCurrentFocus                    # Aerial
```

第 4 步是最容易翻车的地方，务必实测。
