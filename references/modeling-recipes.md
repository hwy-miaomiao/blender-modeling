# 常见题材建模配方库

> 本文件是 `blender-modeling` 技能的**配方速查**：拿到一个题材，直接查这里，照骨架改参数就能出模型。
> 适用环境：Blender 4.0.2 headless，通过 `lib/blender_kit.py`（下称 **kit**）建模。所有代码只使用
> `lib/blender_kit.py` 的公开 API（逐个函数的用途与签名见该文件 docstring / `__all__`），不出现裸 `bpy` 调用，可以整块粘进 `model.py` 直接跑。
> 配套文档：完整流程看 `AGENTS.md`，看图自检看 `references/render-and-check.md`，
> 报错处理看 `references/troubleshooting.md`，kit 函数细节说不好时看 `references/bpy-cookbook.md`。

> ## ⚠ 坐标系约定（所有配方通用，2026-10 修订）
>
> - **+Y = 正面 / 前**，**Z = 上**，**+X = 物体右侧**。
> - kit 的 `front` 相机在 **+Y 侧**看向原点（`_VIEW_DIRECTIONS["front"] = (0, 1, 0.22)`），所以 `view-front.png` 里看到的就是**朝 +Y 的那一面**。
> - **+X 在 front 图里显示在画面左侧**（相机沿 −Y 方向看时是镜像视角）；**不要用"画面左右"描述朝向**，一律用世界坐标 X / Y / Z 说话。
> - 正面特征——车头、机头、门、窗、锁、屏幕、脸、脚尖——**一律建在 +Y 侧**；只有"车尾、后脑勺、床尾、背板"这类反面特征才在 −Y 侧。
> - 需要把某个正面特征换边：**把该部件的 y 坐标取相反数**（对称件不用动），并检查接触面/贴地没有被破坏；涉及旋转的部件（如机头圆锥）要同步改旋转方向。

## 0. 先看这里：通用规则与骨架

### 0.1 六条硬规则

1. **单位一律米**，按真实比例建模。椅面高 0.45、桌面 0.75、杯高 0.09、房门 2.0、汽车长 4.4——比例错比缺细节更致命。
2. **先大形后小件**：先摆主体（能决定轮廓的那个体块），再加附件，最后加细节。每加完一层就想想"这个部件在真实物体上是装在哪儿、和谁接触"。
3. **部件必须接触**：腿要插进座板、轮子要贴地、把手要插进杯身。宁可让部件互相嵌入 5~10mm，也不要留缝悬浮。
4. **origin 放底部中心**：收尾必须 `set_origin(obj, "BOTTOM")`，方便后续摆放与导出。
5. **统一 join**：同一物体（或同一材质组）最后 join 成一个对象，减少后续相机/导出麻烦；join 之前所有**修改器要先 `apply_modifiers`**（join 会丢掉非活动对象的修改器）。
6. **分段数服从风格**：低多边形（low-poly）圆柱/圆锥 8~16 段、球 8×6~16×10；写实感才用 32 段球/圆柱。`shade_flat` 出面块感，`shade_smooth(angle=30~40)` 出圆润感。kit 的 `torus` 分辨率固定，低模场景少用或接受它偏密。

### 0.2 通用骨架（每个 `model.py` 都长这样）

配方章节里的代码块都假设已经接在这段骨架的建模位置；完整脚本固定是 **build → render → export** 五段：

```python
# -*- coding: utf-8 -*-
"""<slug> 建模脚本：<一句话描述>。由 run_blender.py 在 Blender 4.0 内执行。"""
import os, sys

sys.path.insert(0, os.environ["BLENDER_KIT_DIR"])      # 执行器注入；禁止硬编码技能目录
from blender_kit import *                              # kit 公开 API（lib/blender_kit.py）

OUT = os.environ["BLENDER_OUT_DIR"]                    # run_blender.py 注入
STAGE = stage()                                        # "build" | "render" | "full"

# ---------- 1. 场景：世界 + 三灯 + 地台 + 相机 ----------
reset_scene()
cam = setup_scene(distance=4.0, azimuth=-45.0, elevation=25.0, lens=50)["camera"]

# ---------- 2. 建模：主体 → 附件 → 细节（粘贴第 2 节配方） ----------
# ... 这里产生最终对象 main ...

# ---------- 3. 构图：按最终 bbox 重新取景（避免模型出画） ----------
fit_camera(cam, [main], margin=1.2)

# ---------- 4. 渲染预览（写 OUT/renders/） ----------
if STAGE in ("render", "full"):
    setup_render(engine="CYCLES", samples=32, resolution=(512, 512))
    render_views(os.path.join(OUT, "renders"))

# ---------- 5. 导出（写 OUT/exports/，report.json 落在 OUT） ----------
if STAGE in ("build", "full"):
    export_all(os.path.join(OUT, "exports"), stem="model")
```

**怎么用**：从第 1 节索引里选配方 → 把配方代码块粘到上面第 2 段 → `python scripts/run_blender.py --script <输出目录>/model.py --out <输出目录> --stage build` 先确认不报错 → 换成 `--stage full` 出图 → `read_image` 看图自检。

### 0.3 每条配方代码块的约定

- 首行没有 `import`/`reset_scene`：默认当作**通用骨架第 2 段的替换内容**，变量 `main` 是最终 join 对象。想把单块配方独立跑，在最前面补 5 行骨架开头、最后补 `fit_camera + render_views + export_all` 即可。
- 材质变量用 `mat(name, color, roughness, metallic=..., emission=...)` 建，`color` 是 0~1 的 RGB，不是 0~255。
- 尺寸是"真实尺寸的推荐值"，可按需求整体乘系数，但**必须先缩放再 join/摆位**，否则部件之间会错位。

### 0.4 常用材质速查（低多边形风格）

| 材质 | `mat()` 参数 | 用在哪 |
| --- | --- | --- |
| 木（暖） | `(0.55, 0.36, 0.20), roughness=0.65` | 桌椅书架、木地板 |
| 木（深） | `(0.30, 0.20, 0.12), roughness=0.80` | 门框、旧家具、栅栏 |
| 陶瓷/釉面 | `(0.92, 0.90, 0.86), roughness=0.40` | 杯碗盘、花瓶 |
| 哑光金属 | `(0.18, 0.18, 0.20), roughness=0.35, metallic=0.9` | 灯杆、支架 |
| 亮金属/镀铬 | `(0.78, 0.78, 0.82), roughness=0.15, metallic=1.0` | 护手、轮毂、防撞条 |
| 布料 | `(0.30, 0.42, 0.52), roughness=0.92` | 沙发、床品、窗帘 |
| 玻璃（假） | `(0.10, 0.15, 0.20), roughness=0.08, metallic=0.2` | 车窗、屏幕、窗玻璃 |
| 岩石 | `(0.40, 0.40, 0.42), roughness=0.95` | 石头、山、地基 |
| 草地/树冠 | `(0.18, 0.42, 0.14), roughness=0.85` | 树冠、灌木、草地 |
| 自发光 | `emission=(1.0, 0.8, 0.45), emission_strength=3~8` | 灯泡、LED、车灯 |

**色彩空间（易踩坑）**：`mat(color=...)` 的 RGB 直接写入 Principled BSDF 的 Base Color，即**线性（scene-linear）数值**，不是 sRGB 直觉值/十六进制。上表是按渲染效果测试过的线性值；若按 sRGB 取色需先转线性（sRGB 0.55 ≈ 线性 0.26），否则暖木、布料这类中低饱和色会明显发白（实测：暖木按 sRGB 直觉给 `(0.55, 0.36, 0.20)` 出图发白，压到 `(0.25, 0.13, 0.060)` 才像橡木）。

---

## 1. 题材 → 配方索引

