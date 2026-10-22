# lowpoly-mug — 低多边形陶瓷马克杯（实测样例）

> 本目录是 blender-modeling 技能的**完整实测样例 / few-shot 参考**：一句话需求 → brief → `model.py` → 三视角渲染 → 导出 `.blend`/`.glb`。
> 模型完全由同目录 `model.py` 生成，可用文末「复现命令」原样重跑。

## 需求原句

「做一个低多边形马克杯，白色陶瓷杯身，带蓝色把手和底圈，要能看清杯口内腔。」

## 一句话目标

一个真实尺度（约 0.10 m 高）、总三角面 < 3000 的低多边形陶瓷马克杯：白色杯身 + 蓝色杯柄/底圈，杯口敞开、iso 视角能看见内腔，单物件、origin 在杯底中心。

## 风格与量化参数

| 风格词 | 量化结果 |
| --- | --- |
| 低多边形 | 圆柱圆周 24 段；倒角 2 段；总三角面 1816（< 3000 目标） |
| 陶瓷 | `roughness=0.38`、`metallic=0`、albedo 0.86（AgX 下呈柔和高光，不整片过曝） |
| 蓝色点缀 | 杯柄 + 底圈用 sRGB (0.16, 0.40, 0.70) 的强调材质 |
| 能看清内腔 | 杯身用**布尔挖腔**（真实杯壁 6 mm + 杯底 8 mm），并在 iso 视角（俯角约 29°）检查内壁 |
| 产品图质感 | 三点布光 + 深灰地台（albedo 0.07），白杯与背景分离；地台 z=0 承接投影 |

## 尺寸（米）

| 项 | 数值 | 依据 |
| --- | --- | --- |
| 总高 | 0.099 m | 底圈 0.008 m + 杯身 0.091 m |
| 杯身外半径 | 0.045 m | 常见 250 mL 马克杯 |
| 杯壁厚 | 0.006 m | 布尔内腔半径 = 0.045 - 0.006 = 0.039 m |
| 杯底厚 | 0.008 m | 内腔底 z = 0.016 m |
| 底圈半径 / 高 | 0.043 m / 0.008 m | 比杯身小 2 mm，形成台阶 |
| 杯柄环半径 / 管半径 | 0.027 m / 0.0055 m | 竖直圆环，装在 +X 侧杯壁，中心高 0.058 m |
| 总宽（建模坐标系，含杯柄） | 0.125 m | x: -0.045 ~ 0.080 |
| 总深（建模坐标系） | 0.090 m | y: -0.045 ~ 0.045 |
| 轴对齐包围盒（`report.json.dimensions`） | 0.154 × 0.145 × 0.099 m | 整体绕 Z 旋转 -35° 展示，轴对齐包围盒随之变大；高度不受影响 |

## 颜色与材质

| 材质名 | 颜色（0-1 RGB） | roughness | metallic | 用途 |
| --- | --- | --- | --- | --- |
| `mug_ceramic` | (0.86, 0.86, 0.84) | 0.38 | 0.0 | 杯身、杯腔内壁 |
| `mug_accent` | (0.16, 0.40, 0.70) | 0.30 | 0.0 | 杯柄、底圈 |
| `FloorMat` | (0.07, 0.075, 0.085) | 0.55 | 0.0 | 地台（深灰产品背景） |

> 每个部件**建件时就带材质**，最后 `join` 合并；`join` 保留材质槽，合并后不要再 `assign`（只会覆盖槽 0）。
> 布尔 cutter 也必须带同一个陶瓷材质，否则布尔新生成的内腔面会拿到非法材质索引（实测会渲染成串色/花屏）。

## 结构四层

| 层 | 结论 |
| --- | --- |
| 主体层 | 杯身 P01：圆柱（24 边）+ 布尔挖腔 + 杯口倒角 → 开口杯 |
| 附件层 | 杯柄 P04：竖直圆环（torus），装在 +X 侧 |
| 细节层 | 底圈 P03：薄圆柱（强调色）；杯口 1.2 mm 倒角一圈高光 |
| 场景层 | 深灰地台 `setup_floor` + 三点布光 + 相机（`setup_scene` 生成，`render_views` 自动取景） |

## 部件表

| 编号 | 部件 | 层 | 图元/构造 | 尺寸(m) | 位置/旋转(m,°) | 材质 | 修改器 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | `mug_body` | 主体 | `cylinder` | r=0.045, h=0.091 | (0,0,0.0535) | `mug_ceramic` | `add_boolean`（挖腔）+ `add_bevel` 0.0012；`apply_modifiers` 后 join | P02 |
| P02 | `mug_cavity` | 细节（工具） | `cylinder`（布尔 cutter） | r=0.039, h=0.120 | (0,0,0.076) | `mug_ceramic` | 被 P01 布尔吃掉后删除 | P01 |
| P03 | `mug_foot` | 细节 | `cylinder` | r=0.043, h=0.008 | (0,0,0.004) | `mug_accent` | join → `mug` | — |
| P04 | `mug_handle` | 附件 | `torus` | R=0.027, r=0.0055 | (0.047,0,0.058) rot=(90,0,0) | `mug_accent` | join → `mug` | — |

合并：`join([P01, P03, P04], "mug")` → 整体 `rotate(z=-35°)` → `set_origin(mug, "BOTTOM")`，origin 落在杯底中心。

