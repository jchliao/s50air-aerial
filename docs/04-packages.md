# 包清单：停用哪些、为什么、怎么恢复

电视上 `pm list packages -d` 的真实结果（2026-11 实测，共 36 个停用）。

分三批，**建议按批推进并逐批验证**。

---

## A 批：广告 / 上报 / 推送 / 反馈（5 个，零风险）

| 包名 | 作用 | 停用影响 |
|---|---|---|
| `com.stv.bootadmanager` | 开机广告 | 开机不再播广告。**最大收益项** |
| `com.stv.reportlog` | 日志上报 | 无 |
| `com.stv.reportService` | 行为数据上报 | 无 |
| `com.stv.stvpush` | 消息推送 | 收不到乐视推送（广告为主） |
| `com.stv.feedback` | 意见反馈 | 无 |

```bash
for p in com.stv.bootadmanager com.stv.reportlog com.stv.reportService com.stv.stvpush com.stv.feedback; do
  adb shell pm disable-user --user 0 $p
done
```

---

## B 批：内容 / 购物 / 游戏 / 儿童 / 天气（13 个，低风险）

| 包名 | 作用 |
|---|---|
| `com.stv.lap.alitvbuy` | 购物商城 |
| `com.iptv.ylhb` | 内容聚合 |
| `com.newtv.sport` | 体育内容 |
| `cn.tvplay.gunworld` | 游戏 |
| `sina.mobile.tianqitongstv` | 天气（Aerial 自带天气） |
| `com.kuyun.stv.androidtv` | 酷云互动 |
| `com.kuyun.common.androidtv` | 酷云公共库 |
| `com.kuyun.identifer` | 酷云设备标识 |
| `com.stv.guider` | 新手引导 |
| `com.stv.calendar` | 日历 |
| `com.stv.message` | 消息中心 |
| `com.le.lepay.tv` | 支付 |
| `com.stv.music` / `com.tvos.store.music` | 乐视音乐（两个包） |
| `com.amap.android.location` | 高德定位（Aerial 用 IP 定位，不需要） |
| `com.letv.leso` | 乐视搜索 |
| `com.letv.lekids` | 儿童乐园 |
| `com.tencent.qqmusictv.qing` | QQ 音乐 TV（**已卸载**，见下） |

---

## C 批：系统相关（8 个，**逐个看注释**）

| 包名 | 作用 | 能停吗 |
|---|---|---|
| `com.stv.litemode` | 简洁模式（乐视自家桌面） | ✅ 可停，Aerial 替代它 |
| `com.stv.deskplatform` | 乐视桌面 | ✅ 可停（Aerial 替代）。若想保留原桌面别停 |
| `com.stv.net.misc` | 「网络验证」，纯后台 ping 服务 | ✅ 可停，无界面 |
| `com.letv.android.tv.letvlive` | 乐视直播 | ✅ 可停 |
| `com.stv.ucenter` | 账号中心 | ⚠️ 停后部分系统功能可能异常，实测无碍 |
| `com.letv.tvos.appstore` | 应用商店 | ⚠️ 停后装应用只能靠 adb，建议**保留** |
| `com.stv.systemupgrade` | 系统升级 | ⚠️ 停后不再被推送升级（老机器建议停，避免被升崩） |
| `com.stv.helper.main` | TV管家 **UI** | ✅ 可停（**只是界面**，服务不能停） |
| `com.stv.t2.account` | 账号相关 | ✅ 可停 |
| `com.stv.android.videochat` | 视频通话 | ✅ 可停 |
| `com.stv.screenflyter` | 投屏 | ❌ **停前确认不用投屏** |
| `com.stv.downloads` | 下载管理 | ⚠️ 装 APK 时可能用到 |
| `com.kookong.tv.livematch` | 遥控器匹配 | ⚠️ 影响第三方遥控 App |
| `com.letv.combine` | 乐视「组合」聚合（首页聚合容器） | ✅ 可停 |

---

## 绝对不能停（白名单）

| 包名 | 原因 |
|---|---|
| **`com.stv.helper.service`** | **AMS 的 `mTvMasterProxy` 绑定对象。停用后代理为 null → `notifyActivityChanged` 失败 → 前台应用被判 `isIllegalApp` → Aerial 一离开前台就被 force-stop 秒杀。** 详见 `05-helper-service.md` |
| `com.stv.signalsourcemanager` | 信号源管理器，HDMI 直达依赖它 |
| `com.stv.lekey` | 遥控按键分发 |
| `com.stv.filemanager` | 装 APK 用 |
| `com.stv.commonservice` | 公共系统服务。**实测停过，导致系统能力缺失，已恢复** |
| `com.stv.miracast` | 投屏（不用可停） |
| `com.stv.voice` | 语音（不用可停） |

---

## 关于"卸载"vs"停用"

**默认只用 `pm disable-user`，不要 `pm uninstall`。** 原因：

1. 乐视有预装恢复机制：`/system/etc/installpkg.conf`（36 条 MD5）由 `/system/lib/libletvutil.so` 读取，删掉的预装第三方包可能被重新装回。
2. 卸载不可逆（除非有原始 APK），停用一条命令就能回来。
3. 停用的包仍然被 PMS 扫描（`/data/app` 下 28 包 344MB），但对开机速度影响很小 —— 想进一步优化只能卸载，收益有限（纯第三方可删的只有 5 个约 78MB）。

**例外**：`com.tencent.qqmusictv.qing`（QQ 音乐 TV）可以卸载 —— 它是出厂预装的第三方应用（installer = `com.stv.music`，2018-02-12），不是乐视自有组件，卸载释放约 30MB，且实测未被 `installpkg` 机制装回。

```bash
adb shell pm uninstall com.tencent.qqmusictv.qing
```

---

## 恢复

```bash
# 全部恢复
adb shell pm list packages -d | sed 's/package://' | xargs -I{} adb shell pm enable {}

# 单个恢复
adb shell pm enable com.stv.bootadmanager
```

> 注意：`pm install` 会清掉 disabled 状态 —— 重装某个包后要重新 disable。
