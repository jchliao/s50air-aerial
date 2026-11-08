# apk/

预构建产物。

## 在仓库里的

| 文件 | 说明 | 许可 |
|---|---|---|
| `hdmi1.apk` `hdmi2.apk` `hdmi3.apk` | HDMI 直达入口，3.4KB/个 | MIT（本仓库自写，无第三方代码） |

## 需要自己准备的（不在仓库里）

| 文件 | 从哪来 | 为什么不在 |
|---|---|---|
| `aerial-lite.apk` | https://aerial.qust.me/download/aerial-lite.apk 或 GitHub Releases | 上游 MIT 项目，直接装官方版即可，不重复分发 |
| `appdaemon-v3.apk` | **自己构建**，见 `docs/03-appdaemon.md` | 乐视专有代码的修改版，且必须用**你自己电视的平台密钥**签名 |
| `ssm-v3.apk` | 同上（`source/tools/patch_ssm_v3.py`） | 同上 |

> **appdaemon / ssm 一定要自己签。** 本机签的包装到别的电视上会报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。这不是 bug，是 Android 的签名保护。

## 构建 HDMI 入口

```bash
cd ../source/entries && python build_entries.py
cp entries/*.apk ../../apk/
```
