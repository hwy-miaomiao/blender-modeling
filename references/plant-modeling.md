# 植物建模技巧（plant-modeling）

适用：用 `blender_kit` + 无头 Blender 做低多边形/卡通/写实简化的植物与植被；本文是植物系统的**通用技巧 + 题材配方骨架**，与 `modeling-recipes.md`（单件题材 §2.10 树、§2.12 花）互补。
坐标沿用团队规范：**+Y = 正面/前，Z = 上，+X = 物体右侧**；`render_views` 的 front 相机在 +Y 侧。植物多旋转对称，但花头、果实、藤蔓方向仍按 +Y 为正面。

> 效果预览：![植物建模示例（阔叶树 / 花坛）](../docs/previews/plant.png)

---

## §1 适用范围与风格分级

| 适用 | 不适用（换方案） |
| --- | --- |
| 单棵装饰树、灌木、花坛、盆栽、草簇、藤蔓、棕榈 | 成片森林（做 3-5 变体 + 实例化，不逐棵建） |
| 场景道具级植被（远中景） | 镜头前 1 米内树皮/叶脉特写（需贴图置换，超出 kit） |
| 游戏 low-poly 资产（glb 导出） | 需骨骼摆动的植物动画（本文不含绑定） |

| 档位 | total_tris | 圆柱分段 | 球分段×环 | 着色 | 造型要点 |
| --- | --- | --- | --- | --- | --- |
| 低多边形（默认） | 500-3000 | 6-10 | 8×5 ~ 10×6 | `shade_flat` | 剪影优先、团簇拼体积 |
| 卡通/风格化 | 2000-6000 | 10-16 | 12×8 | 可 `shade_smooth` | 比例夸张、配色鲜明 |
| 写实简化 | 6000-20000 | 12-24 | 16×10 ~ 20×12 | 混合 | 叶卡片成组、枝干更密 |

共同约束：对象数 3-20、低模 `total_tris < 3000`（超了在 brief.md 说明）、材质必须给**线性 Base Color**（§6）。单件用深色地台突出主体；小场景（3-8 件）统一 `setup_scene(target=(0,0,1.0), distance=7)`，总面数控制 2500 内。

---

## §2 结构拆解模板

植物再复杂都拆四层：先剪影、后骨架、再枝叶、最后细节/环境。

| 层 | 内容 | 低模做法 |
| --- | --- | --- |
| ① 主干骨架层 | 树干、主枝、花茎、藤蔓主干 | `cone`/`cylinder` 递归或 `tube` 折线，剪影的骨架 |
| ② 枝叶层 | 树冠团簇、针叶层、棕榈羽叶、叶卡片、草叶 | 重叠 `sphere` 团簇 / 分层 `cone` / 压扁球叶 |
| ③ 花与果实层 | 花瓣环、花心、果实小球 | 小分段球环阵 + `set_origin(CENTER)` 后再旋转 |
| ④ 环境层 | 地台、土面、碎石、草丛、花器 | `setup_floor` 深色地台；`cube` 花器 + 土面 |

拆解五步：**剪影**（远看是球冠/锥形/伞形/扇形）→ **骨架**（按 §3 定主干高、干径、分枝起点，主干比枝粗 2-4 倍）→ **枝叶**（冠 5-9 球 / 针叶 3-6 层 / 草本叶卡片）→ **细节**（花、果、草簇）→ **环境**（地台、花器、收边草）。

9 列部件表模板（两行为填表示例，颜色见 §6）：

| 部件 | 图元 | 尺寸/参数 | 位置（米） | 旋转 | 材质 | 修改器 | 分段数 | 归属层 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 树干 | cone | r1 0.24→r2 0.13，h 1.9 | (0,0,0.95) | — | tree_bark | — | vertices 10 | ① |
| 树冠 | sphere | r 0.56-0.90，squash 0.92 | 围绕 (0,0,2.54) | 随机微扰 | 三色叶材质 | — | 8×5 | ② |

---

## §3 比例与尺寸参考表（单位：米）

「常识」为园林常见量级（取整便于建模），「实测」为本文 `report.json` 真实输出。

