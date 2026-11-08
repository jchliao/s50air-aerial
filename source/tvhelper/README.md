# source/tvhelper — uid 1000 执行通道

这是整套改造的**地基**。没有它，`adb shell`（uid 2000）装不了包、停不了系统组件、注入不了按键。

## 它做什么

一个 4.5 KB 的极简 Service APK：

```
收到 am startservice  →  new Thread  →  /system/bin/sh -c "…重定向…sh /sdcard/Download/root.sh"
                                                  ↓
                                     /sdcard/Download/root.log
```

因为 manifest 里有 `android:sharedUserId="android.uid.system"` 且用平台密钥签名，进程 uid 是 **1000**，派生的 `sh` 继承这个身份，于是 `pm`/`settings`/`am` 全都有系统权限。

## 为什么能这么干

Android 的 `sharedUserId` 机制允许同签名（且同 sharedUserId 声明）的包共享进程 uid。系统框架本身就是 `android.uid.system`，所以只要签名一致，你的 Service 就"寄生"在系统进程组里。

两个必要条件，缺一不可：

| 条件 | 不满足时的报错 |
|---|---|
| `android:sharedUserId="android.uid.system"` | 只能在自家沙箱里跑，权限全无 |
| 用**电视的平台密钥**签名 | `INSTALL_FAILED_SHARED_USER_INCOMPATIBLE` |

## 源码

| 文件 | 说明 |
|---|---|
| `src/com/tvhelper/root/Shell.java` | 全部逻辑，73 行 |
| `AndroidManifest.xml` | package / sharedUserId / 7 个权限声明 |

实现上有三个刻意的选择，改的时候别"优化"掉：

1. **`implements Runnable` 而不是匿名内部类** —— dex 里只产出 1 个 class。老 Dalvik 上匿名内部类偶尔会 `NoClassDefFoundError`。
2. **`sh -c` 包一层，不直接 exec 脚本** —— 重定向由 shell 解释，Java 侧不用建管道读输出，还能拿到脚本真实退出码。
3. **`busy` 标志位防重入** —— 连点两次 `am startservice` 不会并发跑两份脚本。

## 构建

需要 JDK 17 + 一份 `android.jar`（API 18）+ d8 + aapt2 + 平台密钥。

```bash
# 变量：JAVA / R8 / AJ(android.jar) / AAPT2 按你本机路径改
# Windows/Git-Bash 上给 java 传路径务必用 cygpath -w，否则 ClassNotFoundException

mkdir -p out/classes out/dex

# 1. javac（-classpath 不要用 -bootclasspath）
"$JAVA" -encoding UTF-8 -source 8 -target 8 -nowarn \
        -classpath "$(cygpath -w $AJ)" -d out/classes \
        src/com/tvhelper/root/Shell.java

# 2. d8 → classes.dex（r8 8.x 独立 jar；build-tools 里的 d8.jar 是壳，别用）
"$JAVA" -cp "$(cygpath -w $R8)" com.android.tools.r8.D8 \
        --min-api 18 --lib "$(cygpath -w $AJ)" --output out/dex \
        "$(cygpath -w out/classes/com/tvhelper/root/Shell.class)"

# 3. aapt2 打包 manifest + resources
"$AAPT2" link -o out/base.apk -I "$(cygpath -w $AJ)" \
        --manifest AndroidManifest.xml \
        --min-sdk-version 18 --target-sdk-version 18

# 4. 塞 dex + v1 签名（Android 4.3 只认 v1）
#    需要 CWD 下有 platform.key / platform.x509.pem
python ../tools/sign_apk.py out/base.apk out/dex/classes.dex tvhelper.apk
```

产物 `tvhelper.apk` ≈ 4.5 KB。

签名用的 `platform.key` / `platform.x509.pem` **不在仓库里**，得从你的电视固件里取，见 `../../docs/03-appdaemon.md` 的「自己签」一节。

**踩过的坑**：

- `-bootclasspath` 在 JDK 17 上会报 `Unable to find package java.lang`，用 `-classpath`
- Windows 版 java 不认 `/c/...` 路径，`-cp` / `--output` / 输入文件都要 `cygpath -w`
- `android-14/lib/d8.jar`（build-tools 自带）是 redirector，`com.android.tools.r8.D8` 类不在里面。要单独下 `r8.jar`
- 签名脚本从**当前工作目录**找 `platform.key`，先 `cd` 到密钥所在目录再跑

## 安装

```bash
# 此时 shell 还没有权限装包，所以第一条路只能是：
#   A. 电视上的文件管理器打开 APK 手动安装
#   B. U 盘拷进去，用乐视预装的"文件管理"
#   C. 如果电视上有别的提权手段，用它
pm install -r tvhelper.apk
```

> 这一步是**先有鸡还是先有蛋**：通道装好之前，`adb install` 会直接 `Killed`。

## 验证

```bash
printf 'echo alive; id\n' > root.sh
MSYS2_ARG_CONV_EXCL="*" adb push root.sh //sdcard/Download/root.sh
adb shell "am startservice --user 0 -n com.tvhelper.root/.Shell"
sleep 6
adb shell "cat /sdcard/Download/root.log"
```

期望：

```
=== start ===
uid: uid=1000(system) gid=1000(system) ...
alive
=== rc=0 ===
=== done ===
```

看到 `uid=1000` 就成功了。只看得到 `=== start ===` 而没有脚本输出，是没加重定向 —— 见 `../../docs/02-uid1000-channel.md` 的铁律。

## 安全

这个通道**等价于 root**，而且任何能连上 ADB 的人都能往里写脚本。所以：

- 别把电视 ADB 端口映射到公网
- 用完可以 `pm disable-user com.tvhelper.root` 关掉（下次要用再 enable）
- `/sdcard/Download/root.sh` 是明文可读的，别往里面写密钥

## 和 `com.stv.helper.*` 不是一回事

名字像，但完全无关，别搞混：

| 包 | 是什么 |
|---|---|
| `com.tvhelper.root` | **本目录**，我们自己造的提权通道 |
| `com.stv.helper.main` | 乐视 TV管家的 UI，可以停 |
| `com.stv.helper.service` | 乐视 TV管家服务，**绝对不能停**（见 `../../docs/05-helper-service.md`） |