| # | 题材 | 推荐 slug | 关键尺寸（米） | 难度 | 核心技术 |
| --- | --- | --- | --- | --- | --- |
| 2.1 | 低多边形马克杯 | `lowpoly-mug` | 高 0.09、直径 0.084 | ★ | 圆柱 + 布尔挖腔 + 环面把手 |
| 2.2 | 碗与盘 | `bowl-and-plate` | 碗口径 0.17、盘径 0.26 | ★ | 圆锥布尔挖腔、圆柱布尔凹槽 |
| 2.3 | 椅子 | `chair` | 宽 0.46 × 深 0.44 × 高 0.88 | ★★ | 盒子拼装 + 统一倒角 |
| 2.4 | 桌子 | `dining-table` | 1.30 × 0.75 × 高 0.75 | ★ | 盒子拼装（与椅子同族） |
| 2.5 | 书架 | `bookshelf` | 宽 1.26 × 深 0.32 × 高 1.84 | ★★ | 阵列修改器做层板、循环排书 |
| 2.6 | 沙发 | `sofa` | 宽 2.10 × 深 0.90 × 高 0.90 | ★★ | 软包大倒角、垫子分件 |
| 2.7 | 床 | `bed` | 宽 1.70 × 长 2.10 × 高 0.92 | ★★ | 多薄层堆叠（床架/床垫/被子） |
| 2.8 | 台灯 | `table-lamp` | 高 0.42、灯罩直径 0.32 | ★★ | 圆锥布尔挖罩 + 发光球 |
| 2.9 | 小木屋 | `cabin` | 4.0 × 3.5 × 高 4.2 | ★★★ | 布尔开门窗、四棱锥屋顶、局部缩放 |
| 2.10 | 树 | `tree` | 高约 4.8、冠幅 2.4 | ★★ | 圆锥树干 + 多个低段球树冠 |
| 2.11 | 石头 | `rock-cluster` | 主石 0.8 × 0.5 | ★ | 低段球 + 置换 + flat 着色 |
| 2.12 | 花（盆栽） | `potted-flower` | 高 0.47、盆径 0.16 | ★★ | 圆锥盆 + 圆柱茎 + 球瓣环 |
| 2.13 | 汽车 | `car` | 长 4.4 × 宽 1.8 × 高 1.4 | ★★★★ | 大倒角车身 + 胶囊形车舱 + 圆柱轮 |
| 2.14 | 无人机 | `drone` | 对角轴距 0.47、高 0.24 | ★★★ | 交叉臂 + 圆柱电机 + 薄膜桨 |
| 2.15 | 机器人 | `robot` | 高 1.16、宽 0.73 | ★★★ | 对称硬表面 + 发光眼 |

> 选型提示：**高瘦题材**（人形、无人机）用 `elevation=20~25` 的略低视角更显体积；**扁平题材**（碗盘、手机）
> 用 `elevation=35~45` 俯视，否则看不清内部结构。相机距离 ≈ 物体最大边长的 2~3 倍。

---

## 2. 配方

### 2.1 低多边形马克杯 `lowpoly-mug` ★

**尺寸** 高 0.090、杯身直径 0.084、含把手外扩至约 0.150
**部件** ① 杯身圆筒（主体） ② 内腔（布尔挖出） ③ 把手环 ④ 杯底（保留 12mm 厚）
**图元/修改器** `cylinder` + `boolean(DIFFERENCE)` + `bevel` + `torus`；不收细
**分段** 圆柱 24（更狠的低模可 12，布尔会更棱角）；环面用 kit 默认密度
**收尾要点** 布尔切割体顶部必须高过杯口，否则封口；倒角宽度 ≤ 壁厚的一半
**朝向** 旋转对称，朝向无要求（把手在 +X 侧；想换边就把 handle 的 x 取反）
**难度** ★（约 3 分钟）

```python
ceramic = mat("mug_ceramic", (0.82, 0.28, 0.22), roughness=0.5)
body = cylinder("mug_body", radius=0.042, depth=0.090, vertices=24, location=(0, 0, 0.045), material=ceramic)
hollow = cylinder("mug_hollow", radius=0.037, depth=0.080, vertices=24, location=(0, 0, 0.052))  # 顶面高过杯口 2mm
add_boolean(body, hollow, "DIFFERENCE")                 # 挖内腔，杯底剩 12mm
add_bevel(body, width=0.0015, segments=2, angle_limit=40); apply_modifiers(body); shade_smooth(body, angle=40)
handle = torus("mug_handle", major_radius=0.024, minor_radius=0.0055, location=(0.046, 0, 0.048), material=ceramic)
rotate(handle, x=90); shade_smooth(handle)              # 环面立到 XZ 平面，套进杯身右侧
mug = join([body, handle], "lowpoly_mug"); set_origin(mug, "BOTTOM")
```

> 变体：去掉 handle、高度 ×1.5 → 笔筒；杯身压扁到 0.055 高、口径放大到 0.11 → 咖啡碗；半径全乘 0.5 → 酒盅。

### 2.2 碗与盘 `bowl-and-plate` ★

**尺寸** 碗：口径 0.170、高 0.060；盘：直径 0.260、高 0.016
**部件** ① 碗壁（锥台，布尔挖内腔） ② 碗口釉圈（环面） ③ 盘面（圆柱） ④ 盘心凹槽（布尔）
**图元/修改器** `cone` + `boolean` + `bevel` + `torus` + `cylinder`
**分段** 圆锥/圆柱 28~32（曲面感重要，低模也别低于 20）
**收尾要点** 两个器皿并排摆，间距留出 0.05 以上；布尔凹槽不能切穿底部
**朝向** 圆器皿旋转对称，朝向无要求
**难度** ★（约 3 分钟）

```python
ceramic = mat("dish_ceramic", (0.92, 0.90, 0.86), roughness=0.45)
glaze = mat("dish_glaze", (0.22, 0.45, 0.62), roughness=0.35)
bowl = cone("bowl_shell", radius1=0.045, radius2=0.085, depth=0.060, vertices=28, location=(-0.13, 0, 0.030), material=ceramic)
add_boolean(bowl, cone("bowl_inner", radius1=0.040, radius2=0.090, depth=0.070, vertices=28, location=(-0.13, 0, 0.040)), "DIFFERENCE")
add_bevel(bowl, 0.0015, segments=2); apply_modifiers(bowl); shade_smooth(bowl, angle=35)
rim = torus("bowl_rim", major_radius=0.085, minor_radius=0.003, location=(-0.13, 0, 0.060), material=glaze)
plate = cylinder("plate", radius=0.130, depth=0.016, vertices=32, location=(0.16, 0, 0.008), material=ceramic)
add_boolean(plate, cylinder("plate_well", radius=0.100, depth=0.010, vertices=32, location=(0.16, 0, 0.016)), "DIFFERENCE")
add_bevel(plate, 0.002, segments=2); apply_modifiers(plate); shade_smooth(plate, angle=40)
tableware = join([bowl, rim, plate], "bowl_and_plate"); set_origin(tableware, "BOTTOM")
```

> 关键参数：`bowl_inner` 的 `radius2`（顶部半径）要大于碗口半径的 90%，才能开出薄而自然的碗沿。

### 2.3 椅子 `chair` ★★

**尺寸** 宽 0.46 × 深 0.44 × 高 0.88（坐高 0.47）
**部件** ① 座板 ② 四条腿 ③ 靠背立柱 ×2（后腿向上延伸） ④ 靠背板 ⑤ 前横撑
**图元/修改器** 全部 `cube`；join 后统一 `bevel`（0.004 × 2 段）
**分段** 硬表面无分段概念；倒角就是它的"圆角语言"
**收尾要点** 四条腿必须落地 z=0；靠背与座板留 1cm 重叠；座板尺寸别小于 0.4×0.4，会显得像凳子
**朝向** 正面 = 坐人的开口一侧，朝 **+Y**；靠背/靠背立柱在 −Y
**难度** ★★（约 8 分钟）