| # | 题材 | 常见尺寸 | 来源 |
| --- | --- | --- | --- |
| 1 | 小乔木/行道树 | 高 4-8，冠幅 3-5，主干高 1.8-2.6 | 常识 |
| 2 | 庭荫大树 | 高 8-15，冠幅 6-10，胸径 0.3-0.6 | 常识 |
| 3 | 树冠占比 | 冠高/树高 ≈ 0.5-0.7（低模可 0.7-0.8） | 常识 |
| 4 | 分枝起点 | 主干高 ≈ 树高 25%-40% | 常识 |
| 5 | 灌木 / 绿篱 | 高 0.8-2.0 / 0.5-1.2，宽 0.4-2.0 | 常识 |
| 6 | 草本花株 | 高 0.2-0.8，花头直径 0.05-0.15 | 常识 |
| 7 | 叶片 | 长 0.03-0.12，宽为长 40%-60%（低模可放大 1.5-2 倍） | 常识 |
| 8 | 花坛/花箱 | 长 0.6-1.2，宽 0.3-0.5，高 0.25-0.45 | 常识 |
| 9 | 小型盆栽 | 整体高 0.15-0.4，盆高 0.08-0.2 | 常识 |
| 10 | 棕榈 | 高 8-15，干径 0.25-0.35，羽叶长 2-4 | 常识 |
| 11 | 针叶树 | 高 10-20，冠幅 3-6，层间距 1-2 | 常识 |
| 12 | 草丛 / 藤蔓 | 叶高 0.05-0.2 / 攀爬高 2-5，缠绕半径 0.05-0.15 | 常识 |
| 13 | 实测：阔叶树 | 高 3.99，冠幅 2.32×2.26，干底径 0.48 | 实测 |
| 14 | 实测：花坛 | 0.820×0.444×0.695，花株高 0.26-0.36 | 实测 |

低模植物尺寸可比真实值夸张 20%-50%（叶、花、树干加粗），否则远看会「消失」。

---

## §4 技巧库（8 个）

### 4.1 递归分枝（cylinder + 方向瞄准）
**适用**：阔叶树主枝、藤蔓分叉。**做法**：用「本地 +Z 对准方向」的欧拉角，从树干顶递归长圆柱。
```python
import math
from blender_kit import cylinder, mat, place
def aim(d):                        # 圆柱本地 +Z 对准方向 d 的欧拉角（度）
    n = math.sqrt(sum(v * v for v in d)); dx, dy, dz = (v / n for v in d)
    return (math.degrees(math.acos(dz)), 0.0, math.degrees(math.atan2(dx, -dy)))
seg = cylinder("branch_00", radius=0.08, depth=0.80, vertices=6,
               location=(0.0, 0.0, 2.30),
               material=mat("bark", color=(0.16, 0.10, 0.06), roughness=0.92))
place(seg, rotation=aim((0.55, 0.10, 1.0)))    # 参数 = 生长方向
```
参数：层数 2-3、每级 2 叉；`length_decay` 0.60-0.75、`radius_decay` 0.55-0.70、`spread` 0.40-0.70。坑：枝梢会戳出树冠（像天线）→ 缩短枝长或加大冠团；`radius_decay` 太大会变「等粗树枝」。

### 4.2 树冠几何簇（重叠球）
**适用**：阔叶树、灌木、大冠幅树。**做法**：围绕冠心放 5-9 球，相邻球中心距 < 半径和的 70%，压扁 Z、两色交替。
```python
from blender_kit import mat, scale_obj, shade_flat, sphere
leaf_a = mat("leaf_dark", color=(0.05, 0.17, 0.06), roughness=0.78)
leaf_b = mat("leaf_mid", color=(0.08, 0.24, 0.08), roughness=0.75)
lobes = ((0.00, 0.00, 0.66, 0.90), (0.55, 0.10, 0.44, 0.68), (-0.50, 0.16, 0.42, 0.66),
         (0.10, -0.55, 0.40, 0.64), (-0.08, 0.50, 0.46, 0.62))   # (dx, dy, dz, 半径)
for i, (dx, dy, dz, r) in enumerate(lobes):
    c = sphere("crown_%02d" % i, radius=r, segments=8, rings=5,
               location=(dx, dy, 2.54 + dz), material=(leaf_a, leaf_b)[i % 2])
    scale_obj(c, (1.02, 1.02, 0.92))           # 冠压扁更自然
    shade_flat(c)                              # 低模保留面块
```
参数：团簇 5-9；半径 0.5-0.9 × 冠半径；`squash_z` 0.80-0.95。坑：只把球挂枝梢 → 「一束气球」/「蘑菇盖」；必须有围绕冠心的填充团簇（本文实测第 2 版原样踩坑）。

