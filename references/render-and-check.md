# 渲染、构图与看图自检

> 本文件是 `AGENTS.md` 第 8-10 节与第 14 节的展开说明，用于**阶段 5（预览渲染）、阶段 6（迭代）、阶段 7（终渲）**。
> 只写本机实测过的参数与判据；命令用法与 `AGENTS.md` 第 8/10/17 节完全一致（脚本均为 `<技能目录>\scripts\xxx.py`）。
> 环境：Windows + Blender 4.0.2 + system Python；kit 内渲染函数来自 `lib/blender_kit.py` 公开 API（`setup_render` / `render_still` / `render_views` / `render_turntable`）。

## 1. 渲染档位与实测基线

| 档位 | 用途 | engine | 分辨率 | 采样 | denoise | 实测耗时（本机） |
| --- | --- | --- | --- | --- | --- | --- |
| 极速验错 | build 后看轮廓 | WORKBENCH | 512×512 | — | 无 | 约 0.7 s/张 |
| 预览 | 每轮迭代看图 | CYCLES CPU | 512×512 | 16 | 开 | 约 0.9-1.0 s/张（三张 3-5 s） |
| 终渲 | 交付图 | CYCLES CPU | 960×960 | 48 | 开 | 约 4.5 s/张（三张约 14 s） |
| 备选 | 快速实色 + 环境反射 | EEVEE（`BLENDER_EEVEE`） | 512×512 | — | 无 | 约 0.5 s/张（进程内首次 0.8 s） |

**实测数据（本机，球 + 立方体 + 两盏 AREA 灯 + 灰色 world 场景）**

- CYCLES CPU 512×512 / 16 samples / denoise：0.94 s；同分辨率关 denoise：0.33 s。
- CYCLES CPU 960×960 / 48 samples / denoise：4.47 s（输出约 805 KB）。
- WORKBENCH 512×512：0.74 s；EEVEE 512×512：0.47 s（全新进程内首次 0.79 s）。
- 256×256 / 8 samples 的冒烟渲染：0.16-0.40 s，约 41 KB。
- 正常三视角 CYCLES 预览 PNG 每张 200-300 KB；**空图/全黑图只有约 9 KB**，所以 `check_output.py` 的 `> 15 KB` 能挡住绝大多数空图。

**档位铁律**：预览一律 512/16 且必须开 denoise（否则 std 偏低、误判全黑）；终渲一律 ≥ 960/48。不得为了提高"好看程度"在预览阶段堆到 960/128——单张 10 s 以上会让 4 轮迭代失控。

## 2. 参数推荐（写进 `model.py` 的 `PARAMS`）

```python
PARAMS["render"] = {
    "preview": (512, 16),   # (分辨率, 采样)
    "final": (960, 48),
}
# 调用侧（与 templates/model_template.py 同一写法）：
# w, s = PARAMS["render"]["preview"]
# render_views(RENDERS_DIR, prefix="view", engine="CYCLES", samples=s, resolution=(w, w))
```

| 参数 | 推荐值 | 说明 |
| --- | --- | --- |
| engine | `CYCLES`（预览与终渲）/ `WORKBENCH`（只验轮廓）/ `EEVEE`（备选） | 传错值 kit 会回退 CYCLES 并给 WARN |
| samples | 预览 16，终渲 48（快速验错可 8） | 512×512/16 已可判断几何与材质 |
| resolution | 预览 512，终渲 960（用户要求 4K 才上 1920） | 截图类需求用正方形 960×960 |
| denoise | 预览/终渲都开 | 4.0.2 默认 `OPENIMAGEDENOISE` |
| film_exposure | 1.0 | 偏暗再上调，每次 ±0.2，别一次翻倍 |
| color_look | `"AgX - Medium High Contrast"` | 4.0.2 默认 AgX；可直接赋值，版本不认时 kit 回退不报错 |
| transparent | 默认 False | 需要透明背景交付时 True（PNG 带 alpha） |

