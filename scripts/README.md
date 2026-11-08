# scripts/

幂等脚本，**默认 dry-run**（只打印，不执行）。加 `DRY_RUN=0` 才真的动电视。

```bash
export TV_IP=192.168.5.9

# 第一步永远是它（后面所有脚本都依赖这个通道）
DRY_RUN=0 bash scripts/00-bootstrap.sh apk/tvhelper.apk

bash scripts/01-debloat.sh a             # 预演 A 批停用
DRY_RUN=0 bash scripts/01-debloat.sh a   # 真执行
```

| 脚本 | 作用 | 可回滚 |
|---|---|---|
| `lib.sh` | 公共函数（连接、uid1000 通道、三级安装降级、确认） | — |
| `00-bootstrap.sh [apk]` | **第一步**：装 uid1000 通道。唯一需要遥控器点确认的一步 | ✅ 卸载 |
| `01-debloat.sh [a\|b\|c\|all]` | 停用广告/上报/内容包 | ✅ `pm enable` |
| `02-install-aerial.sh` | 装 Aerial + 授权 | ✅ 卸载 |
| `03-appdaemon.sh` | 装改过的 appdaemon（主页键） | ✅ `pm uninstall` 回原版 |
| `04-hdmi-entries.sh` | 装 HDMI 1/2/3 磁贴 | ✅ 卸载 |
| `99-restore.sh` | 全恢复 | — |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TV_IP` | 必填 | 电视局域网 IP |
| `DRY_RUN` | `1` | `0` 才真执行 |
| `ROOT_WAIT` | `8` | uid1000 通道等待秒数，慢的机器调大 |
| `ADB` | （空） | adb 可执行文件路径；不填则用 PATH 里的 `adb` |

## 前置

`adb` 要么在 PATH 里，要么用 `ADB=` 指定完整路径（脚本还会自动找 `~/platform-tools/adb`、Android/Sdk 默认位置）。都找不到会直接提示下载地址，不会跑到一半才失败。

Windows / Git Bash 用户：脚本已经处理了 `MSYS2_ARG_CONV_EXCL`（否则 `/sdcard/x` 会被改写成 `C:/Program Files/Git/sdcard/x`）。

## 顺序

严格按 **00 → 01 → 02 → 03 → (04)**。`00` 装好 uid1000 通道之前，其余脚本会全部失败。`03` 依赖 `02`（appdaemon 要指向 Aerial 的 ComponentName）。`02` 之后先按一次主页键，如果能弹窗选默认桌面，就**不需要** `03`。
