# office-chair — 办公转椅（低多边形实例）

> 本文件是 `examples/office-chair/` 的建模简报，演示 AGENTS.md 阶段 1-2 的写法：
> 需求 → 量化尺寸 → 四层拆解 → 9 列部件表 → 假设 → 验收 → 迭代记录。
> 配套脚本：同目录 `model.py`；三张实测渲染图在 `renders/`。

## 需求原句

> 「帮我做个低多边形办公转椅，深色网布坐垫和靠背，金属五星脚架带轮子，能看清扶手和升降杆。」

## 一句话目标

一把 **0.95 m 高的低多边形办公转椅**：深色织物坐垫/靠背 + 中灰金属五星底座与扶手，带 5 个脚轮、升降杆和防尘罩，总共 1100 三角面。

## 风格与量化参数

| 风格词 | 量化落点 | 在 `model.py` 里的位置 |
| --- | --- | --- |
| 低多边形 | 总三角面 < 3000（实测 1100）；圆柱 16 边、脚轮 12 边 | 各 `*_vertices` |
| 深色网布 | 接近黑的蓝灰 `(0.050, 0.055, 0.065)`，粗糙度 0.82 | `PARAMS["colors"]["fabric"]` |
| 金属架构 | 中灰 `(0.280, 0.290, 0.310)`，金属度 0.70、粗糙度 0.35 | `PARAMS["colors"]["frame"]` |
| 圆角/软包 | 座垫倒角 0.025 m/3 段；靠背 0.028 m/3 段；扶手垫 0.012 m/2 段 | `bevel` / `bevel_segments` |
| 写实比例 | 按真实人体工学椅：座高 0.445 m、座深 0.48 m、靠背高 0.50 m | `PARAMS["seat"]` / `["back"]` |

## 尺寸（米）

| 部位 | 数值 | 说明 |
| --- | --- | --- |
| 整椅总高 | 0.952 | 脚轮底面 z=0 → 靠背上沿；`report.json` 实测 |
| 整椅包围盒（X×Y） | 0.625 × 0.638 | 五星底座 + 脚轮外沿决定，比座面宽 |
| 座面 | 0.500（宽）× 0.480（深）× 0.090（厚） | 座面上表面 z = 0.445 |
| 靠背 | 0.460（宽）× 0.500（高）× 0.070（厚） | 底部 z ≈ 0.446，顶部后仰 8° |
| 靠背倾角 | 8° | 绕 X 轴，顶部向 **-Y** |
| 扶手高度 | 0.633（垫上表面） | 扶手垫 0.075×0.260×0.035，位于 x = ±0.255 |
| 五爪底座半径 | 0.300 | 5 条腿每 72°，腿截面 0.300×0.050×0.035 |
| 脚轮 | 半径 0.032、宽 0.022 | 轮底与地台 z=0 相切 |
| 升降杆 | 半径 0.028、长 0.300 | 中心 z = 0.270，跨 0.12 → 0.42 |
| 防尘罩 | 锥体 r1=0.060 → r2=0.038、高 0.120 | 中心 z = 0.180 |

> 注：`report.json` 的 `dimensions` 是**轴对齐包围盒**，含五星脚与脚轮外沿（0.625 × 0.638），比“座面宽 0.50 / 扶手外沿 0.585”大是正常的；总高 0.952 与上表一致。

## 颜色与材质

| 材质名 | 用途 | Base Color (0-1) | 粗糙度 | 金属度 |
| --- | --- | --- | --- | --- |
| `chair_fabric` | 座垫、靠背 | (0.050, 0.055, 0.065) | 0.82 | 0.0 |
| `chair_frame` | 五星底座、升降杆、防尘罩、靠背支撑柱、扶手 | (0.280, 0.290, 0.310) | 0.35 | 0.70 |
| `chair_rubber` | 脚轮 | (0.020, 0.020, 0.022) | 0.85 | 0.0 |
| `FloorMat` | 地台（`setup_floor` 自动生成） | (0.070, 0.075, 0.085) | 0.55 | 0.0 |

> 配色依据：三点布光的 Key 灯能量高，深色 albedo 在 AgX 观感下会被抬成中灰（实测座面像素 ≈145，地台 ≈178）。因此织物给到 0.05 级别而不是 0.15，才能读出“深色网布”的意图；金属靠 metallic 反射而不是靠亮 base color 提亮。