**为什么用 CYCLES CPU**：本机 GPU（OPTIX）首次渲染 3.9 s、比 CPU 慢一个数量级（含初始化），批量小图 CPU 更稳；只有终渲大幅提分辨率（1920+）或场景重时才考虑 GPU。

## 3. 相机与构图

### 3.1 三视角定义（kit 内置方向，从 target 指向相机的单位向量）

| 视角 | 方向 | 看到什么 | 用途 |
| --- | --- | --- | --- |
| `front` | (0, 1, 0.22) | 正面（+Y 侧），略微俯视 | 判断正面特征、左右对称性 |
| `right` | (1, 0, 0.22) | 物体右侧面（+X 侧） | 判断厚度、侧面附件 |
| `iso` | (1, 1, 0.8) | 45° 斜上方 | 判断体积感、部件前后关系（首看这张） |

方向是"从目标指向相机"：`front` 相机在 **+Y** 侧看向原点，所以**正面特征必须朝 +Y**（否则 front 图拍到的是背面）。`+X` 是物体右侧，在 front 图里显示在画面左侧（镜像视角，别用"画面左右"描述朝向，只用 ±X/±Y）。

kit 另支持 `left`、`back`；每轮预览固定出 front/right/iso 三张，转台与特写按需加。

### 3.2 相机设置手法

```python
# 方式 A：一条命令配齐相机 + 三灯 + 地台（推荐，快）
scene = setup_scene(target=(0, 0, 0.5), distance=4.0, lens=50)
# 方式 B：手动摆相机（特写/非标视角）
cam = add_camera(location=(2.5, -2.5, 1.6), target=(0, 0, 0.5), lens=50)
look_at(cam, (0, 0, 0.5))          # 对准目标
fit_camera(cam, [obj], margin=1.2)  # 按包围盒自动收进画面
```

| 参数 | 推荐 | 说明 |
| --- | --- | --- |
| lens | 50 mm（产品/单体）；35 mm（场景/室内） | 长焦压缩变形小，适合"产品图" |
| distance | 小物件 3.0、家具 6.0、整场景 10-15（或按场景最大尺寸 × 2-3） | **只影响布光半径与地台尺寸**，不影响三视角取景（见下） |
| margin（fit_camera） | 1.2-1.5 | 小于 1.1 容易出画；大于 2 主体太小；仅手动相机时需要 |
| 相机高度 | 约在主体中部偏上（z = target.z + 0.1~0.3×高度） | 纯平视显得呆板，略俯视更立体 |

**三视角构图由 kit 自动完成**：`render_views` 内部会按"除地台外的全部几何对象"的 bbox 居中相机并用 `fit_camera(margin=1.15)` 取景（拍完恢复原相机），所以 `setup_scene(distance=...)` 给多大都不会让主体变小/出画。只有**手动 `add_camera` + `render_still`** 的特写才需要自己算距离并调 `fit_camera`。

**实测占画面比例**（`film_transparent` + alpha bbox 量 examples 真样例）：`fit_camera` 对 bbox 的 8 个角点逐个投影、取能容纳全部角点的最近距离，后排角点主导，所以主体实际占比小于 1/1.15 且**随 bbox 形状变化**——低多边形马克杯（0.154×0.145×0.099 m）实测约 **47%-49%**，办公椅（0.625×0.638×0.952 m）约 **70%-77%**。`render_views` 不接受 margin 参数，改不了这个比例；想让主体更大，只能换手动相机 + `fit_camera(margin=1.0~1.1)`。

**注意**：自动取景只排除 `setup_floor` 建的地台（它带 `kit_role="floor"` 标记）。用 `plane()` 自建的地台、散落的辅助道具、隐藏对象都会被算进 bbox，导致主体在画面里变小——这是"主体偏小"最常见的原因。

### 3.3 构图量化判据（看图时量）