```python
wood = mat("chair_wood", (0.55, 0.36, 0.20), roughness=0.6)
seat = cube("seat", size=(0.46, 0.44, 0.04), location=(0, 0, 0.45), material=wood)
legs = [cube(f"leg_{i}", size=(0.04, 0.04, 0.44), location=(x, y, 0.22), material=wood)
        for i, (x, y) in enumerate([(-0.20, 0.18), (0.20, 0.18), (-0.20, -0.18), (0.20, -0.18)])]
posts = [cube(f"post_{i}", size=(0.04, 0.04, 0.42), location=(x, -0.18, 0.67), material=wood)
         for i, x in enumerate((-0.20, 0.20))]                       # 靠背立柱，向上延伸后腿（靠背在 −Y）
back = cube("backrest", size=(0.44, 0.03, 0.16), location=(0, -0.18, 0.74), material=wood)
stretcher = cube("stretcher", size=(0.40, 0.03, 0.03), location=(0, 0.18, 0.12), material=wood)  # 前横撑在 +Y
chair = join([seat, back, stretcher] + legs + posts, "chair")
add_bevel(chair, width=0.004, segments=2); apply_modifiers(chair)
set_origin(chair, "BOTTOM")
```

> 变体：去掉靠背立柱和靠背板 → 凳子；把座板加宽到 1.4 → 长凳；整体 ×1.3、腿加长 → 吧椅。

### 2.4 桌子 `dining-table` ★

**尺寸** 长 1.30 × 宽 0.75 × 高 0.75（桌面厚 0.05）
**部件** ① 桌面 ② 四条腿 ③ 桌裙（两条长的横档） ④ 可选：抽屉面板
**图元/修改器** `cube` × 7；join 后 `bevel`（0.003 × 2 段）
**分段** 硬表面；桌面建议保持薄（0.04~0.06），太厚像工作台
**收尾要点** 桌面中心 z = 0.75 − 厚度/2；桌裙要同时接触桌面底面与腿
**朝向** 矩形桌没有正反面，任选一边作正面即可
**难度** ★（约 5 分钟）

```python
wood = mat("table_wood", (0.58, 0.39, 0.23), roughness=0.55)
top = cube("table_top", size=(1.30, 0.75, 0.05), location=(0, 0, 0.725), material=wood)
legs = [cube(f"leg_{i}", size=(0.06, 0.06, 0.70), location=(x, y, 0.35), material=wood)
        for i, (x, y) in enumerate([(-0.56, -0.29), (0.56, -0.29), (-0.56, 0.29), (0.56, 0.29)])]
aprons = [cube(f"apron_{i}", size=(1.10, 0.03, 0.09), location=(0, s * 0.30, 0.655), material=wood)
          for i, s in enumerate((-1, 1))]
table = join([top] + legs + aprons, "dining_table")
add_bevel(table, width=0.003, segments=2); apply_modifiers(table)
set_origin(table, "BOTTOM")
```

> 变体：桌面缩到 0.6×0.6、腿短到 0.5 → 茶几；桌面加厚到 0.08、腿变双立柱 → 书桌；桌面拉到 1.8 → 餐桌（可配 4 把椅子）。

### 2.5 书架 `bookshelf` ★★

**尺寸** 宽 1.26 × 深 0.32 × 高 1.84
**部件** ① 两侧立板 ② 背板 ③ 5 层层板 ④ 顶板 ⑤ 书本（不同颜色的小方块）
**图元/修改器** `cube` + `add_array`（层板阵列）+ 循环 `cube`（书）+ join 后统一 `bevel`
**分段** 硬表面；层板厚度 0.025 足够，别做太厚
**收尾要点** 层板宽度必须等于两立板内距（本例 1.17），否则缝隙明显；书本贴层板上表面
**朝向** 正面 = 书架开口一侧，朝 **+Y**；背板在 −Y
**难度** ★★（约 12 分钟）

```python
wood = mat("shelf_wood", (0.48, 0.31, 0.18), roughness=0.65)
sides = [cube(f"side_{i}", size=(0.03, 0.30, 1.80), location=(s * 0.60, 0, 0.90), material=wood) for i, s in enumerate((-1, 1))]
back = cube("back", size=(1.20, 0.02, 1.80), location=(0, -0.14, 0.90), material=wood)   # 背板在 −Y，开口朝 +Y
board = cube("board", size=(1.17, 0.28, 0.025), location=(0, 0, 0.02), material=wood)
add_array(board, count=5, offset=(0, 0, 0.40)); apply_modifiers(board)      # 5 层，层距 0.40
top = cube("top", size=(1.26, 0.32, 0.04), location=(0, 0, 1.82), material=wood)
colors = [(0.70, 0.22, 0.18), (0.18, 0.32, 0.58), (0.78, 0.66, 0.20), (0.24, 0.52, 0.30), (0.48, 0.28, 0.56)]
books = []
for i in range(12):                                                          # 3 层 × 4 本，循环配色
    h = (0.17, 0.20, 0.15)[i % 3]
    books.append(cube(f"book_{i}", size=(0.045, 0.18, h),
                      location=(-0.46 + (i % 4) * 0.22, -0.02, 0.42 + (i % 3) * 0.40 + 0.0125 + h / 2),
                      material=mat(f"book_{i % 5}", colors[i % 5], roughness=0.75)))
bookshelf = join([sides[0], sides[1], back, board, top] + books, "bookshelf")
add_bevel(bookshelf, width=0.002, segments=1); apply_modifiers(bookshelf)
set_origin(bookshelf, "BOTTOM")
```

> 关键点：`mat()` 同名重复调用会返回同一材质，所以循环里 `mat(f"book_{i % 5}", ...)` 不会制造 12 份材质。

### 2.6 沙发 `sofa` ★★

**尺寸** 宽 2.10 × 深 0.90 × 高 0.90（座高 0.42）
**部件** ① 底座 ② 靠背 ③ 两个扶手 ④ 三个坐垫 ⑤ 三个背垫（略后倾） ⑥ 四个木脚
**图元/修改器** `cube` + `cylinder`；join 后统一 `bevel`（0.015 × 2 段）做软包感
**分段** 硬表面；软包靠倒角表现，不要用 subsurf（会变太圆失去块面感）
**收尾要点** 坐垫略窄于底座（留出扶手），背垫向 −Y 后倾 8~12°；木脚要露出来
**朝向** 正面 = 坐面开口一侧，朝 **+Y**；靠背在 −Y
**难度** ★★（约 10 分钟）

```python
fabric = mat("sofa_fabric", (0.26, 0.38, 0.48), roughness=0.92)
cushion = mat("sofa_cushion", (0.34, 0.47, 0.57), roughness=0.95)
base = cube("sofa_base", size=(2.10, 0.90, 0.32), location=(0, 0, 0.26), material=fabric)
back = cube("sofa_back", size=(2.10, 0.24, 0.58), location=(0, -0.33, 0.61), material=fabric)   # 靠背在 −Y
arms = [cube(f"arm_{i}", size=(0.22, 0.90, 0.36), location=(s * 0.94, 0, 0.54), material=fabric) for i, s in enumerate((-1, 1))]
seats = [cube(f"seat_{i}", size=(0.60, 0.70, 0.16), location=(x, 0.05, 0.50), material=cushion) for i, x in enumerate((-0.63, 0, 0.63))]
backs = [cube(f"back_cushion_{i}", size=(0.60, 0.16, 0.34), location=(x, -0.15, 0.66), rotation=(12, 0, 0), material=cushion) for i, x in enumerate((-0.63, 0, 0.63))]
feet = [cylinder(f"foot_{i}", radius=0.035, depth=0.10, vertices=8, location=(x, y, 0.05),
                 material=mat("sofa_leg", (0.16, 0.11, 0.08), roughness=0.8))
        for i, (x, y) in enumerate([(-0.92, -0.34), (0.92, -0.34), (-0.92, 0.34), (0.92, 0.34)])]
sofa = join([base, back] + arms + seats + backs + feet, "sofa")
add_bevel(sofa, width=0.015, segments=2); apply_modifiers(sofa)
set_origin(sofa, "BOTTOM")
```

> 变体：宽 0.9、去掉中间坐垫 → 单人沙发；扶手去掉、整体放大 → 懒人沙发；底座加轮子 → 沙发车。

### 2.7 床 `bed` ★★

