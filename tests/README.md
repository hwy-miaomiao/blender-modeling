# tests —— 回归测试

这里有两类测试，**只有第一类跑在 CI 里**（CI 不安装 Blender）：

| 文件 | 需要 Blender？ | 跑法 |
| --- | --- | --- |
| `test_cli_contract.py` | ❌ 只要 Python 3.9+ | `python -m unittest discover -s tests -v` |
| `test_bl_common.py` | ❌ 只要 Python 3.9+ | 同上（`discover` 会一起跑） |
| `test_contact_sheet.py` | ❌ 只要 Python 3.9+（有 Pillow 才跑联系表用例） | 同上 |
| `test_ci_check.py` | ❌ 只要 Python 3.9+ | 同上 |
| `kit_smoke.blender.py` | ✅ 需要 Blender 4.x | 见下 |
| `kit_regression.blender.py` | ✅ 需要 Blender 4.x | 见下（审计回归，改 kit 后必跑） |

## 1. CLI / 健壮性测试（CI 跑）

```bash
python -m unittest discover -s tests -v
```

覆盖：

- `scripts/check_output.py`：`--selftest` 全过、目录不存在/空目录要报 ERROR 并 exit 1、`--min-views 0` 被拒绝、`--json` 输出可解析的纯 JSON、`--help` 正常；
- `scripts/ci_check.py`：当前仓库必须 `0 ERROR`；脏 `report.json`（顶层数组、字符串统计、bool 冒充数字、正斜杠绝对路径）只报 ERROR 不崩溃；
- `scripts/run_blender.py`：脚本不存在时报错 exit 1、`--help` 正常；
- `scripts/doctor.py`、`scripts/contact_sheet.py`：`--help` 正常；
- `scripts/bl_common.py`：`classify_log` 能过滤 `TBBmalloc` 噪音、识别 Traceback/RuntimeError、警告去重、错误数量封顶；`find_blender` 只返回真实存在的文件；
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
