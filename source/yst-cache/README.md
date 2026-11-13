# yst-cache：小电视图标 VP8X → VP8 降级工具

完整说明（原理、实测数据、坑、为什么不给系统打补丁）在 [`../../docs/06-vp8x-icon-cache.md`](../../docs/06-vp8x-icon-cache.md)。

## 文件

| 文件 | 作用 |
|---|---|
| `patch_yst_cache.py` | 纯 PC 端转换。扫描 `tmpimg/pipe/**/*.cnt`，把 VP8X 降级；幂等，首次运行自动备份到 `tmpimg/pipe.bak` |
| `refresh_yst_cache.sh` | 一键：`adb pull` → 转换 → `adb push` → 提示重启小电视 |

运行时产生的 `tmpimg/` 和可选备份 `yst-cache-original.zip` 是本机数据，不入库。

## 前置

- 电视已开 ADB（S50 Air：按【信号源】→ 依次按 1、4、7）
- PC 有 `adb`、Python 3、`ffmpeg`
- Git Bash / MSYS 下脚本已设 `MSYS2_ARG_CONV_EXCL="*"`，不用担心 `/sdcard` 被改写

## 用法

```bash
cd source/yst-cache
TV_IP=192.168.5.9 ADB=/path/to/adb.exe bash refresh_yst_cache.sh
```

只转换（自己 pull/push）：

```bash
python patch_yst_cache.py                       # 智能策略：无 alpha 无损降级，带 alpha 转 PNG
python patch_yst_cache.py --strategy=png-all   # 全转 PNG，体积 50MB+，仅排障
python patch_yst_cache.py --restore            # 从 pipe.bak 还原
```

环境变量：`YST_CACHE_DIR` 改缓存目录、`FFMPEG` 指定 ffmpeg 路径。

## 验证与还原

推回后 `am force-stop com.xiaodianshi.tv.yst` 再打开（或重启电视）让 Fresco 重建索引。
脚本打印的统计是**输入侧**计数：`downgraded` + `to_png` 应等于 `webp-VP8X` 的数量（本机 154 + 114 = 268）。
把改好的缓存重新 pull 一次再跑脚本，`webp-VP8X` 应该为 0。

还原：`bash refresh_yst_cache.sh --restore`。

> 新下载的 VP8X 图标仍可能显示不出来，这是这个「手动补丁」的固有局限；复发时重跑一次脚本即可。
