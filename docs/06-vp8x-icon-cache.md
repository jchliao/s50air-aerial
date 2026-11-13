# 小电视图标：把 VP8X 手动降级为 VP8

**结论先行**：云视听小电视（`com.xiaodianshi.tv.yst`）里部分网络图标显示不出来，根子在 sdcard 上的 Fresco 图片缓存用了 **WebP VP8X 扩展容器**。修法是**不动 APK、不动系统**，把缓存目录拉到 PC，把 VP8X 里的 `VP8 ` 图像 chunk 抽出来重组成简单 VP8 容器（带 alpha 的转 RGBA PNG），再推回去。**已实测有效**，重启小电视后图标正常。

适用：S50 Air / Android 4.3 / API 18；只针对小电视的图标，不影响 Aerial 桌面。  
工具：`source/yst-cache/`（`patch_yst_cache.py` + `refresh_yst_cache.sh` + 说明）。

> **不做的事**：不给电视的系统镜像 / Skia / libwebp / app 的 native so 打 VP8X 补丁。理由见第 8 节。



---

## 1. 症状

小电视里一部分图标（频道 logo、海报角标等）是空白 / 破图，另一部分正常。重装 app、清「应用数据」都没用，过一阵又坏。

## 2. 定位：为什么是缓存，不是 APK

- 这些图标**由网络下发**，不在 APK 的 `res/` 里；改 APK 内 `.webp` 资源是打偏靶子（曾经做过 `yst-final.apk` 重签补丁包，**没用，别装**）。
- 真正落地的位置是 Fresco 磁盘缓存：

```
/sdcard/Android/data/com.xiaodianshi.tv.yst/cache/ImagePipeLine/v2.ols100.1/*/*.cnt
```

- 这些是 sdcard 上的**普通文件**，与 APK 签名无关，改它不会触发 `PackageParser.collectCertificates` 的逐条 SHA1 校验，也不用卸载重装、**不丢登录态**。
- `.cnt` 只是文件名。Android 的 `BitmapFactory` 按**数据魔数**判断格式、不看扩展名，所以文件名保持不变、只替换内容即可（原包里本来就有「名字是 `.webp`、内容是 PNG」的条目，app 自己就这么用）。

## 3. 一个被证伪的假设（重要）

一开始的判断是「Android 4.3 的 Skia 不认 VP8X 扩展容器」。**这个判断是错的**。

临时写了个平台签名探针（`webpprobe`，已卸载清理），在电视上直接调系统 `BitmapFactory.decodeFile()` 解 9 个 VP8X 样本（含带 `ALPH` 的），**全部解码成功**；只是 `hasAlpha()` 一律返回 false，说明透明通道可能被丢掉。

所以：

- 系统解码器本身能解 VP8X，**不是系统缺陷**，也不该去给系统打补丁。
- 失败更可能发生在 **app 自己的 native 解码 / Fresco 图片管线**这一环（老版本 Fresco 对 VP8X 的 chunk 解析或 alpha 处理有问题），但**没有精确定位到具体代码**。
- 不管哪一环的问题，把 VP8X 降级成最简单的 VP8 容器后，全链路都能吃下去了 —— 这正是本方案有效的原因。

## 4. 降级原理

### 4.1 VP8X 容器结构

```
0   "RIFF" + 4字节长度(小端)
8   "WEBP"
12  "VP8X" + 4字节长度(=10) + 10字节数据
        flags 在偏移 20：0x10 = 有 alpha（后面跟 ALPH chunk）
30  后续 chunk 依次排列：ICCP / ALPH / VP8 / VP8L ...
    每个 chunk = 4字节 FourCC + 4字节长度 + 数据 + (奇数长度补 1 字节 0)
```

简单 VP8 容器则是 `RIFF + WEBP + VP8  + VP8码流`，没有 VP8X 头，也没有 ICCP/ALPH。

### 4.2 无损降级（无 alpha，推荐）

从偏移 30 开始遍历 chunk，找到第一个 `VP8 ` 或 `VP8L`，把它的**码流字节原样抽出**，重组一个新的 RIFF：

```python
p = 30
while p + 8 <= len(d):
    four = d[p:p+4]
    sz  = struct.unpack("<I", d[p+4:p+8])[0]
    if four in (b"VP8 ", b"VP8L"):
        data = d[p+8:p+8+sz]
        pad  = b"\x00" if (sz & 1) else b""
        return (b"RIFF" + struct.pack("<I", 4+8+sz+len(pad)) + b"WEBP"
                + four + struct.pack("<I", sz) + data + pad)
    p += 8 + sz + (sz & 1)
```

**不重新编码**，丢弃的只是 ICC 色彩配置块，图像数据零损失，体积几乎不变。

### 4.3 带 alpha 的必须转 PNG

`flags & 0x10` 表示有 `ALPH` chunk。直接降级会把透明通道丢掉（图标变黑底/白块），所以这类走 ffmpeg 重编码成 RGBA PNG：

```bash
ffmpeg -y -loglevel error -i <file>.cnt -pix_fmt rgba <file>.cnt.png
```

输出必须**以 `.png` 结尾**（ffmpeg 按扩展名选封装，写成 `.new` 会失败）。转完读回内存写回原 `.cnt`，删掉临时文件。