**尺寸** 宽 1.70 × 长 2.10 × 高 0.92（床面 0.56）
**部件** ① 床架 ② 四个短脚 ③ 床垫 ④ 床头板 ⑤ 两个枕头 ⑥ 被子（盖住下半段）
**图元/修改器** `cube` + `cylinder`；join 后 `bevel`（0.01 × 2 段）
**分段** 硬表面；枕头/被子用倒角出柔软感，被子高度只留 0.10
**收尾要点** 枕头靠床头、被子盖住脚端；床头板高于 0.8 才像床
**朝向** 床没有正反之分：本配方床头板在 +Y、床尾（被子端）在 −Y；若希望 front 图看到床尾，整体绕 Z 转 180°
**难度** ★★（约 8 分钟）

```python
wood = mat("bed_wood", (0.42, 0.30, 0.20), roughness=0.7)
linen = mat("bed_linen", (0.88, 0.86, 0.82), roughness=0.95)
duvet = mat("bed_duvet", (0.28, 0.44, 0.60), roughness=0.95)
frame = cube("bed_frame", size=(1.70, 2.10, 0.28), location=(0, 0, 0.20), material=wood)
legs = [cylinder(f"leg_{i}", radius=0.04, depth=0.12, vertices=8, location=(x, y, 0.06), material=wood)
        for i, (x, y) in enumerate([(-0.78, -0.98), (0.78, -0.98), (-0.78, 0.98), (0.78, 0.98)])]
mattress = cube("mattress", size=(1.64, 2.02, 0.22), location=(0, 0, 0.45), material=linen)
headboard = cube("headboard", size=(1.70, 0.08, 0.85), location=(0, 1.02, 0.50), material=wood)
pillows = [cube(f"pillow_{i}", size=(0.62, 0.36, 0.13), location=(x, 0.70, 0.63), rotation=(-8, 0, 0), material=linen) for i, x in enumerate((-0.40, 0.40))]
blanket = cube("duvet", size=(1.66, 1.25, 0.10), location=(0, -0.36, 0.58), material=duvet)
bed = join([frame, mattress, headboard, blanket] + legs + pillows, "bed")
add_bevel(bed, width=0.01, segments=2); apply_modifiers(bed)
set_origin(bed, "BOTTOM")
```

> 变体：宽缩到 0.95 → 单人床；去掉被子、床垫换深色 → 医疗床/行军床；加一个床尾柜（从 `box` 组合）。

### 2.8 台灯 `table-lamp` ★★

**尺寸** 高 0.42、灯罩最大直径 0.32、底座直径 0.15
**部件** ① 圆形底座 ② 细灯杆 ③ 灯罩（圆锥挖空，下开口） ④ 灯泡（发光球）
**图元/修改器** `cylinder` + `cone` + `boolean` + `sphere`；灯罩 `shade_smooth`
**分段** 灯罩/底座 32（曲面主体），灯杆 16，灯泡球 16×10
**收尾要点** 灯罩的挖空圆锥要**从下方伸出**，才能形成下开口的罩；灯泡放进罩腔内
**朝向** 旋转对称，朝向无要求
**难度** ★★（约 8 分钟）

```python
metal = mat("lamp_metal", (0.18, 0.18, 0.20), roughness=0.35, metallic=0.9)
shade_mat = mat("lamp_shade", (0.95, 0.82, 0.55), roughness=0.8)
bulb_mat = mat("lamp_bulb", (1.0, 0.86, 0.60), roughness=0.4, emission=(1.0, 0.80, 0.45), emission_strength=8.0)
base = cylinder("lamp_base", radius=0.075, depth=0.022, vertices=32, location=(0, 0, 0.011), material=metal)
stem = cylinder("lamp_stem", radius=0.009, depth=0.30, vertices=16, location=(0, 0, 0.17), material=metal)
bulb = sphere("lamp_bulb", radius=0.035, segments=16, rings=10, location=(0, 0, 0.28), material=bulb_mat)
shade = cone("lamp_shade", radius1=0.160, radius2=0.085, depth=0.18, vertices=32, location=(0, 0, 0.33), material=shade_mat)
add_boolean(shade, cone("lamp_cut", radius1=0.145, radius2=0.070, depth=0.20, vertices=32, location=(0, 0, 0.30)), "DIFFERENCE")
add_bevel(shade, 0.002, segments=2); apply_modifiers(shade); shade_smooth(shade, angle=40)
lamp = join([base, stem, bulb, shade], "table_lamp"); set_origin(lamp, "BOTTOM")
```

> 变体：灯杆高度 ×10、底座半径 ×2 → 路灯；灯罩换成半透明发光材质 → 灯笼；加一根弯管（`tube`）→ 床头阅读灯。

### 2.9 小木屋 `cabin` ★★★

**尺寸** 占地 4.0 × 3.5、墙高 2.6、屋脊高 4.2（总高 4.2）
**部件** ① 地基石台 ② 墙体（布尔挖门洞/窗洞） ③ 四棱锥屋顶（压扁成矩形底） ④ 烟囱 ⑤ 门前台阶 ⑥ 门板 ⑦ 两块窗玻璃
**图元/修改器** `cube` + `boolean` ×3 + `cone(vertices=4)` + `scale_obj`；**先烘焙旋转再缩放**
**分段** 四棱锥用 4 顶点（无分段）；布尔切完不再细分
**收尾要点** 屋顶底面要略低于墙顶（重叠 5cm）防漏缝；椽口要出挑 0.1~0.2；烟囱要高于屋面
**朝向** 正面 = 开门窗的一侧，朝 **+Y**；门窗洞/门板/台阶都开在 +Y 墙面上
**难度** ★★★（约 20 分钟）

```python
wall = mat("cabin_wall", (0.74, 0.60, 0.44), roughness=0.85); roof_mat = mat("cabin_roof", (0.38, 0.22, 0.15), roughness=0.8)
stone = mat("cabin_stone", (0.44, 0.44, 0.42), roughness=0.95); wood_dark = mat("cabin_door", (0.30, 0.20, 0.13), roughness=0.7)
glass = mat("cabin_glass", (0.45, 0.66, 0.78), roughness=0.08)
found = cube("foundation", size=(4.20, 3.70, 0.20), location=(0, 0, 0.10), material=stone)
walls = cube("walls", size=(4.00, 3.50, 2.60), location=(0, 0, 1.50), material=wall)   # 墙 z 0.20~2.80
for name, size, loc in [("door", (0.90, 0.60, 2.00), (0, 1.75, 1.20)),
                        ("win_l", (0.80, 0.60, 0.80), (-1.25, 1.75, 1.65)),
                        ("win_r", (0.80, 0.60, 0.80), (1.25, 1.75, 1.65))]:
    add_boolean(walls, cube(f"cut_{name}", size=size, location=loc), "DIFFERENCE")     # 切门洞 + 两窗（正面 +Y）
roof = cone("roof", radius1=3.10, radius2=0.0, depth=1.45, vertices=4, location=(0, 0, 3.475), material=roof_mat)
place(roof, rotation=(0, 0, 45)); apply_transform(roof, rotation=True)                  # 先转 45° 烘焙，再按世界轴压扁
scale_obj(roof, (1.0, 0.845, 1.0))                                                     # 4.38 × 3.70 的矩形底
chimney = cube("chimney", size=(0.45, 0.45, 1.20), location=(1.25, -0.78, 3.00), material=stone)  # 烟囱靠后（−Y）
step = cube("step", size=(1.00, 0.40, 0.10), location=(0, 1.95, 0.05), material=stone)
door = cube("door", size=(0.86, 0.06, 1.96), location=(0, 1.72, 1.18), material=wood_dark)
panes = [cube(f"pane_{i}", size=(0.78, 0.05, 0.78), location=(x, 1.73, 1.65), material=glass) for i, x in enumerate((-1.25, 1.25))]
cabin = join([found, walls, roof, chimney, step, door] + panes, "cabin"); set_origin(cabin, "BOTTOM")
```

> 坑：`scale_obj` 是**局部轴**缩放。四棱锥必须先 `apply_transform(rotation=True)` 把 45° 烘焙进网格，
> 再按世界 Y 轴压扁，否则屋顶会变成菱形斜顶。改成坡屋顶：用两块中心对称、绕 X 轴 ±38° 的薄立方体做屋面，
> 两端用三棱柱（`cone(vertices=3)` 旋转 90° 后压扁）补山墙。