### 4.3 棕榈（弯曲干 + 羽叶阵列）
**适用**：热带场景。**做法**：`tube` 折线做微弯干，顶端绕一圈 `plane` 羽叶、叶尖下垂 20°-45°。
```python
import math
from blender_kit import mat, plane, place, scale_obj, tube
top = (0.26, 0.04, 4.0)
tube("palm_trunk", [(0.0, 0.0, 0.0), (0.08, 0.0, 1.4), (0.18, 0.02, 2.8), top],
     radius=0.16, resolution=8, material=mat("palm_bark", color=(0.18, 0.12, 0.07), roughness=0.90))
leaf = mat("palm_leaf", color=(0.06, 0.20, 0.06), roughness=0.70)
for i in range(10):
    a = 2.0 * math.pi * i / 10
    frond = plane("palm_frond_%02d" % i, size=1.5, material=leaf,
                  location=(top[0] + 0.12 * math.cos(a), top[1] + 0.12 * math.sin(a), top[2] + 0.05))
    scale_obj(frond, (1.0, 0.20, 1.0))
    place(frond, rotation=(-28.0, 0.0, math.degrees(a)))
```
参数：干高 4-8（低模可缩）、弯曲 0.1-0.3；叶 8-14 片；叶长 ≈ 0.25-0.35 × 干高；俯仰 -20°~-45°。坑：叶根都在同一点像折扇 → 叶根在冠顶 ±0.12 m 抖动；`tube` 半径均匀不能锥化，要锥形干就拆 3-4 段 `cone`。

### 4.4 叶卡片 vs 压扁球叶
**适用**：灌木、草本、阔叶树近景。**做法**：薄叶用 `plane` + `add_solidify`；圆润低模叶用压扁球。
```python
from blender_kit import add_solidify, apply_modifiers, mat, plane, scale_obj, sphere
leaf = mat("leaf", color=(0.06, 0.20, 0.06), roughness=0.70)
card = plane("leaf_card", size=0.12, location=(0.35, 0.0, 1.6), material=leaf)
scale_obj(card, (1.0, 0.55, 1.0))
add_solidify(card, thickness=0.002); apply_modifiers(card)   # 双面，背面看不是黑洞
blob = sphere("leaf_blob", radius=0.040, segments=6, rings=4,
              location=(-0.35, 0.0, 1.6), material=leaf)
scale_obj(blob, (1.7, 0.7, 0.14))              # 压扁球 = 圆润低模叶
```
参数：叶长 3%-8% 树高；卡片厚 0.001-0.004；压扁球 scale ≈ (1.5-1.9, 0.6-0.8, 0.10-0.18)。坑：`plane` 单面背面黑洞 → 必须 solidify；斜视角下卡片像「悬浮纸片」→ 改压扁球（本文花坛第 2 版教训）。

### 4.5 花（花瓣环 + 前倾）
**适用**：花坛、盆栽、草本。**做法**：花瓣绕局部 Z 环形排一圈 → `join` → `set_origin(CENTER)` → 整体朝 +Y 前倾 → 平移。
```python
import math
from blender_kit import join, mat, place, rotate, scale_obj, set_origin, sphere, translate
petal = mat("petal", color=(0.42, 0.025, 0.018), roughness=0.58)
parts = []
for i in range(6):
    a = 2.0 * math.pi * i / 6
    p = sphere("petal_%02d" % i, radius=0.028, segments=6, rings=4, material=petal,
               location=(0.044 * math.cos(a), 0.044 * math.sin(a), 0.0))
    scale_obj(p, (1.30, 0.72, 0.30))           # 压成薄花瓣
    place(p, rotation=(0.0, 0.0, math.degrees(a)))
    parts.append(p)
parts.append(sphere("core", radius=0.020, segments=6, rings=4, material=mat("core", color=(0.62, 0.40, 0.03), roughness=0.55), location=(0, 0, 0.004)))
head = join(parts, "flower_head"); set_origin(head, "CENTER")   # 原点组装后把原点到花心
rotate(head, x=-32.0); translate(head, (0.0, 0.0, 0.30))   # 朝 +Y 前倾并装到花茎顶端
```
参数：花瓣 5-8 片；瓣长 0.02-0.06；花头半径 0.04-0.08；前倾 20°-40°；再叠 ±35° 方位角随机避免整排同向。坑：不 `set_origin(CENTER)` 直接 `rotate` → 绕第一片花瓣转、花头飞出去；花头水平朝上 → front 图只看到侧面像蘑菇。