1. 主体完整在画面内，四边留白 ≥ 画面 5%（贴边即"出画"）。
2. 主体占画面**高度**约 45%-80% 属正常（实测：扁平物件 ≈ 47%-49%、高瘦物件 ≈ 70%-77%）；< 30% 说明有离群对象/自建地台撑大 bbox，> 85% 有出画风险。
3. 主体重心大致居中，不偏单角；地台与背景交界线不切过主体关键特征。
4. 三张图必须看到不同信息面：front 看正面对称、right 看厚度、iso 看体积与前后层次。
5. 特写图只放一个局部（如杯柄、机器人眼睛），不要和全景混用同一张。

## 4. 灯光与材质表现

### 4.1 默认三灯（`setup_studio_lights`）

| 灯 | 默认能量 | 作用 | 调整经验 |
| --- | --- | --- | --- |
| key 主光 | 500 W | 定明暗关系 | 以 `setup_scene` 的 distance 为参照：distance 翻倍，能量约 ×4（客厅尺度家具 800-1200） |
| fill 补光 | 150 W | 压暗部 | 暗部全黑时 +50%-100% |
| rim 轮廓光 | 300 W | 勾边、分离背景 | 剪影糊在一起时 +30% |

世界光 `setup_world(color=(0.05,0.05,0.06), strength=0.6)` 提供环境亮度；地台 `setup_floor(size=20, color=(0.35,0.35,0.38), roughness=0.8)` 出接触阴影。

### 4.2 材质与灯光的配合

- **金属件（metallic ≥ 0.8）**：必须有环境亮度或大面积光源，否则渲成黑块。先把 `strength` 提到 1.0-2.0 或加一块白色平面当反光板。
- **发光件（emission）**：`emission_strength` 取 2-8；1.0 在 AgX 下几乎看不出；过高会整片过曝（看 `mean > 235` 判定）。
- **过曝/欠曝**：看 `report.json.renders[].mean`——正常 20-235；< 15 偏暗、> 235 偏亮。优先调灯光能量与 `film_exposure`，别改材质颜色掩盖。
- **颜色发灰**：AgX 会降饱和，这是正常的；用户要"鲜艳"时把饱和度再提高 10-20%，不要关 AgX（关掉会高光死白）。

## 5. 背景与地台

| 需求 | 做法 |
| --- | --- |
| 默认灰底产品图 | `setup_world` 默认深灰 + `setup_floor` 中灰地台 |
| 干净纯色底 | 调 `setup_world(color=(0.8,0.8,0.85), strength=1.0)`，关 floor 或把 floor 调成同色 |
| 透明背景（用于合成） | `setup_render(transparent=True)`，PNG 带 alpha；`check_output.py` 仍按 RGB 亮度统计 |
| 场景地面（草地/木地） | `setup_floor` 改颜色 + 粗糙度，不额外建模地面（省面数） |
| 多物体场景 | 相机 `distance` 按场景总宽放大，主体 target 取场景重心 |

**判据**：背景均匀、无脏噪点带或异常亮斑；地台与背景交界干净；透明背景交付时必须确认 alpha 通道正常（用看图工具看是否"棋盘格"）。

## 6. 全黑 / 异常图诊断（实测签名）

| 图像表现 | 实测统计（128-512px） | 原因 | 解决 |
| --- | --- | --- | --- |
| 纯黑（全黑图） | mean≈0.4 / std≈0.49 / black_ratio=1.0 / ~9 KB | 无灯且 world strength=0；或相机在物体内部 | 加灯 / 提 world / 移动相机；见 `troubleshooting.md` T-8 |
| 很暗但非全黑 | mean≈15 / std≈52 / black_ratio≈0.92 | 有灯但无 world（kit `reset_scene()` 后 world 可能为 None） | 补 `setup_world` 或 `setup_scene`（内含天地光） |
| 正常 | mean 40-200 / std 20-120 / black_ratio ≈ 0 | — | — |
| 只有剪影、材质全黑 | 轮廓可见、内部全黑 | 材质未 `assign`、金属件无环境反射 | `assign` 材质；补环境光 |
| 纯色灰度图 | std < 4.0 | 相机对着空白背景 / 物体在画面外 | `fit_camera`；检查 `target` 与 `distance` |
| 渲染抛错 | 无图 | `scene.camera` 为 None：裸 `bpy.ops.render.render` 抛 `RuntimeError: Error: Cannot render, no camera`；kit 的 `render_still`/`render_views` 会自动补相机并给 WARN | 用 `add_camera`/`setup_scene` 显式建相机 |