### 2.10 树 `tree` ★★

**尺寸** 高约 4.8、树冠最大直径约 2.4、树干直径 0.4~0.5
**部件** ① 树干（圆锥，下粗上细） ② 四个错落的低段球树冠（主体 + 3 个偏置球）
**图元/修改器** `cone` + `sphere` ×4；`shade_flat` 出低模面块感（想圆润可 `shade_smooth`）
**分段** 树干 8~10 段，树冠球 8 段 × 6 环（这是低多边形树的关键）
**收尾要点** 树冠之间要互相重叠（不能 4 个分离的球），最低的球要压住树干顶端
**朝向** 自然物，朝向无要求（树冠偏置方向可随场景旋转）
**难度** ★★（约 6 分钟）

```python
bark = mat("tree_bark", (0.30, 0.20, 0.12), roughness=0.95)
leaf = mat("tree_leaf", (0.18, 0.42, 0.14), roughness=0.85)
trunk = cone("trunk", radius1=0.24, radius2=0.13, depth=2.40, vertices=8, location=(0, 0, 1.20), material=bark)
crowns = []
for x, y, z, r in [(0.00, 0.00, 3.30, 1.20), (0.85, 0.35, 2.95, 0.85), (-0.75, -0.30, 3.10, 0.95), (0.10, -0.05, 4.05, 0.78)]:
    c = sphere(f"crown_{len(crowns)}", radius=r, segments=8, rings=6, location=(x, y, z), material=leaf)
    shade_flat(c); crowns.append(c)                     # flat 着色 → 低多边形棱面
tree = join([trunk] + crowns, "tree"); set_origin(tree, "BOTTOM")
```

> 变体（松树）：树干保留，树冠换成 3 个上下叠放的 `cone(vertices=8)`，半径 1.1/0.8/0.5；
> 变体（灌木）：去掉树干，树冠球半径 ×0.35、整体高度 ×0.3。

### 2.11 石头 `rock-cluster` ★

**尺寸** 主石 0.80 × 0.68 × 0.50，配两块小石
**部件** ① 主石 ② 两块偏置小石（一处一石，形成自然组合）
**图元/修改器** `sphere(segments=8, rings=5)` + `scale_obj` 压扁 + `add_displace` 噪波 + `shade_flat`
**分段** 球 8×5 起步，越低越像low-poly；不要超过 12×8
**收尾要点** 每块石头缩放比例不同才自然；用 `set_origin(BOTTOM)` 让石头贴地；置换强度 ≤ 半径的 1/6
**朝向** 自然物，朝向无要求
**难度** ★（约 5 分钟）

```python
rock_mat = mat("rock_gray", (0.40, 0.40, 0.42), roughness=0.95)
rocks = []
for i, (x, y, s) in enumerate([(0.00, 0.00, 1.00), (0.60, 0.20, 0.55), (-0.45, 0.30, 0.40)]):
    r = sphere(f"rock_{i}", radius=0.40 * s, segments=8, rings=5, location=(x, y, 0.34 * s), material=rock_mat)
    scale_obj(r, (1.00, 0.85, 0.62))                     # 压成扁椭圆
    add_displace(r, strength=0.05 * s, noise_scale=0.30 * s); apply_modifiers(r)
    shade_flat(r)
    rocks.append(r)
rock = join(rocks, "rock_cluster"); set_origin(rock, "BOTTOM")
```

> 变体：半径都 ×30、置换强度 ×30 → 山体；半径 ×0.1、加几块小碎石 → 路边碎石；材质加一点金色、metallic=0.6 → 矿石。

### 2.12 花（盆栽） `potted-flower` ★★

**尺寸** 高 0.47、花盆口径 0.16、花头直径约 0.16
**部件** ① 花盆（倒锥台） ② 盆沿（环面） ③ 土面（薄圆柱） ④ 茎 ⑤ 两片叶 ⑥ 六片花瓣 + 花心
**图元/修改器** `cone` + `torus` + `cylinder` + `sphere`；花瓣用压扁球绕 Z 均布
**分段** 花盆 16（低模）/32（圆润），花瓣球 8×6，花心 12×8
**收尾要点** 花瓣中心离花心 < 花瓣半径，才不会散开；花头朝上，茎要插进土里
**朝向** 花头朝上、绕 Z 旋转对称，朝向无要求
**难度** ★★（约 12 分钟）

```python
import math
clay = mat("flower_pot", (0.62, 0.30, 0.20), roughness=0.85)
dirt = mat("flower_soil", (0.13, 0.09, 0.06), roughness=1.0)
stem_mat = mat("flower_stem", (0.18, 0.45, 0.15), roughness=0.75)
petal_mat = mat("flower_petal", (0.92, 0.45, 0.55), roughness=0.65)
core_mat = mat("flower_core", (0.98, 0.82, 0.30), roughness=0.6)
pot = cone("pot", radius1=0.060, radius2=0.080, depth=0.130, vertices=16, location=(0, 0, 0.065), material=clay)
rim = torus("pot_rim", major_radius=0.080, minor_radius=0.006, location=(0, 0, 0.130), material=clay)
soil = cylinder("soil", radius=0.072, depth=0.014, vertices=16, location=(0, 0, 0.122), material=dirt)
stalk = cylinder("stalk", radius=0.007, depth=0.300, vertices=8, location=(0, 0, 0.265), material=stem_mat)
leaves = [sphere(f"leaf_{i}", radius=0.050, segments=8, rings=6, location=(x, 0, 0.24), rotation=(0, 30 * s, 0), material=stem_mat)
          for i, (x, s) in enumerate([(-0.055, 1), (0.055, -1)])]
for leaf in leaves: scale_obj(leaf, (1.0, 0.42, 0.22))   # 叶子压扁成薄片
petals = []
for i in range(6):
    a = math.radians(i * 60)
    p = sphere(f"petal_{i}", radius=0.032, segments=8, rings=6,
               location=(0.048 * math.cos(a), 0.048 * math.sin(a), 0.418), rotation=(0, 20, 0), material=petal_mat)
    scale_obj(p, (1.0, 0.62, 0.35)); petals.append(p)
heart = sphere("heart", radius=0.030, segments=12, rings=8, location=(0, 0, 0.425), material=core_mat)
flower = join([pot, rim, soil, stalk, heart] + leaves + petals, "potted_flower"); set_origin(flower, "BOTTOM")
```

> 变体：花瓣改 5 片、花心加大 → 向日葵；去掉花头只留叶 → 绿植；花盆放大 3 倍、加石头 → 花坛。

### 2.13 汽车 `car` ★★★★

**尺寸** 长 4.40（Y 轴）× 宽 1.80（X 轴）× 高 1.40
**部件** ① 下车身（大倒角盒子） ② 车舱（胶囊感盒子） ③ 玻璃环带（比车舱宽 2cm 的深色盒子） ④ 四个车轮 ⑤ 前后保险杠 ⑥ 两个发光大灯
**图元/修改器** `cube` + `bevel`（0.09~0.10 × 3 段）+ `cylinder` 轮子；车身 `shade_smooth(angle=40)`
**分段** 轮子 20 段；车身硬表面靠大倒角出弧形，不要用细分
**收尾要点** 车身底部离地 0.30（轮子露出半径的一半以上）；玻璃环带必须比车舱宽出 1~2cm，否则陷进车身看不见
**朝向** 车头（大灯、前保险杠）朝 **+Y**；车舱略偏后（−Y），车宽沿 X
**难度** ★★★★（约 25 分钟）