### 4.6 草簇
**适用**：地被、花坛收边、树根周围。**做法**：每簇 3-7 根小 `cone`，随机倾斜 5°-30°。
```python
import math
import random
from blender_kit import cone, mat, place
grass = mat("grass", color=(0.07, 0.20, 0.05), roughness=0.75)
for t in range(10):                            # 10 簇
    a = 2.0 * math.pi * t / 10; cx, cy = 0.36 * math.cos(a), 0.20 * math.sin(a)
    for b in range(4):
        h = random.uniform(0.09, 0.17)
        blade = cone("blade_%02d_%d" % (t, b), radius1=0.007, radius2=0.0,
                     depth=h, vertices=4, material=grass,
                     location=(cx + random.uniform(-0.03, 0.03),
                               cy + random.uniform(-0.02, 0.02), h * 0.5))
        place(blade, rotation=(random.uniform(8.0, 26.0), 0.0, random.uniform(0.0, 360.0)))
```
参数：每簇 3-7 根；叶高 0.05-0.2；倾斜 5°-30°；簇间距 = 1-2 × 簇半径。坑：草根离地 → 叶高从 z=0 起算；整体 `set_origin(BOTTOM)` 压到地面。

### 4.7 季节配色
**适用**：同一套模型换季。**做法**：线性三色叶材质 + 调色板字典，按季节换材质名。
```python
from blender_kit import mat
PALETTES = {"spring": ((0.06, 0.18, 0.05), (0.10, 0.26, 0.08), (0.16, 0.36, 0.12)),
            "autumn": ((0.22, 0.07, 0.02), (0.38, 0.16, 0.03), (0.52, 0.30, 0.05))}
season = "autumn"
dark, mid, light = PALETTES[season]
mat("leaf_dark_%s" % season, color=dark, roughness=0.78)
mat("leaf_mid_%s" % season, color=mid, roughness=0.74)
```
参数：秋色橙黄线性 (0.22-0.52, 0.07-0.30, 0.02-0.05)；枯枝褐 (0.10, 0.06, 0.03)。坑：`mat()` 同名返回缓存且不再改参数 → 换季必须换材质名；sRGB 直觉值直接当线性用会发白（§6）。

### 4.8 地面融合与面数核对
**适用**：所有站在地面的植物。**做法**：深色地台 + 接触阴影 + 草簇遮交界；`join` 成 1 mesh 后核对面数。
```python
from blender_kit import join, scene_report, set_origin, setup_floor, setup_scene
setup_scene(target=(0, 0, 0.4), distance=4.0, lens=50, elevation=26, floor=False)
setup_floor(size=8.0, color=(0.055, 0.06, 0.065), roughness=0.7)   # 深色衬主体
plant = join(build_plant(), "plant")
set_origin(plant, "BOTTOM")                    # bbox 底对齐 z=0，别浮空
rep = scene_report(); print("[budget] tris=%d objs=%d" % (rep["total_tris"], rep["object_count"]))
```
参数：地台色 (0.04-0.07) 深灰 / (0.05,0.08,0.04) 草地绿；粗糙 0.7-0.9；尺寸 ≈ 2-3 × 主体宽。坑：默认 20 m 浅灰地台会洗白浅色植物 → `floor=False` + 自定义深色地台；主体浮空先查 `bbox_min.z`。

---

## §5 代表题材配方骨架

每个骨架都是 `build()` 风格，可直接接模板的 build → render → export 流程。难度：★ 初级、★★ 中级、★★★ 需递归/阵列。

