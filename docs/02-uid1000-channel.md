# uid 1000 通道：绕过 shell 权限限制

## 问题

乐视 S50 Air 的 `adbd` 以 **uid 2000 (shell)** 运行，权限被大幅裁剪：

| 操作 | uid 2000 | uid 1000 |
|---|---|---|
| `pm install` | ❌ 进程被 `Killed` | ✅ |
| `pm disable-user` 系统包 | ❌ `Permission denial` | ✅ |
| `pm grant` | ❌ | ✅ |
| `am` 注入按键 | ❌ | ✅ |
| `cat /data/...` | ❌ | ⚠️ 部分 |

而 `adb root` 不可用（eng build 才有），所以需要一条**以 uid 1000 执行命令**的通道。

> **但要先问一句：你真的需要这个通道吗？**
> 触发一个 UI 界面（比如"安装 APK"）是**弹个窗让人点**，不是静默提权，uid 2000 自己就能干。见下面的「不需要 root 的第三条路」。只有要**静默完成**（不点确认）时才必须用 uid 1000 通道。

## 不需要 root 的第三条路：把动作变成"用户点的"

uid 2000 干不了的事里，有一类其实不需要权限 —— **拉起一个界面，让用户在 GUI 上自己点**。因为真正的权限判定发生在系统应用那边（安装器 / 设置 / 文件管理器），不是你的 shell。

### 安装 APK：先 push，再拉系统安装器

```bash
# 1. 推文件（uid 2000 完全够）
MSYS2_ARG_CONV_EXCL="*" adb push app.apk //sdcard/Download/app.apk

# 2. 拉起系统安装器（关键是 --user 0）
adb shell "am start --user 0 -a android.intent.action.VIEW \
  -d file:///sdcard/Download/app.apk \
  -t application/vnd.android.package-archive"

# 3. 电视上出现安装界面 → 遥控器点「安装」
```

实测这个电视的安装器：

```
com.android.packageinstaller/.PackageInstallerActivity
  ← file:// + application/vnd.android.package-archive
  ← content:// + 同上
  ← action INSTALL_PACKAGE
```

**必须加 `--user 0`**，否则：

```
java.lang.SecurityException: Permission Denial: startActivity asks to run as user -2
  but is calling from user 0; this requires android.permission.INTERACT_ACROSS_USERS_FULL
```

这是因为 `am` 默认 `--user current` 解析成了 `-2`（USER_CURRENT），跨用户启动需要额外权限。指定 `0` 就绕过了。

**什么时候用这条路**：**只有第一次装 `com.tvhelper.root` 本身时**。之后所有包都走通道静默安装，不用再碰遥控器。

这是本方案固定的执行顺序：

```
① 装 tvhelper    →  push + 安装器弹窗，遥控器点一次（唯一一次）
② 装其他所有包   →  全部 tvhelper 静默 pm install -r
```

`scripts/00-bootstrap.sh` 就是 ①；② 由 `scripts/lib.sh` 的 `install_apk()` 自动完成（它会先试 uid2000、再试 uid1000，只有都失败才退回安装器）。

### 停用不给停的包 → 没辙

停用组件需要 `CHANGE_COMPONENT_ENABLED_STATE`，没有"弹个窗让用户确认"的替代路径。这个只能走 uid 1000。

### 结论表

| 想做的事 | uid 2000 够吗 | 怎么走 |
|---|---|---|
| push 文件到 `/sdcard` | ✅ | 直接 push |
| **装 APK（弹安装器）** | ✅ | `am start --user 0 -a VIEW` + file:// |
| 装 APK（静默无感） | ❌ | uid 1000 通道 `pm install` |
| 停用/启用系统包 | ❌ | uid 1000 通道 `pm disable-user` |
| `pm grant` 权限 | ❌ | uid 1000 通道 |
| 模拟按键注入 | ❌ | uid 1000 通道 |
| 拉起设置/应用详情页 | ✅ | `am start --user 0 -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:xxx` |

`scripts/lib.sh` 的 `install_apk()` 已经实现了三级降级：`pm install`(uid2000) → `pm install`(uid1000) → 系统安装器弹窗。

## 原理

系统里预装的小工具应用 `com.tvhelper.root` 声明了一个 **以 `android:sharedUserId="android.uid.system"` 运行**的 Service，它读取 `/sdcard/Download/root.sh` 并 `sh` 执行，把输出重定向到 `/sdcard/Download/root.log`。

> 这不是乐视原厂的包，是我们自己造的提权通道，完整源码在 `source/tvhelper/`。名字和乐视 TV管家的 `com.stv.helper.*` 只是巧合，功能无关 —— 别搞混。

核心实现（Java）：

```java
public class Shell extends Service {
    @Override public int onStartCommand(Intent i, int flags, int startId) {
        new Thread(() -> {
            try {
                Process p = Runtime.getRuntime().exec(
                    new String[]{"sh", "/sdcard/Download/root.sh"});
                p.waitFor();
            } catch (Exception ignored) {}
            stopSelf();
        }).start();
        return START_NOT_STICKY;
    }
}
```

因为进程是 `android.uid.system`（uid 1000），派生出的 `sh` 继承 uid 1000，从而拥有 `INSTALL_PACKAGES` 等权限。

manifest 关键部分：

```xml
<manifest package="com.tvhelper.root"
          android:sharedUserId="android.uid.system">
    <application android:persistent="false">
        <service android:name=".Shell" android:exported="true"/>
    </application>
</manifest>
```