```python
paint = mat("car_paint", (0.68, 0.12, 0.10), roughness=0.28, metallic=0.3)
rubber = mat("car_rubber", (0.05, 0.05, 0.05), roughness=0.6)
glass = mat("car_glass", (0.08, 0.12, 0.16), roughness=0.08, metallic=0.2)
chrome = mat("car_chrome", (0.72, 0.72, 0.76), roughness=0.2, metallic=1.0)
bulb = mat("car_bulb", (1.0, 0.95, 0.80), roughness=0.2, emission=(1.0, 0.90, 0.70), emission_strength=3.0)
body = cube("car_body", size=(1.80, 4.40, 0.60), location=(0, 0, 0.62), material=paint)
add_bevel(body, 0.09, segments=3); apply_modifiers(body); shade_smooth(body, angle=40)
cabin = cube("car_cabin", size=(1.56, 2.10, 0.55), location=(0, -0.10, 1.13), material=paint)   # 车舱偏后（−Y）
add_bevel(cabin, 0.10, segments=3); apply_modifiers(cabin); shade_smooth(cabin, angle=40)
band = cube("car_glass_band", size=(1.60, 2.02, 0.30), location=(0, -0.10, 1.19), material=glass)   # 比车舱宽 → 露出的窗带
wheels = [cylinder(f"wheel_{i}", radius=0.34, depth=0.24, vertices=20, location=(x, y, 0.34), rotation=(0, 90, 0), material=rubber)
          for i, (x, y) in enumerate([(-0.82, -1.38), (0.82, -1.38), (-0.82, 1.38), (0.82, 1.38)])]
bumpers = [cube(f"bumper_{i}", size=(1.78, 0.18, 0.22), location=(0, s * 2.15, 0.44), material=chrome) for i, s in enumerate((-1, 1))]
lights = [sphere(f"headlight_{i}", radius=0.085, segments=12, rings=8, location=(x, 2.18, 0.74), material=bulb) for i, x in enumerate((-0.60, 0.60))]  # 大灯在车头 +Y
car = join([body, cabin, band] + wheels + bumpers + lights, "car"); set_origin(car, "BOTTOM")
```

> 变体：车舱再加高 0.15、轮子加大 → SUV；车身压扁到 0.45 高、车舱压到 0.35 → 跑车；
> 去掉车舱只留车身 + 货斗（薄盒）→ 皮卡。**坐标系约定**：车头朝 +Y，车宽沿 X，大灯/前保险杠在 +Y 端。

### 2.14 无人机 `drone` ★★★

**尺寸** 对角轴距 0.47、总高 0.24、桨叶外接直径约 0.73
**部件** ① 机身（带倒角小盒） ② 两根交叉臂 ③ 四个电机 ④ 四支桨 ⑤ 云台相机球 ⑥ 两个起落脚 ⑦ 两个 LED
**图元/修改器** `cube` + `bevel` + `cylinder`；臂用一根长盒交叉 45° 即可，不用做 4 根
**分段** 电机 12 段、相机球 14×8、桨叶用薄盒（低模更利落）
**收尾要点** 桨必须高于电机；交叉臂做成一整根（跨过机身），四电机要落在臂端点上
**朝向** 机身四轴旋转对称，朝向无要求；云台相机朝 **+Y**（前向），换向只需把 camera 的 y 取反
**难度** ★★★（约 15 分钟）

```python
frame_mat = mat("drone_frame", (0.12, 0.13, 0.15), roughness=0.4, metallic=0.6)
prop_mat = mat("drone_prop", (0.16, 0.16, 0.18), roughness=0.35, metallic=0.8)
cam_mat = mat("drone_cam", (0.04, 0.04, 0.05), roughness=0.25)
led_mat = mat("drone_led", (0.10, 0.90, 0.30), roughness=0.2, emission=(0.10, 1.00, 0.30), emission_strength=6.0)
body = cube("drone_body", size=(0.20, 0.26, 0.10), location=(0, 0, 0.15), material=frame_mat)
add_bevel(body, 0.02, segments=2); apply_modifiers(body); shade_smooth(body, angle=40)
arms = [cube(f"arm_{i}", size=(0.66, 0.045, 0.035), location=(0, 0, 0.15), rotation=(0, 0, a), material=frame_mat) for i, a in enumerate((45, -45))]
motors, props = [], []
for i, (x, y) in enumerate([(-0.235, -0.235), (0.235, -0.235), (-0.235, 0.235), (0.235, 0.235)]):
    motors.append(cylinder(f"motor_{i}", radius=0.034, depth=0.060, vertices=12, location=(x, y, 0.195), material=frame_mat))
    props.append(cube(f"prop_{i}", size=(0.26, 0.028, 0.006), location=(x, y, 0.232), rotation=(0, 0, 20 + i * 30), material=prop_mat))
camera = sphere("camera", radius=0.045, segments=14, rings=8, location=(0, 0.14, 0.11), material=cam_mat)  # 云台相机朝前 +Y
skids = [cube(f"skid_{i}", size=(0.05, 0.04, 0.10), location=(s * 0.07, 0, 0.05), material=frame_mat) for i, s in enumerate((-1, 1))]
leds = [sphere(f"led_{i}", radius=0.016, segments=10, rings=6, location=(s * 0.10, 0.10, 0.19), material=led_mat) for i, s in enumerate((-1, 1))]
drone = join([body, camera] + arms + motors + props + skids + leds, "drone"); set_origin(drone, "BOTTOM")
```

> 变体：两臂拉长、机身加高 → 穿越机；加一个半球罩 → 测绘无人机；桨换成圆柱薄片 → 更"玩具感"。

### 2.15 机器人 `robot` ★★★

**尺寸** 总高 1.16、肩宽 0.73、躯干 0.50 宽
**部件** ① 方头 + 深色面屏 + 两颗发光眼 ② 颈 ③ 躯干 + 胸口徽标 ④ 两条圆柱臂 + 球形手 ⑤ 两条圆柱腿 + 方块脚
**图元/修改器** `cube`（倒角 0.03~0.04）+ `cylinder` + `sphere`；左右对称用循环 + 符号 `s in (-1, 1)`
**分段** 圆柱 12、球 12×8（硬表面为主，球件刻意低段）
**收尾要点** 头盔/躯干必须倒角，否则就是"纸箱子"；脚要朝前（+Y）伸出，站立才稳
**朝向** 正面（面屏 + 两颗眼 + 胸口徽标）朝 **+Y**；脚尖朝 +Y
**难度** ★★★（约 18 分钟）

```python
metal = mat("robot_metal", (0.72, 0.74, 0.78), roughness=0.35, metallic=0.7)
dark = mat("robot_dark", (0.08, 0.09, 0.10), roughness=0.5, metallic=0.4)
accent = mat("robot_accent", (0.88, 0.55, 0.10), roughness=0.4, metallic=0.3)
eye_mat = mat("robot_eye", (0.20, 0.90, 1.00), roughness=0.15, emission=(0.20, 0.90, 1.00), emission_strength=6.0)
head = cube("head", size=(0.34, 0.30, 0.28), location=(0, 0, 1.02), material=metal)
add_bevel(head, 0.03, segments=2); apply_modifiers(head)
face = cube("face", size=(0.26, 0.02, 0.16), location=(0, 0.155, 1.02), material=dark)   # 面屏朝 +Y
eyes = [sphere(f"eye_{i}", radius=0.032, segments=12, rings=8, location=(x, 0.165, 1.04), material=eye_mat) for i, x in enumerate((-0.07, 0.07))]
neck = cylinder("neck", radius=0.06, depth=0.08, vertices=16, location=(0, 0, 0.83), material=dark)
torso = cube("torso", size=(0.50, 0.30, 0.52), location=(0, 0, 0.55), material=metal)
add_bevel(torso, 0.04, segments=2); apply_modifiers(torso)
chest = cube("chest", size=(0.20, 0.03, 0.16), location=(0, 0.16, 0.60), material=accent)   # 胸口徽标朝 +Y
arms, legs = [], []
for s in (-1, 1):                                            # 左右对称拼装
    arms.append(cylinder(f"arm_{s}", radius=0.055, depth=0.36, vertices=12, location=(s * 0.31, 0, 0.55), material=metal))
    arms.append(sphere(f"hand_{s}", radius=0.065, segments=12, rings=8, location=(s * 0.31, 0, 0.35), material=dark))
    legs.append(cylinder(f"leg_{s}", radius=0.06, depth=0.34, vertices=12, location=(s * 0.13, 0, 0.17), material=metal))
    legs.append(cube(f"foot_{s}", size=(0.16, 0.24, 0.08), location=(s * 0.13, 0.03, 0.04), material=dark))  # 脚尖朝 +Y
robot = join([head, face, neck, torso, chest] + eyes + arms + legs, "robot"); set_origin(robot, "BOTTOM")
```