## 结构四层

| 层 | 内容 | 数量 |
| --- | --- | --- |
| 主体层 | 五星底座、升降杆、座垫、靠背 | 4 组 |
| 附件层 | 两侧扶手（立柱+垫）、靠背支撑柱 | 3 组（随组 join） |
| 细节层 | 倒角圆角、防尘罩锥体、脚轮 | 若干（合并在组内） |
| 场景层 | 深灰地台 1 块（`setup_floor`） | 1 |

## 部件表

| 编号 | 部件 | 层 | 图元/构造 | 尺寸(m) | 位置/旋转(m,°) | 材质 | 修改器 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | chair_hub | 主体 | `cylinder` 16 边 | r=0.065 h=0.060 | (0,0,0.090) | chair_frame | — | — |
| P02 | chair_leg_00~04 | 主体 | `cube` ×5 | 0.300×0.050×0.035 | 半径 0.15 处、rotZ=72°×i | chair_frame | — | P01 |
| P03 | chair_caster_00~04 | 细节 | `cylinder` 12 边 | r=0.032 w=0.022 | 半径 0.30 处、z=0.032、rot=(90,0,72°×i) | chair_rubber | — | P02 |
| P04 | office-chair_base | 主体 | `join`(P01-P03) | 包围盒 0.625×0.638 | 原点 BOTTOM | 2 槽 | — | P01-P03 |
| P05 | chair_gas | 主体 | `cylinder` 16 边 | r=0.028 h=0.300 | (0,0,0.270) | chair_frame | — | P04 |
| P06 | chair_shroud | 附件 | `cone` 16 边 | r1=0.060 r2=0.038 h=0.120 | (0,0,0.180) | chair_frame | — | P05 |
| P07 | office-chair_lift | 主体 | `join`(P05-P06) | 高 0.30 | 原点 BOTTOM | chair_frame | — | P05-P06 |
| P08 | office-chair_seat | 主体 | `cube` | 0.500×0.480×0.090 | (0,0,0.400) | chair_fabric | `add_bevel` 0.025/3 | P07 |
| P09 | chair_backrest | 主体 | `cube` | 0.460×0.070×0.500 | (0,-0.210,0.700) rotX=8° | chair_fabric | `add_bevel` 0.028/3 | P08 |
| P10 | chair_back_post_l/r | 附件 | `cube` ×2 | 0.050×0.060×0.180 | (±0.130,-0.190,0.460) | chair_frame | — | P09 |
| P11 | office-chair_back | 主体 | `join`(P09-P10) | 宽 0.46 高 0.50 | 原点 BOTTOM | 2 槽 | — | P09-P10 |
| P12 | chair_arm_post_l/r | 附件 | `cube` ×2 | 0.045×0.050×0.200 | (±0.255,0.020,0.500) | chair_frame | — | P08 |
| P13 | chair_arm_pad_l/r | 附件 | `cube` ×2 | 0.075×0.260×0.035 | (±0.255,-0.010,0.615) | chair_frame | `add_bevel` 0.012/2 | P12 |
| P14 | office-chair_arms | 附件 | `join`(P12-P13) | 跨 0.585 | 原点 BOTTOM | chair_frame | — | P12-P13 |
| P15 | Floor | 场景 | `setup_floor` | 12×12 平面 | z=0 | FloorMat | — | — |

> 部件表每一行都对应 `model.py` 里的一次 kit 调用；`join` 合并的逻辑组在“依赖”列注明。

## 假设与默认决策

1. **不追问尺寸**：提示词没给规格，按真实人体工学椅取值（座高 0.445 m、靠背高 0.50 m、五星底座半径 0.30 m）。
2. **朝向**：`render_views` 的 front 相机在 **+Y**；本样例把「入座正面」朝 +Y（靠背在 -Y 侧），所以 `view-front.png` 看到的是椅子正面（坐垫前缘 + 靠背正面）。
   - 与 AGENTS.md §13「主体正面朝 +Y」一致；实测 kit 的 `_VIEW_DIRECTIONS["front"] = (0, 1, 0.22)`（相机在 +Y 侧看向原点），`view-front.png` 见到的就是椅子正面。