### 4.4 只改 VP8X，其他一律不动

裸 VP8 / VP8L、PNG、JPEG 本来就正常，保持原样。这样能控制缓存体积，避免膨胀触发 Fresco 的 LRU 淘汰、反而导致更多图标重新下载（重新下载又是 VP8X，等于白改）。

## 5. 完整操作

### 5.1 一键（推荐）

```bash
cd source/yst-cache
bash refresh_yst_cache.sh              # 拉取 -> 转换 -> 推回
bash refresh_yst_cache.sh --restore    # 还原成首次备份的原始缓存
```

可用环境变量覆盖默认值：`TV_IP`（默认 `192.168.5.9`）、`ADB`（默认 `adb`）、`PYTHON`（默认 `python3`）、`FFMPEG`。脚本幂等，可反复跑。

### 5.2 手动等价步骤

```bash
export TV_IP=192.168.5.9
export MSYS2_ARG_CONV_EXCL="*"        # Windows MSYS/Git Bash 必须，否则路径被改写
ADB=/path/to/adb.exe
DEV=$TV_IP:5555
REMOTE=/sdcard/Android/data/com.xiaodianshi.tv.yst/cache/ImagePipeLine

$ADB connect $DEV
$ADB -s $DEV pull "$REMOTE" ./tmpimg/pipe           # 整目录拉到 PC

python patch_yst_cache.py                           # 智能降级；首次运行自动备份 tmpimg/pipe.bak

$ADB -s $DEV push ./tmpimg/pipe/v2.ols100.1 "$REMOTE/"

# 让 Fresco 重建索引
$ADB -s $DEV shell "am force-stop com.xiaodianshi.tv.yst"
# 重新打开小电视；必要时重启电视
```

排障用 `python patch_yst_cache.py --strategy=png-all`（全部 WebP 转 PNG），体积会涨到 50MB+，**只用于判断是不是容器问题**。

## 6. 实测数据（本机缓存）

| 项       | 数量 / 数值                                         |
| ------- | ----------------------------------------------- |
| 缓存文件总数  | 454                                             |
| 改造前格式   | VP8X 268 / 裸 VP8 153 / PNG 32 / JPEG 1          |
| VP8X 细分 | `ICCP+VP8` 154、`ALPH+VP8` 111、`ICCP+ALPH+VP8` 3 |
| 处理      | 无损降级 154 个；转 RGBA PNG 114 个；其余 186 个不动          |
| 改造后     | VP8X **268 → 0**                                |
| 体积      | 7.22 MB → 18.01 MB（全转 PNG 会到 ~52.6 MB，不采用）      |

用户确认：**有效**。

## 7. 踩过的坑

| 坑                                       | 处理                                     |
| --------------------------------------- | -------------------------------------- |
| ffmpeg 输出写成 `.cnt.new` 无法识别             | 输出必须以 `.png` 结尾                        |
| Windows 下从 adb 输出读到的路径带 `\r`            | `tr -d '\r'` 再拼路径                      |
| 中断后残留 `.cnt.png` / `.cnt.new`，下次被当成缓存文件 | 脚本开头先清理，并跳过这类后缀                        |
| Git Bash 把 `/sdcard/...` 转成 Windows 路径  | `MSYS2_ARG_CONV_EXCL="*"`              |
| adb server 会掉                           | 每条命令前先 `adb connect`                   |
| 全量转 PNG 体积暴涨、触发 LRU                     | 改混合策略：无 alpha 无损降级，只有带 alpha 的转 PNG    |
| 改 APK 内 `.webp` + 重签                    | 无效，图标不在 APK 里；`yst-final.apk` 别装       |
| 推出去后图标没变化                               | `am force-stop` 后重进，或重启电视让 Fresco 重建索引 |

## 8. 为什么不给电视打 VP8X 补丁

| 设想                                            | 结论                                              |
| --------------------------------------------- | ----------------------------------------------- |
| 给系统 Skia / libwebp 打补丁让它「支持 VP8X」             | **没靶子**。探针证明系统 `BitmapFactory` 本来就能解 VP8X。      |
| 替换小电视 `/data/data/.../lib/*.so` 里的 native 解码库 | 目标函数未定位，且 app 升级会覆盖，风险/收益不划算。                   |
| 常驻 `FileObserver` 自动转码新缓存                     | 要常驻后台、要处理并发和 LRU，还可能被后台清理策略杀掉；而缓存降级脚本一次几秒、可重复跑。 |
| 改 APK 资源 / 重签                                 | 无效（见第 2 节）。                                     |

**最终取舍**：不动系统、不动 APK，只对 sdcard 上的缓存做一次可还原的手动降级。缺点是新下载的 VP8X 图标还可能复现 —— 复现时再跑一次 `refresh_yst_cache.sh` 即可。

## 9. 还原与复发

- 还原：`bash refresh_yst_cache.sh --restore`，或 `python patch_yst_cache.py --restore` 后手动 push。原始缓存另有 zip 备份（`yst-cache-original.zip`，放在本机工作目录，未入仓库）。
- 复发（用了新频道 / 清过缓存后出现新破图）：重跑第 5 节，脚本会自动识别并只处理新出现的 VP8X。
- 这个方法完全不触碰 `/system`，不影响主页键、信号源、后台保活等其它改造。
