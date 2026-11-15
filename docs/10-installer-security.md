# 10 · 关闭系统安装器的安全检查

日期：2026-11-15 · 状态：**已生效**（`/data/app` 覆盖，原 `/system/app` 版本完整保留）

## 问题现象

芒果TV 自升级时弹出「**此应用存在安全隐患，为了您的电视安全，已禁止安装**」。
焦点窗口 `com.android.packageinstaller/.PackageInstallerActivity`（系统安装器，不是 TV管家）。
触发源是芒果TV 下载的自升级包 `/sdcard/Android/data/com.starcor.mango/cache/apk/HunanOTT_V7.2.202.390.3.SHAFA_TVAPP.0.0_Release.apk`。

## 逆向结论：安装器有**两层**拦截

反编译 `/system/app/PackageInstaller.apk`（versionCode 18，`4.3-1.1.18`）后定位：

| 层 | 判断 | 命中后 |
|---|---|---|
| 1 · 黑名单 | `com/android/packageinstaller/c.1.smali` → `a(Context,String,String)Z` 调 `letv/tvmaster/TvMasterManager.checkPermission(包名, 1)`；`checkPermission(client, 13)` 是商店豁免 | `PackageInstallerActivity.c(7)` → 「此应用存在安全隐患…已禁止安装」 |
| 2 · 未知来源 | `PackageInstallerActivity.l()Z` 读 `Settings.Secure install_non_market_apps` | dialog 2 → 「为安全起见，系统已禁止安装非官方渠道…解除禁止/取消」 |

`A.smali` 的 `allowed_sources` 只是「允许来源」对话框回调，不是总开关；**安装器没有全局安全开关**。

## 改动（最小）

把 `c.a(Context,String,String)Z` 整个方法替换为恒返回 false，即「任何包都不在黑名单」：

```smali
.method public static a(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;)Z
    .registers 8
    const/4 v0, 0x0
    return v0
.end method
```

其余安装流程（解析、权限列表、用户确认）完全不动。

## 出包与安装

1. `baksmali` 反编译 → 改 `c.1.smali` → `org.jf.smali.Main` 重编译 `classes-new.dex`
2. `aerial-tools/build/sign_apk.py` 替换 dex + 平台签名
3. `aerial-tools/build/bump_version.py` 抬 **versionCode 18 → 19**（否则重启会被 `/system/app` 压掉）
4. uid1000 通道 `pm install -r` → `Success`

```
pm path com.android.packageinstaller
  package:/data/app/com.android.packageinstaller-1.apk
  versionCode=19   flags=[ SYSTEM HAS_CODE UPDATED_SYSTEM_APP ]
```

## 静态强校验

- 21 个条目中仅 5 个变化：`AndroidManifest.xml`、3 个 `META-INF` 签名文件、`classes.dex`
- 所有 `res/*` 与 `resources.arsc` **逐字节未变**
- 51 个 smali 文件**仅 `c.1.smali` 变化**
- `CERT.RSA` 证书指纹与原包一致（平台签名）

## 实测

装完弹窗消失；再用刚才被拦的自升级包触发，第一层不再出现，改为显示第二层「非官方渠道」提示 → 黑名单检查确认已关。
第二层是系统设置项（`安装非官方渠道应用`），`settings put secure install_non_market_apps 1` 在这台 4.3 上返回 0 但值仍 `null`（命令写不进），用户表示安装问题已解决，未再继续。

## 回退

```bash
pm uninstall com.android.packageinstaller       # 回到 /system/app 原版 v18
```

原 APK 备份在 `aerial-tools/build/assets/app/PackageInstaller.apk`，产物 `aerial-tools/build/pi-nosec-v19.apk`，
smali 备份 `pi-smali/c.1.smali.bak`，日志 `pi-smali/install.log`。

> 与 `libskia.so` 补丁无关，两个改动互相独立。