**注意**：4.0.2 的 Cycles 是双面光照，法线翻转**不会**直接渲成黑面（实测翻转法线前后统计完全一致）；看到"黑面"优先怀疑无灯、材质缺失、面重叠遮挡，而不是法线。

## 7. 量化看图自检清单（每轮渲染后逐项过）

用 `read_image` 打开每张 `renders/view-*.png`（三张都必须看），数值证据同时看 `report.json.renders[]`：

| # | 检查项 | 通过判据 | 不通过动作 |
| --- | --- | --- | --- |
| 1 | 是否全黑/空图 | `std > 4.0` 且 `black_ratio < 0.98`；肉眼能明确辨认主体 | 查灯/相机/world |
| 2 | 构图 | 四边留白 ≥ 5%；主体占高约 45%-80%（实测：扁平物件 ≈ 47%-49%、高瘦物件 ≈ 70%-77%）；居中 | 三视角自动取景；异常先查离群对象/自建地台是否被算进 bbox；手动相机才用 `fit_camera(margin=1.2~1.5)` |
| 3 | 轮廓 | 只看剪影能认出物件；最大外廓宽高比与 brief 误差 ≤ 10% | 修主体比例 |
| 4 | 比例 | 关键相对尺寸符合 brief 尺寸表（如杯柄 ≈ 杯高 1/2）；总高误差 ≤ 10% | 改 `PARAMS` |
| 5 | 部件完整性 | 部件表每行都能在图中定位；缺件数 = 0 | 补建缺失部件 |
| 6 | 颜色/材质 | 主色与 brief 色板一致；mean 在 20-235；金属/粗糙度可区分 | 调材质/RGB/灯光 |
| 7 | 穿插 | 相接部件无可见穿模；设计性嵌合需 brief 注明 | 改位置/尺寸 |
| 8 | 悬浮 | 着地件最低点离地 ≤ 0.005 m；悬空件有支撑逻辑 | 下移/加支撑 |
| 9 | 黑面/法线 | 无纯黑补丁、无明暗断裂；暗部能辨认形状 | 查灯/材质/遮挡 |
| 10 | 背景/地台 | 背景均匀、交界干净；透明图 alpha 正常 | 调 world/floor/transparent |
| 11 | 锯齿/噪点 | 预览可轻微锯齿；终渲边缘平滑、无肉眼噪点 | 升分辨率/采样，开 denoise |
| 12 | 文字/细节 | 文字完整可读（中文必须加载字体）；细节比例不失衡 | 修字体/细节尺寸 |

**记录要求**：每轮在 `brief.md` 的"迭代记录"表写：轮次、问题（哪张图 + 具体现象）、改了什么（PARAMS 字段）、重跑结果。没证据的改动不算迭代。

## 8. 迭代策略

### 8.1 修改顺序（硬性）

1. **先大形**：整体比例、主体尺寸、构图（`setup_scene` / `PARAMS` 尺寸）。
2. **再几何**：部件完整性、位置/穿插/悬浮、倒角与分段。
3. **再材质**：颜色、粗糙度、金属度、发光。
4. **最后灯光与导出**：灯光能量、背景、`film_exposure`；导出参数一般不动。

**每轮只改 1-2 类问题**。一轮改 5 处会让"改好了没有"无法归因，也容易引入新错。

### 8.2 轮次与时间预算

| 轮次 | 目标 | 单轮允许时间 |
| --- | --- | --- |
| 1 | 修全黑/出画/缺主体等致命问题 | ≤ 5 min |
| 2 | 修比例、部件穿插/悬浮 | ≤ 5 min |
| 3 | 修材质颜色、倒角/平滑 | ≤ 5 min |
| 4 | 打磨细节与灯光；仍不达标就停 | ≤ 5 min |