### 5.1 阔叶树 ★★（本文实测：624 tris / 3.99 m 高）
```python
import math
import random
from blender_kit import (cone, cylinder, join, mat, place, scale_obj, set_origin,
                         setup_scene, shade_flat, sphere)
def build():
    setup_scene(target=(0, 0, 2.2), distance=7.0, lens=50, elevation=20)
    rng = random.Random(7)
    wood = mat("tree_bark", color=(0.16, 0.10, 0.06), roughness=0.92)
    leaves = [mat("tree_leaf_dark", color=(0.05, 0.17, 0.06), roughness=0.78),
              mat("tree_leaf_mid", color=(0.08, 0.24, 0.08), roughness=0.75)]
    objs = [cone("tree_trunk", radius1=0.24, radius2=0.13, depth=1.9, vertices=10,
                 location=(0, 0, 0.95), material=wood)]
    def grow(start, d, length, radius, depth):     # 递归长分枝，d = 生长方向
        n = math.sqrt(sum(v * v for v in d))
        d = tuple(v / n for v in d)
        mid = tuple(start[i] + d[i] * length * 0.5 for i in range(3))
        seg = cylinder("branch_%02d" % len(objs), radius=radius, depth=length,
                       vertices=6, location=mid, material=wood)
        place(seg, rotation=(math.degrees(math.acos(d[2])), 0.0,
                             math.degrees(math.atan2(d[0], -d[1]))))
        objs.append(seg)
        if depth <= 0:
            return
        tip = tuple(start[i] + d[i] * length for i in range(3))
        for _ in range(2):
            a, s = rng.uniform(0.0, 2 * math.pi), 0.55 * rng.uniform(0.7, 1.25)
            grow(tip, (d[0] + s * math.cos(a), d[1] + s * math.sin(a), d[2] + 0.45),
                 length * 0.68, radius * 0.62, depth - 1)
    grow((0, 0, 1.9), (0, 0, 1.0), 0.80, 0.080, 2)
    lobes = ((0.00, 0.00, 0.66, 0.90), (0.55, 0.10, 0.44, 0.68),
             (-0.50, 0.16, 0.42, 0.66), (0.10, -0.55, 0.40, 0.64),
             (-0.08, 0.50, 0.46, 0.62), (0.34, 0.28, 0.20, 0.56),
             (-0.32, -0.24, 0.22, 0.56))
    for i, (dx, dy, dz, r) in enumerate(lobes):
        c = sphere("crown_%02d" % i, radius=r * rng.uniform(0.92, 1.08), segments=8,
                   rings=5, location=(dx, dy, 2.54 + dz), material=leaves[i % 2])
        scale_obj(c, (1.02, 1.02, 0.92))
        shade_flat(c)
        objs.append(c)
    tree = join(objs, "broadleaf_tree")
    set_origin(tree, "BOTTOM")
    return [tree]
```
关键比例：树干 1.9 m、冠心 2.54 m、冠幅约 2.3 m；分枝 2-3 级就够，枝梢必须被冠罩住。变体：`scale` 1.3 → 5 m 树；`lobes` 半径 ×0.6、枝长 ×0.5 → 灌木。

### 5.2 针叶树 ★★（分层锥体，约 900 tris）
```python
from blender_kit import cone, join, mat, set_origin, setup_scene, shade_flat
def build():
    setup_scene(target=(0, 0, 2.4), distance=8.0, lens=50, elevation=18)
    bark = mat("conifer_bark", color=(0.12, 0.08, 0.05), roughness=0.92)
    needle = mat("conifer_needle", color=(0.03, 0.12, 0.05), roughness=0.85)
    objs = [cone("conifer_trunk", radius1=0.16, radius2=0.10, depth=4.2,
                 vertices=8, location=(0, 0, 2.1), material=bark)]
    for i in range(5):
        layer = cone("conifer_layer_%d" % i, radius1=1.30 * 0.70 ** i, radius2=0.0,
                     depth=1.30 * 0.84 ** i, vertices=10, material=needle,
                     location=(0, 0, 0.90 + i * 0.72))
        shade_flat(layer)
        objs.append(layer)
    tree = join(objs, "conifer_tree")
    set_origin(tree, "BOTTOM")
    return [tree]
```
顶锥要盖住树干顶，层间重叠 40%；层数 3 → 小盆栽圣诞树，`radius1` ×1.4 → 雪松。

