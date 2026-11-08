# source/entries — HDMI 直达入口构建

产出 `apk/hdmi1.apk`、`apk/hdmi2.apk`、`apk/hdmi3.apk`。

## 为什么是一源一包

Aerial 的磁贴是**按包名去重**的（`queryIntentActivities` 后按 packageName 分组）。一个 APK 里注册 3 个 LAUNCHER Activity，桌面也只显示 1 个磁贴。所以每个信号源必须独立包名。

## 结构

```
build_entries.py                 构建脚本（一条命令出三个包）
entry_template/JumpActivity.java 入口 Activity 模板（PKGPLACEHOLDER / PORTPLACEHOLDER）
src/                             主配置 app 的源码（可选，用于调试切源）
AndroidManifest.sourceshortcut.xml  主 app 的明文 manifest 参考
sign_shortcut.py                 v1 签名（自签证书，非平台签名）
```

## 构建

```bash
# 1. 准备工具链（只需一次）
bash ../tools/fetch-tools.sh
# 把工具链放到本目录的 tools/ 下（build_entries.py 里路径是写死的）
mkdir -p tools && cp ../tools/bin/* tools/

# 2. 准备自签证书（只需一次）
openssl req -x509 -newkey rsa:2048 -keyout user.key -out user.x509.pem \
  -days 10000 -nodes -subj "/CN=SourceShortcut"

# 3. 构建
python build_entries.py
```

## 加一个信号源

改 `build_entries.py` 的 `ENTRIES`：

```python
ENTRIES = [
    ("com.tv.hdmi1", "HDMI 1", "HDMI 1"),
    ("com.tv.hdmi2", "HDMI 2", "HDMI 2"),
    ("com.tv.hdmi3", "HDMI 3", "HDMI 3"),
    # 新增：
    ("com.tv.av",    "AV",     "Composite"),
    ("com.tv.dtv",   "DTV",    "Digital TV"),
]
```

三个字段分别是 **包名**、**桌面显示名**、**extraPort 值**。

`extraPort` 合法值（必须是这些字符串，大小写和空格都不能变）：

| 值 | 信号源 |
|---|---|
| `Analog TV` | ATV |
| `Digital TV` | DTV |
| `Composite` | AV |
| `YPBPR` | 分量 |
| `VGA` | VGA |
| `HDMI 1` / `HDMI 2` / `HDMI 3` | 对应 HDMI |

**不要用 `HDMI`（不带序号）** —— 那是模拟遥控器硬键，行为是"回到上次的口"。详见 `docs/AGENTS.md` 第 4 节。

## 实现要点

```java
// JumpActivity.java 核心
Intent t = new Intent();
t.setClassName("com.stv.signalsourcemanager", "com.stv.signalsourcemanager.MainActivity");
t.putExtra("extraPort", PORT);
t.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
startActivity(t);
finish();   // 立刻退出，不留界面
```

manifest 必须加透明主题，否则会闪一下白/黑窗口：

```xml
<activity android:name=".JumpActivity"
    android:exported="true"
    android:theme="@android:style/Theme.Translucent.NoTitleBar"
    android:screenOrientation="landscape">
```

## 改名 / 换图标

**不要改 APK 重新打包**（versionCode 一变就要重装）。用 Aerial 的手机配置页：

1. 电视：控制中心 → 个性化 → 出现二维码
2. 手机扫码 → 主屏幕页 → 选中目标磁贴 → 改名 / 上传图标

改完立即生效，重启不丢。