> 因为用了 `sharedUserId=android.uid.system`，这个 APK **必须平台签名**才能安装。

## 用法

```bash
# 1. 写脚本到 PC 本地文件
cat > root.sh <<'EOF'
rm -f /sdcard/Download/root.log
pm list packages -d > /sdcard/Download/root.log 2>&1
echo "EXIT=$?" >> /sdcard/Download/root.log
EOF

# 2. 推到电视（注意 MSYS 路径转义）
MSYS2_ARG_CONV_EXCL="*" adb push root.sh //sdcard/Download/root.sh

# 3. 触发
adb shell "am startservice --user 0 -n com.tvhelper.root/.Shell"

# 4. 等 5-10 秒后读结果
sleep 8
adb shell "cat /sdcard/Download/root.log"
```

## 铁律（血泪）

| 规则 | 原因 |
|---|---|
| **每行都必须自己 `>> /sdcard/Download/root.log 2>&1`** | **服务只写它自己的 `rc` 行，不捕获脚本 stdout。** 不加重定向 = 输出丢失，日志里只剩 `=== rc=0 ===` 和 `=== done ===` |
| 脚本第一行 `rm -f /sdcard/Download/root.log` | 否则读到上一次的结果，误判 |
| 每条命令后 `echo "EXIT=$?"` 也要重定向 | 服务不会把 exit code 传回来 |
| 脚本必须是 **LF 换行，不能有 `\r`** | Git-Bash 默认写 CRLF，`sh` 会把 `\r` 当参数一部分 → `rm -f xxx\r` 删不掉文件，后续判断全错 |
| 不用 `head`/`wc`/`sed`/`printf`/here-doc | **电视的 toybox 极简，这些都不存在** |
| 写文件在 PC 端做 | 电视上没有可用文本编辑器 |
| `sleep 6~12` 再读 | 太早读会拿到空文件 |

### 正确 vs 错误示例

```bash
# ❌ 错：输出全丢
adb push script.sh //sdcard/Download/root.sh
# script.sh 内容：
#   pm list packages -d
# 结果：root.log 里只有 "=== rc=0 ==="

# ✅ 对：每行自己重定向
# script.sh 内容：
#   rm -f /sdcard/Download/root.log
#   pm list packages -d >> /sdcard/Download/root.log 2>&1
#   echo "EXIT=$?" >> /sdcard/Download/root.log
```

### CRLF 陷阱

Git-Bash 的 `printf` 默认输出 LF，但如果你从 Windows 编辑器/某些工具生成脚本，可能带 CRLF：

```bash
# 症状：日志里出现 \r\r\n，或 rm 明明执行了却没删掉旧日志
adb shell "cat /sdcard/Download/root.sh" | od -c | head

# 修：写之前过滤
printf '%s\n' "$SCRIPT" | tr -d '\r' > root.sh
```

本仓库 `scripts/lib.sh` 的 `root_exec` 已经处理了这两件事（自动补重定向 + 去 CRLF），直接用它就行。

### 怎么确认通道是好的

```bash
root_exec <<'EOF'
echo "alive"
dumpsys package com.stv.appdaemon 2>&1 | grep -m1 versionCode
EOF
```

期望输出（顺序不定）：

```
alive
    versionCode=2019060620 targetSdk=22
=== rc=0 ===
=== done ===
```

如果只有 `=== rc=0 ===` / `=== done ===`，说明重定向没加。

实测 `wc` 不存在：

```
/sdcard/Download/root.sh[3]: wc: not found
=== rc=127 ===
```

替代：统计行数用 `grep -c ''`，或者把内容拉回 PC 统计。

## 电视上没有这个服务怎么办

**本仓库带完整源码**：`source/tvhelper/`（`Shell.java` 73 行 + manifest + 构建命令 + 验证方法）。

简要步骤：

1. `source/tvhelper/src/com/tvhelper/root/Shell.java` —— 照抄或直接用
2. 用**平台签名**签（和 appdaemon 同一把密钥）
3. 装机走「先 push 再拉系统安装器」：`DRY_RUN=0 bash scripts/00-bootstrap.sh apk/tvhelper.apk`

详见 `source/tvhelper/README.md`。

> **为什么它必须"弹窗装"而后面可以静默**：这个通道存在的意义就是静默装包，所以它自己不能靠静默装 —— 但它可以靠系统安装器装（见上一节）。装好之后，静默能力才出现。**只此一次。**

### 三个实现细节（改的时候别"优化"掉）

| 细节 | 原因 |
|---|---|
| `implements Runnable`，不用匿名内部类 | dex 只产 1 个 class。老 Dalvik 上匿名内部类偶尔 `NoClassDefFoundError` |
| `sh -c "…"` 包一层，不直接 exec 脚本 | 重定向由 shell 解释，Java 侧不用建管道读输出，还能拿到脚本真实退出码 |
| `volatile boolean busy` 防重入 | 连点两次 `am startservice` 不会并发跑两份脚本 |
| `onCreate` 和 `onStartCommand` 都调 `spawn()` | 服务被复用时 `onCreate` 不会再进，只靠它会在第二次调用时静默不执行 |

## 安全提醒

这个通道等价于 root（uid 1000）。脚本内容任何人都能通过 adb 写进去，所以：

- 用完把 `/sdcard/Download/root.sh` 清空
- 不要把电视的 ADB 端口暴露到公网
- 不需要时 `pm disable-user com.tvhelper.root` 关掉