### 5.3 灌木丛 ★（团簇 + 多株）
```python
import random
from blender_kit import join, mat, scale_obj, set_origin, setup_scene, shade_flat, sphere
def build():
    setup_scene(target=(0, 0, 0.5), distance=5.0, lens=50, elevation=24)
    leaf = mat("bush_leaf", color=(0.06, 0.19, 0.06), roughness=0.75)
    rng = random.Random(3)
    objs = []
    for i, (x, y, r) in enumerate(((0.0, 0.0, 0.60), (0.45, 0.10, 0.42),
                                   (-0.35, 0.20, 0.46), (0.10, -0.42, 0.40))):
        blob = sphere("bush_%02d" % i, radius=r, segments=8, rings=5,
                      location=(x, y, 0.35 + r * 0.55), material=leaf)
        scale_obj(blob, (1.15, 1.05, 0.85))
        shade_flat(blob)
        objs.append(blob)
    for i in range(3):                          # 再散 3 丛小球做灌木带
        objs.append(sphere("bush_s_%d" % i, radius=rng.uniform(0.25, 0.35),
                           segments=8, rings=5, material=leaf,
                           location=(rng.uniform(-0.9, 0.9), rng.uniform(-0.9, 0.9), 0.30)))
    bush = join(objs, "bush_cluster")
    set_origin(bush, "BOTTOM")
    return [bush]
```
3-6 团成丛、同丛球重叠 50%；复制 2-3 份错位摆放即成灌木带。

### 5.4 花坛 / 盆栽 ★★（本文实测：3558 tris / 0.82×0.44×0.70 m）
```python
import math
from blender_kit import (add_bevel, cone, cube, join, mat, place, rotate, scale_obj,
                         set_origin, setup_floor, setup_scene, sphere, translate)
def build():
    setup_scene(target=(0, 0, 0.42), distance=4.0, lens=50, elevation=26, floor=False)
    setup_floor(size=8.0, color=(0.055, 0.06, 0.065), roughness=0.7)
    pot = cube("planter", size=(0.82, 0.42, 0.30), location=(0, 0, 0.15),
               material=mat("planter_wood", color=(0.09, 0.045, 0.022), roughness=0.88))
    add_bevel(pot, width=0.010, segments=2)
    objs = [pot, cube("soil", size=(0.73, 0.33, 0.05), location=(0, 0, 0.277),
                      material=mat("soil", color=(0.015, 0.012, 0.008), roughness=1.0))]
    stem_mat = mat("stem", color=(0.035, 0.13, 0.035), roughness=0.72)
    petal = mat("petal_red", color=(0.42, 0.025, 0.018), roughness=0.58)
    core = mat("flower_core", color=(0.62, 0.40, 0.03), roughness=0.55)
    for i in range(9):                          # 3×3 花株
        x, y = ((i % 3) - 1) * 0.23, ((i // 3) - 1) * 0.115
        h = 0.26 + 0.10 * ((i * 7) % 5) / 4.0
        stem = cone("stem_%02d" % i, radius1=0.008, radius2=0.006, depth=h,
                    vertices=5, location=(x, y, 0.30 + h * 0.5), material=stem_mat)
        parts = []
        for p in range(6):                      # 花瓣环
            a = 2.0 * math.pi * p / 6
            pet = sphere("petal_%02d_%d" % (i, p), radius=0.028, segments=6, rings=4,
                         material=petal,
                         location=(0.044 * math.cos(a), 0.044 * math.sin(a), 0.0))
            scale_obj(pet, (1.30, 0.72, 0.30))
            place(pet, rotation=(0.0, 0.0, math.degrees(a)))
            parts.append(pet)
        parts.append(sphere("core_%02d" % i, radius=0.020, segments=6, rings=4,
                            location=(0, 0, 0.004), material=core))
        head = join(parts, "head_%02d" % i)
        set_origin(head, "CENTER")
        rotate(head, x=-30.0)
        translate(head, (x, y, 0.30 + h))
        objs += [stem, head]
    bed = join(objs, "flower_bed")
    set_origin(bed, "BOTTOM")
    return [bed]
```
花头「原点组装 → set_origin(CENTER) → rotate → translate」顺序不能颠倒；叶片可参考 §4.4 压扁球另加；压面数：花瓣 6×4 → 5×3，或 9 株 → 6 株。

---

## §6 材质与配色

### 6.1 必须给线性 Base Color

`mat()` 的 `color` 是**线性空间** RGB；按 sRGB 直觉给值会整体发白，需压暗 30%-50%：

