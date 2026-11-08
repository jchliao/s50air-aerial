# 乐视 S50 Air → Aerial 桌面改造

把这台 2013 年的乐视 S50 Air（Android 4.3 / API 18）从原厂广告桌面改造成干净的 tvOS 风格桌面，并让它**可控、可恢复**。

> **本仓库面向 AI Agent 使用。** 每个目录都有一份机器可读的操作说明；命令可以直接复制执行。人类读者看 `README` + `docs/` 即可，Agent 直接读 `AGENTS.md`。

## 这套方案做了什么

| # | 项目 | 效果 | 风险 |
|---|---|---|---|
| 1 | 装 Aerial Lite 桌面 | tvOS 风格，无广告，主页键直达 | 低（可卸载） |
| 2 | **修复 appdaemon 的致命递归崩溃** | 主页键 / 信号源键恢复正常 | **中**（需平台签名，动系统应用） |
| 3 | **魔改信号源管理器** | 去掉切换乐视桌面时的崩溃点 | **中**（平台签名） |
| 4 | 停用 36 个广告/上报/购物/儿童包 | 开机快、无弹窗、列表干净 | 低（可逐条 enable） |
| 5 | HDMI 1/2/3 桌面直达磁贴 | 一键进游戏机，无闪屏 | 低（普通自签 APK） |

**核心发现**：原厂 `appdaemon` 有个 bug —— 启动桌面失败时不做失败处理，无限递归 → `StackOverflowError` → 每 100ms 崩溃重启，把主页键和信号源键一起废掉。Android 4.3 上 Aerial 会被系统标成 `stopped=true`，正好触发这个 bug。这是很多老电视换第三方桌面后"主页键失灵"的真正原因。

## 快速开始

**前提**：电视和电脑同局域网，电视已开 ADB（乐视：设置 → 关于 → 连点版本号，或在工程模式开）。

脚本的用法是 `TV_IP=<IP> [DRY_RUN=0] [ADB=/path/to/adb] bash scripts/xx.sh`：

- `TV_IP` 必须给（也可以先 `export TV_IP=192.168.5.9`）
- **默认 `DRY_RUN=1`，只打印不改动**；确认无误后加 `DRY_RUN=0` 才真执行
- adb 从 `PATH` 找，找不到再用 `ADB=` 指定完整路径

```bash
export TV_IP=192.168.5.9

# 0. 确认能连上（乐视 adb 常在 5555）
adb connect $TV_IP:5555 && adb devices

# 1. 先停广告包（最安全，可逆）
bash scripts/01-debloat.sh a          # 先看 dry-run
DRY_RUN=0 bash scripts/01-debloat.sh all

# 2. 装 Aerial Lite 桌面（APK 从上游下载，见 apk/README.md）
DRY_RUN=0 bash scripts/02-install-aerial.sh apk/aerial-lite.apk

# 3. 主页键接管（二选一）
#    3a. 最简：系统会问"用哪个桌面"，选 Aerial + 始终 —— 多数固件够用
#    3b. 彻底：装改过的 appdaemon（需要自己构建，见 docs/03-appdaemon.md）
DRY_RUN=0 bash scripts/03-appdaemon.sh path/to/appdaemon-v3.apk

# 4. 可选：HDMI 直达磁贴
DRY_RUN=0 bash scripts/04-hdmi-entries.sh
```

每一步都先 dry-run 打印将要做什么，确认后才执行。

## 目录

```
AGENTS.md              ← Agent 入口：完整决策树、所有踩过的坑、验证命令
docs/                  ← 分主题深挖（原厂架构、smali 改法、包清单、恢复）
scripts/               ← 幂等可执行脚本（带 dry-run 和回滚）
apk/                   ← 自签的 HDMI 入口 APK（appdaemon / ssm / Aerial 需自行构建，见 apk/README.md）
source/                ← 可复现构建的源码和工具链
```

## 恢复原状

```bash
DRY_RUN=0 bash scripts/99-restore.sh                 # 恢复全部系统应用、卸载 Aerial
DRY_RUN=0 bash scripts/99-restore.sh --keep-aerial   # 只恢复系统应用
DRY_RUN=0 bash scripts/99-restore.sh --only-appdaemon
```

`pm uninstall com.stv.appdaemon` 会自动回退到 `/system/app` 原版；所有 `pm disable` 都能 `pm enable` 回来。**没有任何一步是不可逆的。**

## 已知限制

- **TV管家服务 `com.stv.helper.service` 绝对不能停用**。它是 AMS `mTvMasterProxy` 的绑定对象，禁用后代理为 null → `notifyActivityChanged` 失败 → 前台应用被判 `isIllegalApp` → Aerial 一离开前台就被 force-stop 秒杀。只能停用它的 UI 包 `com.stv.helper.main`。
- 平台签名用的密钥来自本机 dump，**不在仓库里**（见 `docs/03-appdaemon.md` 的「自己签」一节）。
- 只验证过 S50 Air（LetvUi 3.x / Android 4.3）。其他乐视机型大概率同构，但包名和 smali 偏移需要重新核对。

## 许可

脚本和文档 MIT。APK 内是乐视原厂代码的修改版，仅限自用，不要分发。
