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

## 原理

系统里预装的小工具应用 `com.tvhelper.root` 声明了一个 **以 `android:sharedUserId="android.uid.system"` 运行**的 Service，它读取 `/sdcard/Download/root.sh` 并 `sh` 执行，把输出重定向到 `/sdcard/Download/root.log`。

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
| 脚本第一行 `rm -f /sdcard/Download/root.log` | 否则读到上一次的结果，误判 |
| 每条命令后 `echo "EXIT=$?" >> root.log` | 服务不会把 exit code 传回来 |
| 全部输出重定向到文件 | adb shell 拿不到子进程 stdout |
| 不用 `head`/`wc`/`sed`/`printf`/here-doc | **电视的 toybox 极简，这些都不存在** |
| 写文件在 PC 端做 | 电视上没有可用文本编辑器 |
| `sleep 6~12` 再读 | 太早读会拿到空文件 |

实测 `wc` 不存在：

```
/sdcard/Download/root.sh[3]: wc: not found
=== rc=127 ===
```

替代：统计行数用 `grep -c ''`，或者把内容拉回 PC 统计。

## 电视上没有这个服务怎么办

需要自己做一个：

1. 写一个最小的 Service APK（`source/tools/` 里有模板思路）
2. 用**平台签名**签（和 appdaemon 用同一把密钥）
3. `adb install`（此时需要能装 —— 如果 uid 2000 装不了，先想办法，比如 U 盘 + 电视文件管理器，或用乐视的应用商店侧载）

> 本仓库不自带这个 APK 的源码，因为它和本方案核心目标无关（只是执行通道）。可以照上面 30 行实现自己写。

## 安全提醒

这个通道等价于 root（uid 1000）。脚本内容任何人都能通过 adb 写进去，所以：

- 用完把 `/sdcard/Download/root.sh` 清空
- 不要把电视的 ADB 端口暴露到公网
- 不需要时 `pm disable-user com.tvhelper.root` 关掉