| 想要的观感（sRGB 直觉） | 直接给（错，发白） | 线性值（对） |
| --- | --- | --- |
| 深绿树叶 | (0.2, 0.6, 0.2) | (0.05, 0.17, 0.06) |
| 中绿树叶 | (0.35, 0.75, 0.3) | (0.08, 0.24, 0.08) |
| 棕色树皮 | (0.5, 0.3, 0.15) | (0.16, 0.10, 0.06) |
| 深棕木箱 | (0.45, 0.25, 0.15) | (0.09, 0.045, 0.022) |
| 近黑泥土 | (0.25, 0.2, 0.15) | (0.015, 0.012, 0.008) |
| 红花花瓣 | (0.75, 0.15, 0.1) | (0.42, 0.025, 0.018) |
| 黄花花瓣 | (0.9, 0.7, 0.2) | (0.70, 0.32, 0.02) |

规律：中高亮度 ≈ sRGB 值²·² 再乘 0.6-0.8；暗部（<0.2）直接除以 3-5。粗糙度：叶片/花瓣 0.55-0.75、树皮/木器 0.85-0.95、泥土 0.95-1.0、果实 0.25-0.45、金属 0.3-0.4 + metallic 0.7-0.9。

### 6.2 四套配色板（线性 RGB）

| 配色板 | 深 | 中 | 亮 | 适用 |
| --- | --- | --- | --- | --- |
| 春夏绿 | (0.05, 0.17, 0.06) | (0.08, 0.24, 0.08) | (0.12, 0.32, 0.11) | 阔叶/灌木/草 |
| 秋色 | (0.22, 0.07, 0.02) | (0.38, 0.16, 0.03) | (0.52, 0.30, 0.05) | 秋叶树 |
| 针叶/热带 | (0.03, 0.12, 0.05) | (0.05, 0.18, 0.05) | (0.08, 0.24, 0.07) | 松柏、棕榈 |
| 多肉/沙漠 | (0.10, 0.14, 0.10) | (0.16, 0.22, 0.16) | (0.24, 0.30, 0.22) | 多肉、岩生 |

---

## §7 灯光 / 相机 / 构图

- **灯**：`setup_scene` 自动调三灯（Key/Fill/Rim）；植物多哑光，不要额外加灯，加灯会过曝。
- **distance / elevation**：小盆栽 2.4-3.5、花坛 4-5、灌木 5-6、单树 7-10；elevation 树 18-25、花坛/盆栽 25-32、地被 30-40（`distance` 同时决定三灯半径 `max(distance*0.8, 1.0)`，拉太近会过曝）。
- **构图**：`render_views` 固定 `margin=1.15` 自动取景；实测**树占画面高 55%-70%、扁平花坛 55%-65%**，留白正常，别为「占满画面」反复调相机。
- **落地感与穿地**：地台与主体间的软阴影是「落地感」主要来源，不要关 `floor`；建完 `set_origin(obj, "BOTTOM")` 核对 `report.dimensions`/`bbox_min` 的 z≈0；自建地台/离群道具会被算进 bbox 导致取景异常（改用 `setup_floor`）。

---

## §8 常见错误与排查（真实报错 / 真实症状）

| # | 报错原文 / 症状 | 原因 | 修法 |
| --- | --- | --- | --- |
| 1 | `ModuleNotFoundError: No module named 'blender_kit'` | 直接用 `python model.py` 或 `blender -b --python model.py` 跑，未注入 `BLENDER_KIT_DIR` | 一律用 `python scripts\run_blender.py --script ... --out ... --stage ...` |
| 2 | `NameError: name 'save_report' is not defined. Did you mean: 'scene_report'?` | 清理 `from blender_kit import ...` 时删掉了 `save_report`，full 阶段才用到 | 补回导入；full 前先 `--stage build` 快检 |
| 3 | `Error: script failed, file: '<model.py>', exiting.` | Blender `--python-exit-code 1` 把异常转成退出码，真因在日志 | 查 `<out>/logs/<label>-*.log` 的**第一个** `Traceback` |
| 4 | `[ERROR] 缺少或为空: <out>\brief.md` | 只跑 full 生成渲染/导出，没写交付必需的 brief.md | 按 10 小节模板补 `brief.md` 后重跑 `check_output.py` |
| 5 | 布尔挖盆后内腔材质串色，`material_index` 出现 `414629464` | 布尔 cutter 无材质，新面材质索引越界 | cutter 建件时传同一材质：`cylinder(..., material=ceramic)` |
| 6 | 花头/叶片旋转后「飞出去」 | 先 `rotate` 再 `set_origin`，绕第一片花瓣转 | 先 `set_origin(CENTER)` → `rotate` → `translate` |
| 7 | 渲染整体发白、花瓣看不出颜色 | sRGB 直觉色当线性用（如树叶给 (0.2,0.6,0.2)） | 按 §6.1 压暗 30%-50%；深色地台拉对比 |

