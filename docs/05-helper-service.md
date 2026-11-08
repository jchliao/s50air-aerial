# TV管家 helper.service：为什么停了它，Aerial 会被秒杀

这是本方案里**最反直觉**的一条，也是很多人踩坑后找不到原因的地方。

## 现象

停用 `com.stv.helper.service`（TV管家服务）后：

- 开机正常
- Aerial 启动正常
- **但一旦切到别的应用 / 打开信号源 / 按主页键，Aerial 立刻消失**，像被 force-stop 一样
- logcat 里能看到 `Force stopping app.orchard.tv.lite`，但**没有** ANR / Crash 记录

## 原因

TV管家是乐视系统的"应用健康管理"组件。`com.stv.helper.service` 声明了 `persistent=true`，在 `system_server` 启动时通过 AIDL 被 AMS 绑定为 **`mTvMasterProxy`**：

```java
// ActivityManagerService 里的定制逻辑（乐视 framework）
mTvMasterProxy = ITvMaster.Stub.asInterface(
    ServiceManager.getService("tvmaster"));   // 由 helper.service 注册

// 每次 Activity 切换时：
if (mTvMasterProxy != null) {
    mTvMasterProxy.notifyActivityChanged(pkg, cls);
} // ← 当 proxy 为 null 时，这段直接跳过
```

被跳过后，AMS 认为"没有应用在正常状态"，后续的 `isIllegalApp` 判定会Fail-open 成**非法**，于是任何离开前台的应用都会被回收。

**换句话说：helper.service 不只是个管家，它是 AMS 的一个必要代理。没有它，AMS 的活跃度判定整体失效。**

## 我们踩过的弯路

1. 起初以为是 `tvmaster.db` 里的白名单（applevel）问题 —— 把 Aerial 加进去，能好一阵子，但 TV管家 会定期重建这个 db（网络配置覆盖），白名单又丢了。
2. 怀疑是 appdaemon 的 `persistent` 冲突 —— 不是。
3. 最后对比 `pm disable` 前后的 `dumpsys activity` 才定位到 `mTvMasterProxy`。

## 正确做法

**只停 UI 包，不停服务包**：

```bash
# ❌ 绝对不要
adb shell pm disable-user --user 0 com.stv.helper.service

# ✅ 只停界面
adb shell pm disable-user --user 0 com.stv.helper.main
```

`com.stv.helper.main` 是 TV管家的**界面**（应用列表里的那个"电视管家"图标），停掉后：
- 桌面/应用列表看不到它
- 后台服务照常运行，AMS 代理正常
- Aerial 不再被杀

## 顺带说明：为什么魔改版也留不住

我们试过去掉 `persistent` 属性重新打包 `StvHelperService.apk`，想让它不再常驻：

- 它是 `/system/app` 的原版，versionCode = 1
- 魔改版也是 1（改 persistent 属性不改版本号）
- 装到 `/data/app` 后，重启扫描时 versionCode 相同 → `/data` 被丢弃 → 回到原版

**结论：TV管家 两个包都是 `/system/app` 原版，无法通过 `/data` 覆盖长期替代。** 接受它存在，只停 UI 就够。

## 验证

```bash
# 服务在跑
adb shell dumpsys activity services com.stv.helper | head -20
# 或者看进程
adb shell ps | grep stv.helper

# 代理正常（切几次应用后 Aerial 应该还活着）
adb shell am start -n app.orchard.tv.lite/.HomeActivity
adb shell am start -a android.intent.action.VIEW -d about:blank   # 随便开个别的东西
adb shell am start -n app.orchard.tv.lite/.HomeActivity
adb shell dumpsys window | grep mCurrentFocus   # 应该还是 Aerial
```