## 假设与默认决策

1. **尺寸**：需求没给尺寸，按真实马克杯取「高 0.099 m、半径 0.045 m、容量约 300 mL」；数值全部集中在 `PARAMS`。
2. **材质**：需求只说「白色陶瓷 + 蓝色把手」，因此杯身用低粗糙度瓷白、杯柄与底圈共用同一个强调色，避免多色杂乱。
3. **杯腔用布尔而不是开口圆柱**：布尔能做出真实 6 mm 杯壁与 8 mm 杯底的厚度感；低多边形下 24 边圆柱足够，且内腔在 iso 视角清晰可见。
4. **整体绕 Z 旋转 -35°**：`render_views` 的 front/right 相机分别位于 +Y / +X，杯柄若严格朝 +X 会在 right 视角变成一条竖线；旋转后三个视角都能看到圆环轮廓。
5. **自建深灰地台**：`setup_scene` 默认地台 albedo 0.35，白杯会糊进背景（首轮实测过曝、分离度差）；改为 `floor=False` + `setup_floor(0.07)` 后主体轮廓清晰。
6. **样例保留二进制导出**：`--stage full` 生成 `exports/model.blend`（约 0.56 MB）与 `model.glb`（约 0.12 MB），随样例一起提交，可直接用 Blender 打开 / 导入引擎；`logs/` 不提交，重跑 `--stage full` 即重新生成。
7. **不建勺子/杯垫/托盘等道具**：保持单物件，便于直接复用与摆放。

## 环境

- Blender 4.0.2（headless `blender -b`，Cycles）、Python 3.12；kit 1.0.0（本样例产物生成时版本；当前仓库 kit 1.1.0，重跑 `--stage full` 会更新 `report.json` 里的版本号）。
- `python -X utf8 -B scripts/doctor.py` → 0 ERROR；平台 Windows x64。
- 渲染只依赖 Blender 自带 Cycles；`contact_sheet.py` 才需要可选 Pillow。

## 验收标准

- [x] `--stage build` / `--stage render` / `--stage full` 均退出码 0、`BM_RESULT.ok=true`、`errors=[]`
- [x] `renders/view-front.png`、`view-right.png`、`view-iso.png` 各 1 张 512×512，单张 > 15 KB、`std > 4`、`black_ratio < 0.98`（本样例实测 std 22-67）
- [x] `report.json` 三轴尺寸为正、有相机与灯光、`mesh_count ≥ 1`、`total_tris < 3000`
- [x] 杯腔为白色陶瓷（无串色）、杯柄与杯身相接无可见穿模、杯底与地台贴合（`bbox_min[2] = 0`）
- [x] `model.py` 无绝对路径（grep `[A-Za-z]:\\` 命中 0）、只 import `blender_kit` 的公开函数、参数全部集中在 `PARAMS`
- [x] 三张渲染图均用 `read_image` 真看过（见迭代记录）
- [x] `python scripts/check_output.py --out "<本目录>"` → 27 PASS / 0 ERROR / 0 WARN（含 `exports/` 两个导出文件校验；本机 py3.12 + Pillow 实测）

## 迭代记录

| 轮次 | 问题（证据） | 改了什么（PARAMS/函数） | 重跑结果 |
| --- | --- | --- | --- |
| 1 | 首轮预览：白杯局部轻微过曝、灰地台与白杯分离度低；right 视角杯柄只剩一条竖线 | 先改展示：`handle.yaw_deg=-20`，`scene.floor=False` + 自建地台 `setup_floor(color=(0.20,0.21,0.23))` | 分离度变好；right 视角仍是近似竖线，iso 内腔发蓝 |
| 2 | iso 内腔呈蓝色、材质串色（数据证据：`mug.data.polygons` 出现材质索引 414629464，来自无材质的布尔 cutter） | `mug_cavity` 加 `material=mug_ceramic`（布尔新面归入槽 0） | 内腔恢复白色陶瓷，材质索引只剩 0/1；right/iso 杯柄轮廓均可辨 |
| 3 | 地台仍偏亮（iso mean=212、std=10 说明主体与背景对比弱）；right 视角杯柄圆环仍偏侧 | `floor.color 0.20→0.07`、`ceramic 0.93→0.86`、`handle.yaw_deg -20→-35` | 三视角 mean 153-178、std 23-61；白杯与深灰背景分离，杯柄三视角均可见 |

## 复现命令

在 `<技能目录>`（即含 `SKILL.md` 的目录）下执行；`<本目录>` 指本文件所在目录：

```powershell
python scripts\run_blender.py --script "<本目录>\model.py" --out "<本目录>" --stage build
python scripts\run_blender.py --script "<本目录>\model.py" --out "<本目录>" --stage render
python scripts\run_blender.py --script "<本目录>\model.py" --out "<本目录>" --stage full --timeout 900
python scripts\check_output.py --out "<本目录>"
```

`--stage full` 会在 `<本目录>` 下生成 `exports/model.blend`、`exports/model.glb`、`logs/*.log` 与 `report.json`；本样例仓库保留 `brief.md`、`model.py`、`README.md`、`renders/`（3 张 512 px）、`exports/`（blend + glb）与 `report.json`，`logs/` 不提交。
