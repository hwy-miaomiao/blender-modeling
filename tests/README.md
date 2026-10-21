# tests —— 回归测试

这里有两类测试，**只有第一类跑在 CI 里**（CI 不安装 Blender）：

| 文件 | 需要 Blender？ | 跑法 |
| --- | --- | --- |
| `test_cli_contract.py` | ❌ 只要 Python 3.9+ | `python -m unittest discover -s tests -v` |
| `test_bl_common.py` | ❌ 只要 Python 3.9+ | 同上（`discover` 会一起跑） |
| `test_contact_sheet.py` | ❌ 只要 Python 3.9+（有 Pillow 才跑联系表用例） | 同上 |
| `test_ci_check.py` | ❌ 只要 Python 3.9+ | 同上 |
| `test_vision_metrics.py` | ❌ 只要 Python 3.9+（Pillow 用例自动跳过） | 同上 |
| `test_snapshot.py` | ❌ 只要 Python 3.9+ | 同上 |
| `test_safe_check.py` | ❌ 只要 Python 3.9+ | 同上 |
| `test_check_output_vision.py` | ❌ 只要 Python 3.9+（需 Pillow 生成真实 PNG；无 Pillow 时整类跳过） | 同上 |
| `kit_smoke.blender.py` | ✅ 需要 Blender 4.x | 见下 |
| `kit_regression.blender.py` | ✅ 需要 Blender 4.x | 见下（审计回归，改 kit 后必跑） |

## 1. CLI / 健壮性测试（CI 跑）

```bash
python -m unittest discover -s tests -v
```

覆盖：

- `scripts/check_output.py`：`--selftest` 全过、目录不存在/空目录要报 ERROR 并 exit 1、`--min-views 0` 被拒绝、`--json` 输出可解析的纯 JSON、`--help` 正常；视觉闸门对「全部渲染图无法解码」判 ERROR（VISION008）、「部分渲染图无法解码」判 ERROR（VISION009，列文件名/张数）、backfill 迁移只查引用、空迭代表报 ERROR；Pillow 可用时从 PNG 重算 `report.renders` 的 `mean/std/black_ratio` 并与记录对照（不一致 ERROR）；
- `scripts/ci_check.py`：当前仓库必须 `0 ERROR`；脏 `report.json`（顶层数组、字符串统计、bool 冒充数字、正斜杠绝对路径）只报 ERROR 不崩溃；
- `scripts/run_blender.py`：脚本不存在时报错 exit 1、`--help` 正常；`--no-vision` 会关闭 vision 回写；
- `scripts/doctor.py`、`scripts/contact_sheet.py`：`--help` 正常；
- `scripts/vision_metrics.py`：纯函数分割/量化指标/阈值闸门（VISION001~008）、坏 PNG（全部无法解码）报 VISION008 ERROR、部分坏图在模块层进 skipped（`check_output` 会把部分坏图升 VISION009 ERROR）、backfill 标记、`--write` 原子覆盖（`os.replace` 失败保留原文件）、`--selftest` 全过；
- `scripts/snapshot.py`：`history/vN` 快照与 `best.json` 基线、promote/rollback、`validate_best` 对坏版本只报 WARN；`--list --json` / `--json` 的 stdout 必须是可解析纯 JSON；`--selftest` 全过；
- `scripts/safe_check.py`：SAFE_MODE 静态审查正例 0 ERROR、subprocess/eval/绝对路径/`..`/变量路径（SAFE006 ERROR）/`Path.open`/盘符相对路径/`shutil` 拷贝/白名单 basename 绕过等反例必须命中对应 SAFE 码、`%TEMP%` 输出目录表达式放行、`--json` stdout 纯 JSON、`--selftest` 全过；
- `scripts/bl_common.py`：`classify_log` 能过滤 `TBBmalloc` 噪音、识别 Traceback/RuntimeError、警告去重、错误数量封顶；`find_blender` 只返回真实存在的文件；`execute(vision=True)` 在 full 成功后回写 `report.vision`（无 Pillow/无模块时降级为 warning，`--no-vision` 不调用）；
- 三个脚本模块在没有 Blender 的机器上可以正常 import。

## 2. kit 冒烟测试（手动，改了 kit/模板/导出后必跑）

在技能目录下（`<工作区>` 换成你的工作区路径）：

```bash
python scripts/run_blender.py \
  --script tests/kit_smoke.blender.py \
  --out "<工作区>/blender-models/_kit-smoke" \
  --stage build --timeout 180
```

它会在真实 Blender 里跑一遍全部图元、修改器、变换工具、渲染、6 种导出和
`open_blend` 回环，最后打印 `KIT SMOKE OK`。产物在 `_kit-smoke/` 下，可随时删除。

## 3. 审计回归（手动，改了 kit 后必跑）

```bash
python scripts/run_blender.py \
  --script tests/kit_regression.blender.py \
  --out "<工作区>/blender-models/_kit-regression" \
  --stage build --timeout 300
```

覆盖 v1.1.0 修复的全部问题：镜像 `bisect`、布尔 cutter 排除、隐藏对象不参与取景/统计、
按求值后网格统计面数、对象重名 `.001`、失效对象降级、渲染设置恢复、report 相对路径、
`setup_floor` 幂等、`open_blend` 损坏文件容错等。全部通过会打印 `KIT REGRESSION OK`。