> 变体：头部放大 1.4 倍 → 头身比 Q 版机器人；躯干加高、腿加粗 → 机甲；头顶加天线（细圆柱 + 小球）→ 服务机器人。

---

## 3. 配方收尾自检清单（每个模型必过）

1. **尺寸**：报告里的 `dimensions` 与真实比例一致（椅子高 0.8~0.95、桌面 0.7~0.8、杯高 0.08~0.10）。
2. **贴地**：脚/轮/底必须到 z=0；`scene_report()["bbox_min"][2]` 应接近 0（允许 ±2cm）。
3. **接触**：相邻部件无缝隙、无"漂浮 5cm"的典型错误（腿比座板短一截最常发生）。
4. **朝向**：正面朝 **+Y**（kit 的 `front` 相机在 +Y 侧看向原点，`view-front.png` 看到的就是朝 +Y 的面）；车头、机头、门、屏幕、脸都朝 +Y；床尾/车尾/后脑勺等反面特征才在 −Y。**+X 是物体右侧（front 图里显示在画面左侧），不要用画面左右描述朝向。**
5. **几何干净**：`mesh_stats()` 里 `non_manifold_edges` 尽量为 0（布尔后偶尔有 1~2 条可接受）。
6. **渲染自检**：`read_image` 打开三张图，确认不是全黑、不是空场景、没有明显穿插；再按 `references/render-and-check.md` 的清单逐项过。

---

## 4. 组合 / 变形技巧：用配方拼新题材

### 4.1 五条拼装法则

1. **换比例**：同一套几何改长宽高比就是新题材（杯→碗、桌→茶几、柜→货架）。改比例时**同步改接触面**，否则会脱节。
2. **换材质**：几何不变、材质一换，题材就换（木桌 → 金属控制台；石头 → 矿石；台灯 → 荧光灯）。`metallic`/`roughness`/`emission` 三个参数值千金。
3. **阵列 / 旋转复制**：书架层板阵列、花瓣绕 Z 均布、栏杆重复、窗户成排。`add_array` + 循环 + `rotation` 三角函数。
4. **布尔组合**：盒子 − 盒子 = 门洞/抽屉/挖空机身；盒子 + 圆柱 = 半圆顶/宝箱盖；圆柱 − 圆柱 = 管道/灯罩。
5. **部件借用**：新题材 = 主体配方 + 另一配方的部件。例如"沙发 + 车轮 = 沙发车"、"桌子 + 台灯 + 书架 = 书房场景"、"小屋 + 树 + 石头 = 微缩村落"。

### 4.2 派生题材速查表

| 新题材 | 基础配方 | 变换方式 |
| --- | --- | --- |
| 宝箱 | 桌子 + 床 | 箱体缩到 0.8×0.5×0.4，顶部叠半圆柱盖，加环面铁箍 |
| 剑 / 匕首 | 马克杯 + 花 | 刀刃 = 薄立方体，刀尖 = 压扁四棱锥，护手 = 立方体，柄 = 圆柱 |
| 手机 | 桌子 | 倒角薄盒 0.075×0.155×0.008 + 屏幕薄片 + 圆柱摄像头 |
| 笔记本电脑 | 手机 + 桌子 | 两片倒角薄盒呈 105°，转轴用细圆柱 |
| 飞机 | 汽车 + 树 | 车身换成"圆柱机身 + 圆锥机头"，机翼/尾翼用压扁盒子 |
| 路灯 | 台灯 | 灯杆 ×10，底座半径 ×2，灯罩换成八棱锥 |
| 笔筒 | 马克杯 | 去掉把手，高度 ×1.5，口径 ×0.9 |
| 长凳 | 椅子 | 去掉靠背，座板加宽到 1.4，腿改为 4 条短粗腿 |
| 茶几 | 桌子 | 桌面缩到 0.6×0.6，高度 0.42 |
| 货架 | 书架 | 层板间距 ×1.45，去掉背板，深度 ×0.8 |
| 山 / 地形 | 石头 | 半径 ×30~50，置换强度 ×30，noise_scale ×25 |
| 灌木 | 树 | 去树干，树冠球半径 ×0.35、高度 ×0.3 |
| 招牌 | 小屋 | 立方体薄板 + `text()` 文字，挂在门楣上 |

### 4.3 变形速成（每块 6~10 行，接在通用骨架建模段）

**宝箱**（来自"桌子箱体 + 床的圆柱 + 环面铁箍"）
> 朝向：锁扣在 **+Y** 正面；铁箍/抱箍绕箱子一圈，对称。

```python
wood = mat("chest_wood", (0.44, 0.28, 0.16), roughness=0.8)
iron = mat("chest_iron", (0.20, 0.20, 0.22), roughness=0.45, metallic=0.9)
gold = mat("chest_gold", (0.85, 0.68, 0.22), roughness=0.3, metallic=1.0)
base = cube("chest_base", size=(0.80, 0.52, 0.40), location=(0, 0, 0.24), material=wood)
lid = cylinder("chest_lid", radius=0.26, depth=0.80, vertices=20, location=(0, 0, 0.44), rotation=(0, 90, 0), material=wood)
straps = [torus(f"strap_{i}", major_radius=0.265, minor_radius=0.018, location=(x, 0, 0.44), rotation=(0, 90, 0), material=iron) for i, x in enumerate((-0.26, 0.0, 0.26))]
bands = [cube(f"band_{i}", size=(0.06, 0.545, 0.42), location=(x, 0, 0.24), material=iron) for i, x in enumerate((-0.26, 0.0, 0.26))]
lock = cube("chest_lock", size=(0.11, 0.05, 0.13), location=(0, 0.275, 0.40), material=gold)   # 锁扣朝正面 +Y
feet = [cube(f"foot_{i}", size=(0.08, 0.08, 0.06), location=(x, y, 0.03), material=iron) for i, (x, y) in enumerate([(-0.32, -0.20), (0.32, -0.20), (-0.32, 0.20), (0.32, 0.20)])]
chest = join([base, lid, lock] + straps + bands + feet, "treasure_chest"); set_origin(chest, "BOTTOM")
```

**剑**（来自"薄板 + 四棱锥 + 圆柱"的图元组合）
> 朝向：剑身在厚度方向（Y）对称，朝向无要求；竖直握持时刃面朝 ±X。

```python
steel = mat("sword_steel", (0.82, 0.85, 0.90), roughness=0.15, metallic=1.0)
gold = mat("sword_gold", (0.85, 0.65, 0.20), roughness=0.25, metallic=1.0)
leather = mat("sword_grip", (0.25, 0.15, 0.10), roughness=0.8)
blade = cube("blade", size=(0.075, 0.024, 0.70), location=(0, 0, 0.60), material=steel)
add_bevel(blade, 0.006, segments=1); apply_modifiers(blade)
tip = cone("blade_tip", radius1=0.044, radius2=0.0, depth=0.14, vertices=4, location=(0, 0, 1.00), material=steel)
scale_obj(tip, (1.0, 0.30, 1.0))                        # 压扁成刃尖
guard = cube("guard", size=(0.26, 0.055, 0.035), location=(0, 0, 0.24), material=gold)
grip = cylinder("grip", radius=0.019, depth=0.17, vertices=12, location=(0, 0, 0.12), material=leather)
pommel = sphere("pommel", radius=0.034, segments=12, rings=8, location=(0, 0, 0.034), material=gold)
sword = join([blade, tip, guard, grip, pommel], "sword"); set_origin(sword, "BOTTOM")
```

**手机 / 平板**（来自"倒角薄盒"）
> 朝向：平放展示，屏幕朝 **+Z**；需要立起来时把手机绕 X 轴转 −90° 让屏幕朝 +Y。