第 4 轮后停止迭代，交付当前最佳结果并在交付说明写"遗留问题 + 下一步改法"。不要为"更完美"无限循环。

### 8.3 快速定位技巧

- 改完先跑 `--stage build`（秒级）确认脚本没崩，再跑 `--stage render` 看图，别直接 full。
- 只想看轮廓时把 `render_views` 的 `engine` 参数临时改成 `"WORKBENCH"`，0.7 s/张（改完记得改回 `"CYCLES"`）。
- 单张异常：用 `render_still(os.path.join(RENDERS_DIR, "debug.png"), camera=cam)` 只渲一张，比三张快。
- 渲染慢到超过 60 s：先查分辨率/采样是否被改大、物体数是否暴增（`report.json` 的 `object_count`/`total_tris`）。

## 9. 三视角 / 特写 / 转台 / 接触表

| 需求 | 调用 | 说明 |
| --- | --- | --- |
| 三视角预览/终渲 | `render_views(RENDERS_DIR, prefix="view", engine="CYCLES", samples=16, resolution=(512,512))` | prefix 用 `view`（预览）/`final`（终渲）；自动按 bbox 取景并恢复原相机 |
| 单张特写 | `add_camera(location=..., target=...)` + `render_still(path, camera=cam)` | 特写不替代三视角，只补充 |
| 转台 | `render_turntable(RENDERS_DIR, prefix="turn", count=6, elevation=20.0)` | 6-8 张；可选传 `margin`（默认 1.15）调留白；交付可选 |
| 一张总览 | `python scripts/contact_sheet.py --out "<输出目录>"` | 生成 `renders/contact-sheet.png`；无 Pillow 时 WARN 退出 0 |

**命令（与 `AGENTS.md` 阶段 8 一致）**

```powershell
cd "F:\DeepSeek Harness\blender-modeling"
$OUT = "<工作区>\blender-models\<slug>"
# 预览三视角（约 3-5 秒）
python scripts/run_blender.py --script "$OUT\model.py" --out "$OUT" --stage render --label preview
# 终渲 + 导出（约 15-30 秒）
python scripts/run_blender.py --script "$OUT\model.py" --out "$OUT" --stage full --label final --timeout 900
# 拼总览图 + 闸门
python scripts/contact_sheet.py --out "$OUT"
python scripts/check_output.py --out "$OUT" --min-views 4
```

## 10. 常见渲染问题对照表

| 现象 | 最可能原因 | 动作 |
| --- | --- | --- |
| 三张图全黑 | 无灯/无 world；相机在物体内 | 用 `setup_scene` 重配；查相机位置 |
| 主体太小 | 有离群对象/自建地台被算进取景 bbox（`render_views` 只排除 `setup_floor` 地台）；或手动相机 distance 太大 | 地台改用 `setup_floor`；移走或 `join` 离群件；手动相机用 `fit_camera(cam, objects, margin=1.2)` |
| 主体出画 | 手动相机未取景（三视角自动取景不会出画） | `fit_camera(cam, objects, margin=1.2)` |
| 部件悬空 | 位置 z 按错误基准算 | 用 `set_origin(group, "BOTTOM")` 后按地面 z=0 摆 |
| 部件穿插 | 尺寸相加没算重叠 | 留 0.01 m 嵌合余量，或上移附件 |
| 暗部死黑 | fill 太弱 / 无 world | fill +50%-100%，world strength ↑ |
| 高光过曝 | key 太强 / emission 太亮 | key −20%；emission_strength ≤ 8 |
| 背景脏点 | floor 与 world 对比过强 / 噪点 | 提采样、开 denoise；floor 改浅灰 |
| 地台与物体"焊接" | 无接触阴影 | 加 rim/key 角度；物体与地台留微缝 |
| 终渲边缘锯齿 | 分辨率不足/无 denoise | 960 + denoise；必要时 1920 |
| 渲染超时 | 分辨率/采样/物体数过大 | 降档；拆 `--stage build` 与 `--stage render` |
| 金属件全黑 | 无环境反射 | 提 world strength；加反光板；降 metallic 到 0.6 |