---

## §9 验收自检清单

通用 12 项照 AGENTS.md；植物类再加 6 项：

- [ ] 剪影可辨物种：远看能区分树/灌木/草本/棕榈，不是一团绿球。
- [ ] 分枝自然：主枝比侧枝粗 1.5-2.5 倍；枝梢不戳出树冠（除非刻意枯枝）。
- [ ] 树冠无破洞：团簇重叠、无透视穿帮，冠内看不到穿过冠面的枝。
- [ ] 无穿地/穿模：`bbox_min.z ≈ 0`；花头不与叶片/邻株重叠；草不插进花器壁。
- [ ] 冠幅/高比合理：树冠宽/总高 ≈ 0.5-1.0（低模 0.6-0.9）。
- [ ] 朝向可用：花头/果实朝 +Y 前倾，front 图能看到正面特征；季相配色统一；`total_tris` 在预算内。

---

## §10 实测记录表

### 10.1 实跑数据（Blender 4.0.2，`report.json` 真实输出）

| 题材 | 命令 | 耗时 | objects | mesh | tris | dimensions（米） | check_output | read_image 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 阔叶树 broadleaf-tree | `--stage full` | 33.7 s | 6 | 1 | 624 | 2.315 × 2.257 × 3.993 | 27 PASS / 0 ERROR | 树冠连片、枝梢不外露、投影落地 |
| 花坛 flower-bed | `--stage full` | 203.2 s | 6 | 1 | 3558 | 0.820 × 0.444 × 0.695 | 27 PASS / 0 ERROR | 花头三视角可见、叶片贴茎、分色清楚 |

花坛 full 明显更慢：9 株 × 6 瓣的小几何让 960×960/32 samples 的采样与降噪变慢；要压时间把 final 降到 800×800/24 samples。

### 10.2 迭代记录（read_image 真看后的修正）

| 题材 | 轮次 | 看到的问题 | 修正 | 结果 |
| --- | --- | --- | --- | --- |
| 阔叶树 | v1-v2 | 树冠偏稀像气球；只挂枝梢 → 冠扁平像蘑菇 | 冠心补填充团簇，放弃「只挂枝梢」方案 | 变密但仍分层 |
| 阔叶树 | v3-v4 | 上下两层冠有缝；枝梢戳出冠顶像天线 | 团簇增多 + 枝长 1.05→0.80、递归 3→2 级 | 连成一片、枝被冠罩住 |
| 阔叶树 | v5 | — | 冠心抬高、squash 0.92 | **采用，full 通过** |
| 花坛 | v1 | 花器/土发白、叶片像绿纸片、花头朝上像蘑菇 | 线性色压暗、叶片改朝向、花头前倾 | 色调正常 |
| 花坛 | v2-v3 | 叶片像斜插纸片、花头全部同向、right 侧对镜头像一排盘子 | 叶片改压扁球；花头 `rotate(x=head_tilt±8)` + `rotate(z=±35°)` | 三视角都能看到花盘 |
| 花坛 | full | `NameError: name 'save_report' is not defined` | 补回 import 重跑 | 通过（§8 错误 2） |

### 10.3 证据位置（临时目录，不入库）

- 阔叶树：`.tmp\domain\plant\broadleaf-tree\`（model.py / brief.md / report.json / renders / exports / logs，相对 <工作区>）；花坛：`.tmp\domain\plant\flower-bed\`
- 渲染图：`renders/view-{front,right,iso}.png`（512）与 `renders/final-{front,right,iso}.png`（960）；复跑 `python scripts\run_blender.py --script "<目录>\model.py" --out "<目录>" --stage full` → `python scripts\check_output.py --out "<目录>"`

---

## 附录 A：命令速查

```powershell
cd "<技能目录>"
$OUT = "<输出目录>"
python scripts\run_blender.py --script "$OUT\model.py" --out "$OUT" --stage build    # 1-2 s 快检
python scripts\run_blender.py --script "$OUT\model.py" --out "$OUT" --stage render   # 预览 512
python scripts\run_blender.py --script "$OUT\model.py" --out "$OUT" --stage full     # 终渲+导出
python scripts\check_output.py --out "$OUT"                                          # 交付闸门
```