3. **深色配色**：验证发现三点布光会把深色 albedo 抬亮（AgX 提亮 + 强 Key），所以织物取 0.05 级深蓝黑、金属取中灰 + metallic 0.70，避免整椅发灰泛白。
4. **不建头枕/腰托/气压升降拉杆**：低多边形样例只保留轮廓必需件，细节层用倒角与防尘罩代替，控制在 1100 tris。
5. **地台自建**：`setup_scene(floor=False)` + `setup_floor(...)` 深灰地台，保证椅子（深色）与背景有对比；`render_views` 会自动排除 `kit_role="floor"` 的对象。
6. **只有 3 张 512 预览图**：示例仓库要控制体积，`--stage full` 不在 `examples/` 里产 960 终渲；真实交付按模板加 `final-*`。
7. **样例保留二进制导出**：`--stage full` 生成 `exports/model.blend`（约 0.56 MB）与 `model.glb`（约 0.08 MB），随样例一起提交，可直接用 Blender 打开 / 导入引擎；`logs/` 不提交，重跑 `--stage full` 即重新生成。

## 验收标准

- [x] `--stage build` 退出码 0、`errors: []`，objects=10 / meshes=5 / tris=1100 / dims≈(0.625, 0.638, 0.952)
- [x] `--stage render` 出 3 张 512×512 PNG，每张 > 15 KB，std > 4、black_ratio < 0.98，`read_image` 逐张看过
- [x] 轮廓可辨：五星底座、升降杆、座垫、靠背、两侧扶手、5 个脚轮
- [x] 无穿模、无悬浮：脚轮与地台相切，座垫压在升降杆上，靠背支撑柱连接座垫与靠背
- [x] `--stage full` 导出 blend + glb，`report.json` 合法且 dimensions 三轴为正
- [x] `model.py` 中 `[A-Za-z]:\\` 绝对路径命中 0；`brief.md` 尺寸表与 `report.json` dimensions 误差 ≤ 10%
- [x] `python scripts/check_output.py --out "<本目录>"` → 21 PASS / 0 ERROR / 0 WARN（含 `exports/` 两个导出文件校验）

## 迭代记录

| 轮次 | 问题（证据） | 改了什么（PARAMS/函数） | 重跑结果 |
| --- | --- | --- | --- |
| 1 | 首轮 build 通过；render 后看图：整椅泛白、织物/金属/橡胶几乎同色，读不出深色网布 | 织物 (0.15,0.16,0.19)→(0.050,0.055,0.065)；金属 (0.52,0.54,0.57)→(0.280,0.290,0.310)、metallic 0.70；橡胶 0.05→0.02 | 重渲：front mean 128/std 50、right 119/49、iso 144/32，材质三档可区分 |
| 2 | 材质调试脚本确认 slots/材质索引正确（base 2 槽 48+70、back 2 槽 98+12），泛白不是材质串色而是强光 + AgX | 不改材质分配，只改 `colors` 数值；记录像素证据（座面 145 vs 地台 178） | 椅子比地台暗、轮廓光完整 |
| 3 | 终检：脚轮与地台相切、靠背与座垫由支撑柱连接、扶手垫倒角可见；三视角完整 | 无代码改动（`apply_modifiers` 在 join 前，倒角未丢） | `--stage full` 通过，3 图 + report.json 输出 |

> 看图记录：`view-front.png`（正面：座垫/靠背/扶手对称、五星底座居中）、`view-right.png`（侧面：靠背 8° 后仰、升降杆与防尘罩层次）、`view-iso.png`（3/4 视角：整体轮廓与金属反光）。三张图均用 `read_image` 真看过。

## 复现命令

在 `<技能目录>`（`blender-modeling/`）下执行：

```powershell
# 1) 建模快检（不渲染不导出）
python scripts/run_blender.py --script "<技能目录>\examples\office-chair\model.py" --out "<技能目录>\examples\office-chair" --stage build

# 2) 三视角预览渲染
python scripts/run_blender.py --script "<技能目录>\examples\office-chair\model.py" --out "<技能目录>\examples\office-chair" --stage render

# 3) 导出 blend + glb 并写 report.json
python scripts/run_blender.py --script "<技能目录>\examples\office-chair\model.py" --out "<技能目录>\examples\office-chair" --stage full
```

说明：第 3 步会在本目录生成 `exports/model.blend`、`exports/model.glb` 与 `logs/*.log`；本样例仓库保留 `model.py`、`brief.md`、`README.md`、`renders/`、`exports/`（blend + glb）与 `report.json`，`logs/` 不提交。