```python
alu = mat("phone_body", (0.18, 0.19, 0.21), roughness=0.3, metallic=0.8)
screen = mat("phone_screen", (0.05, 0.06, 0.08), roughness=0.1)
body = cube("phone_body", size=(0.075, 0.155, 0.008), location=(0, 0, 0.004), material=alu)
add_bevel(body, 0.004, segments=3); apply_modifiers(body); shade_smooth(body, angle=40)
glass = cube("phone_screen", size=(0.068, 0.148, 0.002), location=(0, 0, 0.009), material=screen)
cam = cylinder("phone_cam", radius=0.007, depth=0.003, vertices=12, location=(-0.022, 0.062, 0.0105), material=screen)
phone = join([body, glass, cam], "phone"); set_origin(phone, "BOTTOM")
```

**笔记本电脑**（手机放大 + 转轴）
> 朝向：正面 = 用户/键盘一侧朝 **+Y**，屏幕盖与转轴在 −Y。

```python
alu = mat("laptop_body", (0.55, 0.57, 0.60), roughness=0.35, metallic=0.8)
screen = mat("laptop_screen", (0.05, 0.07, 0.10), roughness=0.1)
base = cube("laptop_base", size=(0.32, 0.22, 0.016), location=(0, 0, 0.008), material=alu)
add_bevel(base, 0.004, segments=2); apply_modifiers(base)
lid = cube("laptop_lid", size=(0.32, 0.016, 0.22), location=(0, -0.138, 0.118), rotation=(15, 0, 0), material=alu)
add_bevel(lid, 0.004, segments=2); apply_modifiers(lid)
panel = cube("laptop_panel", size=(0.30, 0.002, 0.19), location=(0, -0.129, 0.120), rotation=(15, 0, 0), material=screen)
hinge = cylinder("laptop_hinge", radius=0.008, depth=0.30, vertices=12, location=(0, -0.10, 0.012), rotation=(0, 90, 0), material=alu)
laptop = join([base, lid, panel, hinge], "laptop"); set_origin(laptop, "BOTTOM")
```

**飞机**（来自"汽车车身拉伸 + 机翼"）
> 朝向：机头（机鼻圆锥、座舱）朝 **+Y**，机翼略靠前（+Y），尾翼在 −Y。
```python
alu = mat("plane_body", (0.85, 0.87, 0.90), roughness=0.3, metallic=0.5)
accent = mat("plane_accent", (0.75, 0.15, 0.12), roughness=0.4)
glass = mat("plane_glass", (0.10, 0.15, 0.20), roughness=0.08)
fuselage = cylinder("fuselage", radius=0.16, depth=1.40, vertices=16, location=(0, 0, 0.28), material=alu)
rotate(fuselage, x=90); apply_transform(fuselage, rotation=True)          # 机身轴改到 Y
nose = cone("nose", radius1=0.16, radius2=0.0, depth=0.30, vertices=16, location=(0, 0.85, 0.28), material=alu)
rotate(nose, x=-90); apply_transform(nose, rotation=True)                 # 锥尖朝 +Y（机头）
wing = cube("wing", size=(1.60, 0.34, 0.05), location=(0, 0.05, 0.28), material=alu)
tailplane = cube("tailplane", size=(0.60, 0.22, 0.04), location=(0, -0.68, 0.30), material=alu)   # 尾翼在 −Y
fin = cube("fin", size=(0.04, 0.26, 0.28), location=(0, -0.68, 0.44), material=accent)             # 垂尾在 −Y
canopy = cube("canopy", size=(0.20, 0.16, 0.10), location=(0, 0.34, 0.38), material=glass)         # 座舱靠机头 +Y
gear = [sphere(f"wheel_{i}", radius=0.07, segments=12, rings=8, location=(s * 0.10, -0.05, 0.09), material=alu) for i, s in enumerate((-1, 1))]
plane = join([fuselage, nose, wing, tailplane, fin, canopy] + gear, "airplane"); set_origin(plane, "BOTTOM")
```

**路灯**（台灯 ×10 放大）
> 朝向：灯柱绕 Z 旋转对称，朝向无要求。

```python
metal = mat("lamp_metal", (0.16, 0.17, 0.18), roughness=0.35, metallic=0.9)
glow = mat("lamp_pane", (1.0, 0.88, 0.60), roughness=0.3, emission=(1.0, 0.82, 0.50), emission_strength=6.0)
base = cylinder("post_base", radius=0.16, depth=0.10, vertices=24, location=(0, 0, 0.05), material=metal)
post = cylinder("post", radius=0.045, depth=3.60, vertices=16, location=(0, 0, 1.90), material=metal)
head = cone("post_head", radius1=0.22, radius2=0.10, depth=0.26, vertices=8, location=(0, 0, 3.72), material=metal)
bulb = sphere("post_glow", radius=0.09, segments=16, rings=10, location=(0, 0, 3.58), material=glow)
lamp_post = join([base, post, head, bulb], "street_lamp"); set_origin(lamp_post, "BOTTOM")
```

### 4.4 多物体场景拼装

一个场景 = 多个配方各自 build 出对象 → 统一 `join` 或不 join（相机取景时传所有对象）。

```python
# 小场景：树 + 石头 + 小屋（各自沿用上面配方，参数略改）
tree_objs = build_tree(scale=1.0)            # 你自己封装的函数，返回对象
rock_obj  = build_rock(radius=0.4)
cabin     = build_cabin()
place(tree_objs, location=(2.5, 1.0, 0), rotation=(0, 0, 30))
place(rock_obj, location=(-1.8, 1.6, 0))
scene_objects = [tree_objs, rock_obj, cabin]
fit_camera(cam, scene_objects, margin=1.15)                  # 整组取景
```

**场景注意**：① 物体间最少留 0.2~0.3 倍自身尺寸的间距，避免穿插；② 地台已由 `setup_scene(floor=True)` 提供，物体都从 z=0 起；③ `fit_camera` 传**全部**物体，否则出画；④ 场景 > 8m 时把 `setup_scene(distance=..., elevation=30)` 拉远，或直接 `add_camera` 指定机位；⑤ 渲染分辨率 512 够自检，交付图可再开 960。

### 4.5 从零拼新题材的四步法

1. **拆**：把需求拆成"主体 + 附件 + 细节"三层的物体清单（例：微波炉 = 方盒子主体 + 门玻璃 + 旋钮 + 把手）。
2. **找**：每个部件在索引里找形状最近的配方（盒子→桌子/书架；圆柱→台灯；球→石头）。找不到精确对应就组合两个。
3. **量**：先定整体外轮廓尺寸，再按比例切分每个部件（门占正面 70%、窗占 30%……）。所有尺寸写进 `brief.md`。
4. **接**：按"主体 → 大附件 → 小细节"的顺序写代码，每写完一层跑一次 `--stage build` 看 `scene_report()` 的尺寸/对象数是否合理。

---

## 附录：常见问题（配方层面）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 布尔后挖出来的腔是封死的 | 切割体没有穿透目标面 | 让 cutter 至少高出/穿出目标 2mm，或加大 depth |
| 部件之间出现黑缝 | 两个面共面（z-fighting） | 让两件物体重叠 1~2mm，或错开 1mm |
| 倒角后模型破面 | 倒角宽度 > 板厚的一半 | 宽度 ≤ 最小壁厚 × 0.4 |
| 低模看起来像高模 | 忘了 `shade_flat`，或球分段太多 | 低段球 + flat 着色；圆柱 8~16 段 |
| 渲染图里模型很小 | 相机距离按"最大边长的 5 倍"以上设 | 用 `fit_camera(cam, [main], margin=1.2)` 自动取景 |
| join 后倒角丢了 | 倒角在 join 前的子对象上且没 apply | 先 `apply_modifiers` 再 join，或 join 后统一倒角 |
| 对称部件错位 | 左右循环用了不对称的硬编码 | 用 `for s in (-1, 1)` 乘符号，位置由 `s * 半距` 生成 |

> 维护约定：新增或修改配方时，同步更新第 1 节索引表与本文件的配方编号；改动 kit API 后，必须重跑受影响骨架的 `--stage build`。
