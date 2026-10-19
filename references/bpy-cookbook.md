# bpy 实测速查 — Blender 4.0.2（Windows / headless）

> **适用范围**：本机实测环境 `C:\Program Files\Blender Foundation\Blender 4.0\blender.exe`，`bpy.app.version_string == "4.0.2"`，Windows，无头模式 `blender.exe -b`。
> **写作原则**：本文只收录**在本机亲自跑通**的 API 与参数；每段代码都可以直接粘贴进 `bpy` 脚本。行为随版本变化，换机器/换版本时先跑第 15 节的自检。
> **优先用 kit**：`blender-modeling/lib/blender_kit.py` 已经把下列多数操作封装成带中文 docstring 的函数（场景、图元、修改器、材质、渲染、导出、报告），kit 缺能力时再回退到本文的裸 bpy 写法。kit 与 bpy 的对应关系见第 14 节。

---

## 1. 最小闭环：空场景 → 物体 → 相机 → 渲染 → 导出

把下面整段存成 `smoke.py`，用第 2 节命令跑；产物在脚本同目录 `_smoke/`。

```python
# -*- coding: utf-8 -*-
"""最小闭环：空场景 → 立方体 → 材质 → 灯光 → 相机 → 渲染 → 导出。"""
import math
import os

import bpy
from mathutils import Vector

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_smoke")
os.makedirs(OUT, exist_ok=True)

# 1) 清空为"空场景"（无默认物体、无默认材质；world 可能为空，见第 9 节）
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# 2) 物体（默认落在原点，size=1.0 表示边长 1 米）
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.5))
cube = bpy.context.object
cube.name = "smoke_cube"

# 3) 材质（Principled BSDF，输入名见第 7 节）
m = bpy.data.materials.new("smoke_gray")
m.use_nodes = True
bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
bsdf.inputs['Base Color'].default_value = (0.75, 0.75, 0.78, 1.0)
bsdf.inputs['Roughness'].default_value = 0.45
cube.data.materials.append(m)

# 4) 世界背景（空场景里 scene.world 可能为 None，必须新建并赋给 scene）
world = bpy.data.worlds.new("smoke_world")
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
bg.inputs['Color'].default_value = (0.05, 0.05, 0.06, 1.0)
bg.inputs['Strength'].default_value = 0.6
scene.world = world

# 5) 灯光（AREA，能量单位是瓦特 W）
bpy.ops.object.light_add(type='AREA', location=(3.0, -3.0, 4.0))
key = bpy.context.object
key.data.energy = 300.0
key.data.size = 3.0

# 6) 相机 + 朝向：用 -Z 指向目标（to_track_quat）
bpy.ops.object.camera_add(location=(3.2, -3.2, 2.2))
cam = bpy.context.object
cam.data.lens = 50.0
d = Vector((0.0, 0.0, 0.5)) - cam.location
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam
bpy.context.view_layer.update()   # 读 matrix_world 前必须刷新

# 7) 渲染设置
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.cycles.denoiser = 'OPENIMAGEDENOISE'
scene.render.resolution_x = 512
scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'AgX - Medium High Contrast'
scene.render.filepath = os.path.join(OUT, "smoke.png")
bpy.ops.render.render(write_still=True)

# 8) 导出
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "smoke.blend"), check_existing=False)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "smoke.glb"),
                          export_format='GLB', export_apply=True)
bpy.ops.wm.obj_export(filepath=os.path.join(OUT, "smoke.obj"),
                      export_selected_objects=False, apply_modifiers=True)

print("SMOKE_OK", os.path.getsize(os.path.join(OUT, "smoke.png")),
      os.path.getsize(os.path.join(OUT, "smoke.blend")))
```

---

## 2. 运行方式与退出码

```powershell
# 在 PowerShell 里跑；路径含空格必须加引号
& "C:\Program Files\Blender Foundation\Blender 4.0\blender.exe" -b --factory-startup -noaudio `
  --python-exit-code 1 --python "F:\path\to\smoke.py" 1>out.log 2>err.log
$LASTEXITCODE    # 0 = 成功；非 0 = 失败（脚本抛异常 / sys.exit(1)）
```

要点（全部实测）：

| 参数 | 作用 |
| --- | --- |
| `-b` | 无头后台模式，不打开界面 |
| `--factory-startup` | 忽略用户配置与已安装插件状态，保证可复现 |
| `-noaudio` | 不初始化音频设备（无头环境避免报错） |
| `--python-exit-code 1` | 脚本里**未捕获异常**时进程退出码为 1（否则 Blender 可能仍返回 0） |
| `--python <文件>` | 要执行的脚本 |
| `--python-expr "<code>"` | 直接执行一小段表达式（适合一行探针） |

- 脚本参数透传：命令行的 `--` 之后的内容出现在 `sys.argv` 里，例如 `... --python s.py -- --samples 8`，脚本里用 `sys.argv[sys.argv.index("--") + 1:]` 读取（kit 的 `script_args()` 已封装）。
- **stderr 噪音**：`TBBmalloc: skip allocation functions replacement ... unknown prologue` 是无害信息，不是错误；判断成败只看退出码与 stdout 里的异常。
- 渲染/导出日志会出现在 stdout/stderr，`--factory-startup` 下 Cycles、glTF、FBX、STL 插件都已启用，无需手动 `addon_enable`。

---

## 3. 场景与对象管理

### 3.1 重置为空场景

```python
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
print(len(bpy.data.objects))          # 0（实测）
scene = bpy.context.scene
print(scene.name)                     # "Scene"
print(bpy.app.version_string)         # "4.0.2"
```

- `use_empty=True` 清掉默认立方体/灯光/相机；**实测之后 `scene.world is None`、`bpy.data.worlds` 为空**，需要背景时自己新建 world 并赋值（见第 9 节）。
- 一个脚本里只应在开头调用一次；中途调用会丢弃已建好的全部数据（包括材质缓存）。
- kit 的 `reset_scene()` 在此基础上还清了内部的渲染/导出统计状态。

### 3.2 手动新建对象并挂到场景

```python
import bpy
me = bpy.data.meshes.new("custom_mesh")
obj = bpy.data.objects.new("custom_obj", me)
bpy.context.scene.collection.objects.link(obj)
```

- 用 `bpy.data.*.new()` 创建的数据不会自动出现在场景里，必须 `collection.objects.link(obj)`；`bpy.ops.*_add()` 创建的会自动链接并成为 `bpy.context.object`（active object）。
- 同一份 mesh 数据可以被多个 object 共享（`bpy.data.objects.new(name, same_mesh)`），改 mesh 几何会同时影响它们；要独立几何用 `obj.data.copy()`。

### 3.3 选择 / active object（操作符的前置条件）

`bpy.ops.object.*` 与 `bpy.ops.mesh.*` 大多依赖"选中 + active"上下文：

```python
def activate(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.context.view_layer.update()
```

实测坑：`bpy.ops.object.transform_apply(...)` 在**没有选中对象**时会静默返回、不报异常（本机实测不抛错，但不要据此认为变换已应用）；`bpy.ops.object.join()` 需要至少两个选中且 active 是合并目标；`bpy.ops.object.modifier_apply(modifier="不存在的名字")` 也只打警告不抛异常。所以别用"没报错"当作成功，要读回数据验证（见 5.2、6.1）。

### 3.4 删除对象

```python
obj = bpy.data.objects.get("smoke_cube")
if obj is not None:
    bpy.data.objects.remove(obj, do_unlink=True)   # 直接销毁（含数据块引用）
```

- 只想从场景移除、保留数据块：`bpy.context.scene.collection.objects.unlink(obj)`；但后续 `scene_report` 之类仍可能从 `bpy.data` 读到它，建模清理一律用 `remove(..., do_unlink=True)`。
- 删除前先 `bpy.data.objects.get(name)` 判空，避免 KeyError/None 调用。

### 3.5 depsgraph 惰性求值（最容易踩的坑）

对象的 `matrix_world`、`dimensions`、`bound_box` 在改完 `location/rotation_euler/scale` 后**不会立刻更新**，直到 depsgraph 刷新。实测：

```python
from mathutils import Vector
cam.location = (4, -4, 3)
cam.rotation_euler = (1.047, 0, 0)
print(cam.matrix_world.translation)      # 可能是旧值（甚至单位阵）
bpy.context.view_layer.update()          # 刷新
print(cam.matrix_world.translation)      # 新值
```

需要读 `matrix_world` / `dimensions` / `bound_box` / `evaluated_get` 之前，先 `bpy.context.view_layer.update()`；渲染与导出操作符内部会自行刷新，不受影响。kit 的 `look_at` / `_finalize` 末尾已经内置刷新。

---

## 4. 图元创建

### 4.1 创建方式与返回值

所有 `bpy.ops.mesh.primitive_*_add(...)` 都会：创建对象 → 挂到当前 collection → 设为 active → 返回 `{'FINISHED'}`；对象本身从 `bpy.context.object` 取。

**新对象默认名**：`Cube`、`Cylinder`、`Sphere`、`Cone`、`Torus`、`Plane`；同名再建会自动加 `.001` 后缀。想稳定命名：创建后立刻 `obj.name = "..."`（`obj.data.name` 可选同步）。

### 4.2 测过的图元参数

```python
import math
import bpy

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
cube = bpy.context.object

bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1.0, vertices=32,
                                    location=(2, 0, 0.5))
cyl = bpy.context.object

bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=32, ring_count=16,
                                     location=(4, 0, 0.5))
sphere = bpy.context.object

bpy.ops.mesh.primitive_cone_add(radius1=0.5, radius2=0.0, depth=1.0, vertices=32,
                                location=(6, 0, 0.5))
cone = bpy.context.object

# 环：主半径 R、截面半径 r → 本地尺寸 2*(R+r) x 2*(R+r) x 2*r（实测 R=0.5,r=0.1 → 1.2,1.2,0.2）
bpy.ops.mesh.primitive_torus_add(major_radius=0.5, minor_radius=0.1,
                                 major_segments=48, minor_segments=12,
                                 rotation=(math.radians(90), 0, 0),
                                 location=(8, 0, 0.5))
torus = bpy.context.object
print("torus rotation_euler", tuple(round(math.degrees(v), 1) for v in torus.rotation_euler))
# (90.0, -0.0, 0.0) —— rotation 参数会写进 rotation_euler（实测）

bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 2, 0))
plane = bpy.context.object
```

要点：

- 图元的 `location` 是**对象原点**位置，不是几何中心（例如圆柱、立方体的几何中心在原点，但底面在 `z-depth/2`；建模时按"底面落地"放 `z = depth/2`）。
- `rotation` 参数单位是**弧度**；`bpy.ops.*` 的 rotation 元组实测会写入 `obj.rotation_euler`（torus 弯 90° 后 `rotation_euler.x == 90°`）。
- 分段数决定面数：低多边形用 `cylinder vertices=8~16`、`sphere segments=16/ring_count=8`、`torus major_segments=24/minor_segments=8`；接口图/近景可翻倍。
- `bpy.ops.mesh.primitive_cube_add(size=2.0)` 的 `size` 是**边长**（实测 `dimensions=(2,2,2)`；`size=1.0` → `(1,1,1)`）；要三轴不同尺寸时用 `obj.scale` 或直接改 `obj.dimensions`（`dimensions` 赋值会反推 scale，需刷新后读回）。
- 需要圆角立方体：立方体 + Bevel 修改器（第 6 节），比手工造倒角省事。

### 4.3 文字与中文字体（实测）

默认字体（Bfont）**没有中文字形**，写中文会缺字/显示为方块。中文必须加载系统字体，并在 `convert(target='MESH')` 之前赋给 `obj.data.font`：

```python
import bpy

# 字体：simhei.ttf 是 Windows 自带黑体；可换成 msyh.ttc / simsun.ttc 等
font = bpy.data.fonts.load(r"C:\Windows\Fonts\simhei.ttf", check_existing=True)
print(font.name)          # "SimHei Regular"（实测）

bpy.ops.object.text_add(location=(0, 0, 0.5))
txt = bpy.context.object
txt.data.body = "中文 Abc"
txt.data.size = 0.5
txt.data.extrude = 0.02          # 挤出厚度，0 就是平面字
txt.data.align_x = 'CENTER'
txt.data.align_y = 'CENTER'
txt.data.font = font              # 必须在 convert 之前

bpy.ops.object.convert(target='MESH')   # 转网格后才能稳定导出/布尔/统计
txt_mesh = bpy.context.object
print(len(txt_mesh.data.vertices))      # 实测 3152（"中文 Abc", size=0.5, extrude=0.02）
```

- 同一字符串用默认字体会得到完全不同的顶点数（实测 209），因为中文字形缺失，**面积/轮廓不可用**。
- `convert` 后对象类型从 `FONT` 变 `MESH`，才方便 `join`、布尔、`mesh_stats`；导出前不转换也能导，但得到的是文字对象。
- 字体文件用绝对路径加载一次即可（`check_existing=True` 复用）；脚本里不要把系统中文字体路径写死成唯一方案，带存在性检查再回退（见第 13 节）。

### 4.4 管状体（把手/线缆）——曲线 + bevel 再转网格

```python
import bpy

cd = bpy.data.curves.new("tube_curve", 'CURVE')
cd.dimensions = '3D'
sp = cd.splines.new('POLY')
pts = [(0, 0, 0), (0.3, 0, 0.2), (0.3, 0.3, 0.2), (0.6, 0.3, 0.0)]
sp.points.add(len(pts) - 1)
for i, co in enumerate(pts):
    sp.points[i].co = (co[0], co[1], co[2], 1.0)   # 注意第 4 分量固定 1.0
cd.bevel_depth = 0.02          # 管半径
cd.bevel_resolution = 2        # 截面细分（圆滑度）
cd.resolution_u = 12           # 段间细分

ob = bpy.data.objects.new("tube", cd)
bpy.context.scene.collection.objects.link(ob)
bpy.ops.object.select_all(action='DESELECT')
ob.select_set(True)
bpy.context.view_layer.objects.active = ob
bpy.ops.object.convert(target='MESH')   # 转成 MESH，便于后续操作
```

- 实测：POLY（直线段）足够做低多边形把手；要平滑曲线用 `splines.new('BEZIER')` 并设置 `handle_left/right`（更繁琐，本机未用于正式资产）。
- `bevel_depth` 是半径；圆头端点会让包围盒略大于控制点范围（实测控制点跨度 1.0 时 x 跨度 1.07）。
- 转 MESH 后 `bpy.context.object` 才是网格对象，名字可能变，需要的话立刻改名。

---

## 5. 变换与几何操作

### 5.1 设置变换（角度用弧度）

```python
import math
obj.location = (1.0, 2.0, 0.5)                       # 米
obj.rotation_euler = (math.radians(30), 0, math.radians(45))  # XYZ 欧拉
obj.scale = (2.0, 1.0, 1.0)
bpy.context.view_layer.update()
```

- 度数转弧度用 `math.radians`；kit 的 `place/rotate` 直接收"度"。
- 欧拉旋转顺序在 UI 里可切（默认 `XYZ`）；脚本里也可用四元数：`obj.rotation_mode='QUATERNION'; obj.rotation_quaternion=...`。
- 父子关系：`child.parent = parent` 后 child 的 `location` 变成父空间坐标；需要保持世界位置时先记录 `child.matrix_world.copy()`，设 parent 后再 `child.matrix_world = saved`（本机未在 kit 中使用，谨慎）。

### 5.2 应用变换（烘焙进网格）

```python
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
# 实测：应用后 obj.location=(0,0,0)、rotation_euler=(0,0,0)、scale=(1,1,1)
```

用途：join 之前统一坐标系、让修改器厚度按世界尺度生效、导出前消除非 1 缩放。

### 5.3 世界包围盒（`obj.bound_box` 是本地的）

`obj.bound_box` 是**本地空间**的 8 个角点；世界包围盒必须左乘 `matrix_world`：

```python
from mathutils import Vector

def world_bbox(objects):
    """返回 (min_xyz, max_xyz)；空列表返回 (None, None)。用修改器后的最终几何需走 evaluated_get。"""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    found = False
    for o in objects:
        ev = o.evaluated_get(dg)                 # 取修改器求值后的版本
        mw = ev.matrix_world
        for c in ev.bound_box:
            p = mw @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
            found = True
    return (tuple(lo), tuple(hi)) if found else (None, None)
```

- 加修改器后 `obj.bound_box` 可能还是修改前的；用 `obj.evaluated_get(depsgraph)` 读求值后的 `bound_box`（kit 的 `world_bbox` 就是这么做的）。
- 实测坑：`Object.dimensions` = **本地 bbox × scale，不含旋转**。边长 1 的立方体绕 Z 转 45° 后 `dimensions` 仍是 `(1.0, 1.0, 1.0)`，但世界 XY 跨度是 `1.414`。要"真实外廓尺寸"用 `world_bbox`，不要用 `dimensions`。

### 5.4 合并、复制、改原点

```python
# 合并：active 对象保留，名字/材质槽以 active 为准；实测两个 8 顶点立方体合并 → 16 顶点
bpy.ops.object.select_all(action='DESELECT')
target.select_set(True)
other.select_set(True)
bpy.context.view_layer.objects.active = target
bpy.ops.object.join()
merged = bpy.context.object          # name == target.name

# 复制（几何独立）
dup = obj.copy()
dup.data = obj.data.copy()
bpy.context.scene.collection.objects.link(dup)
dup.name = "obj_copy"
dup.location = (2, 0, 0)

# 原点：底部中心（先把 3D 游标移到底面中心，再 origin_set）
import mathutils
bpy.context.scene.cursor.location = (obj.location.x, obj.location.y, bottom_z)
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)   # 收尾复位

# 原点：几何中心
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
```

- `origin_set(type='ORIGIN_CURSOR')` 只移动原点，不移动几何的世界位置（实测：改原点前后世界包围盒不变）。
- 对多个对象批量改原点时，先选中全部、active 设其中一个：Blender 会对所有选中对象生效。
- `join` 后材质槽会合并、重复槽可能出现；低多边形资产建议 join 前 `assign_all` 成同一材质，join 后再确认槽位。

### 5.5 网格统计（顶点/三角面/非流形边）

```python
import bmesh

def mesh_stats(obj):
    out = {"name": obj.name, "verts": 0, "tris": 0, "non_manifold_edges": 0}
    if obj.type != 'MESH':
        return out
    me = obj.data
    out["verts"] = len(me.vertices)
    me.calc_loop_triangles()
    out["tris"] = len(me.loop_triangles)
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        out["non_manifold_edges"] = sum(1 for e in bm.edges if not e.is_manifold)
    finally:
        bm.free()
    return out
```

- 三角面数看 `len(me.loop_triangles)`（调用前必须 `calc_loop_triangles()`）；`len(me.polygons)` 是面数（含四边面），不等于 tris。
- 开口边界边也算 non-manifold（与 Blender 的 Non Manifold 选择一致）；单个立方体实测 0。

---

## 6. 修改器

### 6.1 通用模式

```python
# 1) 新建并设置参数
mod = obj.modifiers.new("Bevel", 'BEVEL')
mod.width = 0.02
mod.segments = 2

# 2) 应用（需要 active + 选中；不 apply 时留在修改器栈里，渲染/导出会生效）
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.modifier_apply(modifier=mod.name)

# 3) 清空全部修改器（不应用）
obj.modifiers.clear()
```

- 修改器顺序 = `obj.modifiers` 列表顺序；`modifiers.new` 追加到末尾。
- `bpy.ops.object.modifier_apply(modifier="不存在的名字")` **不抛异常**，只打警告；应用后读 `len(obj.modifiers)` 与顶点数确认。
- 需要"拿到应用后的网格但不销毁修改器"时见 6.3 的 `new_from_object`。

### 6.2 逐类实测参数

```python
import math

# Bevel：圆角；limit_method='ANGLE' 只倒锐边（kit add_bevel 用这个组合，实测通过）
m = obj.modifiers.new("Bevel", 'BEVEL')
m.width = 0.02
m.segments = 3
m.limit_method = 'ANGLE'
m.angle_limit = math.radians(30)

# Subdivision Surface：细分（每级 4 倍面数）
m = obj.modifiers.new("Subsurf", 'SUBSURF')
m.levels = 2
m.render_levels = 2

# Mirror：按轴镜像；use_bisect_axis 用于切开重叠部分
m = obj.modifiers.new("Mirror", 'MIRROR')
m.use_axis = (True, False, False)     # X 轴
m.use_bisect_axis = (False, False, False)

# Solidify：加厚（偏移 -1 向法线反方向，1 向法线方向）
m = obj.modifiers.new("Solidify", 'SOLIDIFY')
m.thickness = 0.02
m.offset = -1.0

# Array：阵列；constant_offset_displace 是"每份偏移的绝对距离"（米）
m = obj.modifiers.new("Array", 'ARRAY')
m.count = 3
m.use_relative_offset = False
m.use_constant_offset = True
m.constant_offset_displace = (0.0, 0.25, 0.0)

# Displace：用纹理扰动顶点（做地面起伏/石块粗糙面）
tex = bpy.data.textures.new("NoiseTex", type='CLOUDS')
tex.noise_scale = 0.5
m = obj.modifiers.new("Displace", 'DISPLACE')
m.texture = tex
m.texture_coords = 'LOCAL'
m.strength = 0.02

# Boolean：实体 cutter 挖洞；solver='EXACT'
m = obj.modifiers.new("Bool", 'BOOLEAN')
m.operation = 'DIFFERENCE'
m.solver = 'EXACT'
m.object = cutter
```

**布尔实测要点**：

- cutter **必须是封闭实体**。实测：立方体用圆柱 cutter（DIFFERENCE）→ 求值网格 72 顶点，挖洞正常。
- 用单面 `plane` 当 cutter 结果**不可预测**（同一立方体、只改平面高度）：平面穿过立方体中部/上部（z=0.50 / 0.75）→ 求值网格仍是原立方体 **8 顶点 6 面**，切割静默不生效；平面悬空在立方体上方（z=1.20）→ 目标被整体清空 **0 顶点**；平面正好贴在顶面（z=1.00）→ 只剩 **4 顶点 1 个面**。需要"切"的效果时，给平面加 Solidify 变成薄实体，或改用实体图元。
- 布尔结果法线可能翻转/出现内壁；低多边形优先做"简单图元叠加"而不是复杂挖孔（见 AGENTS.md 降级路径）。
- 布尔应用后 cutter 应立即删除：`bpy.data.objects.remove(cutter, do_unlink=True)`。

### 6.3 取"修改后网格"（不破坏修改器栈）

```python
dg = bpy.context.evaluated_depsgraph_get()
ev = obj.evaluated_get(dg)
me = bpy.data.meshes.new_from_object(ev)   # 新网格，独立于 obj.data
print(len(me.vertices))
# 需要时替换原网格（相当于 apply 全部修改器）：
old = obj.data
obj.data = me
bpy.data.meshes.remove(old)
obj.modifiers.clear()
```

- 这是导出/统计前"把修改器烘焙进去"的安全写法，比 `modifier_apply` 少踩上下文坑；kit 内部布尔应用也走求值网格。
- `new_from_object` 只对可求值对象有效（MESH / 曲线转网格后 / FONT 转网格后）；对空 data 会抛异常。

### 6.4 平滑着色与自动平滑

```python
# 面级平滑：所有面 use_smooth=True（角变圆，但可能把直角也磨圆）
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.shade_smooth()
print(obj.data.polygons[0].use_smooth)    # True（实测）

# 自动平滑：只有夹角小于阈值的边显示为硬边（4.0.2 属性存在，实测可设）
if hasattr(obj.data, "use_auto_smooth"):
    obj.data.use_auto_smooth = True
    obj.data.auto_smooth_angle = math.radians(30)   # 30°（实测读回 30.0）

# 回到硬边
bpy.ops.object.shade_flat()
```

- `shade_smooth()` 是面级标记，不改变几何；`use_auto_smooth`（4.0.2 存在）配合角度阈值控制哪条边看起来是硬的。写兼容代码时用 `hasattr` 保护，别假设更高版本也存在。
- 修改器场景下更省事的顺序：先 `shade_smooth`，再加 Bevel/Subsurf；或给特定边做标记后 4.x 用 "Smooth by Angle" 修改器（本机未验证，不在此推荐）。

---

## 7. 材质（Principled BSDF 节点）

### 7.1 创建材质并配置

```python
import bpy

m = bpy.data.materials.new("mug_white")
m.use_nodes = True                       # 默认节点树里已有 Principled BSDF + Material Output
bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')

bsdf.inputs['Base Color'].default_value = (0.92, 0.92, 0.90, 1.0)  # RGBA，0-1
bsdf.inputs['Roughness'].default_value = 0.35
bsdf.inputs['Metallic'].default_value = 0.0
bsdf.inputs['Alpha'].default_value = 1.0

# 自发光（4.0 名称是 Emission Color，不是旧的 Emission）
bsdf.inputs['Emission Color'].default_value = (1.0, 0.4, 0.1, 1.0)
bsdf.inputs['Emission Strength'].default_value = 3.0

# 半透明：alpha < 1 时材质本身不会混合，要切 blend_method（枚举实测存在）
bsdf.inputs['Alpha'].default_value = 0.5
m.blend_method = 'BLEND'    # 可选 'OPAQUE' / 'CLIP' / 'HASHED' / 'BLEND'
```

### 7.2 Principled BSDF 输入名（4.0.2 实测全表）

```
Base Color, Metallic, Roughness, IOR, Alpha, Normal, Weight,
Subsurface Weight, Subsurface Radius, Subsurface Scale, Subsurface IOR,
Subsurface Anisotropy, Specular IOR Level, Specular Tint, Anisotropic,
Anisotropic Rotation, Tangent, Transmission Weight, Coat Weight,
Coat Roughness, Coat IOR, Coat Tint, Coat Normal, Sheen Weight,
Sheen Roughness, Sheen Tint, Emission Color, Emission Strength
```

实测差异：4.0.2 里 **没有** `Emission` 输入（旧名已改为 `Emission Color`），**没有** `Specular`（改为 `Specular IOR Level`）。按名字取值前先判断存在，或直接用 kit 的 `mat()`。

### 7.3 给对象赋材质

```python
# 单个对象：没有槽就追加，有槽就替换第 0 个（kit.assign 语义）
if len(obj.data.materials) == 0:
    obj.data.materials.append(m)
else:
    obj.data.materials[0] = m

# 多材质槽：按面索引 material_index 分配
obj.data.materials.append(m2)
obj.data.polygons[0].material_index = 1
```

- 材质是**数据块**，可被多个对象共享；同名新建不会自动复用，要用 `bpy.data.materials.get(name)` 或 kit 的 `mat()`（同名直接返回已有材质）。
- `m.diffuse_color` 只影响视口预览颜色，不影响渲染；渲染用节点里的 Base Color（实测两者完全独立）。
- 需要随机/程序化纹理时节点树更复杂，低多边形资产优先用纯色 + 粗糙度/金属度区分。

---

## 8. 相机与取景

### 8.1 创建相机与朝向

```python
import bpy
from mathutils import Vector

bpy.ops.object.camera_add(location=(4.0, -4.0, 3.0))
cam = bpy.context.object
cam.data.lens = 50.0            # 毫米；越大视角越窄
cam.data.sensor_width = 36.0    # 毫米（默认 36，sensor_fit='AUTO'）

# 让相机 -Z 轴指向目标：to_track_quat('-Z','Y')
target = Vector((0.0, 0.0, 0.5))
d = target - cam.location
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
bpy.context.view_layer.update()   # 之后读 matrix_world 才准
```

- 相机看向 -Z，画面上方是 +Y（本地坐标）；`to_track_quat('-Z','Y')` 是标准"看向"写法（灯光同理，灯光朝向 -Z）。
- 不要手糊欧拉角：很容易翻车；用 `to_track_quat`。
- 相机进入渲染：`bpy.context.scene.camera = cam`；没有相机时裸 `bpy.ops.render.render()` 会报 `Cannot render, no camera`。

### 8.2 自动取景（按包围盒摆距离）

推荐直接用 kit（已实测）：`fit_camera(camera, objects, margin=1.2)`、`render_views(dir, views=("front","right","iso"))`。裸写时的最小可用版本（**包围球**近似，画面偏松但稳定）：

```python
import math
import bpy
from mathutils import Vector

def frame_camera(cam, objects, margin=1.2):
    """沿当前相机→包围盒中心方向，把相机摆到能完整看到 objects 的距离，并对准中心。"""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    for o in objects:
        ev = o.evaluated_get(dg)
        for c in ev.bound_box:
            p = ev.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    center = (lo + hi) * 0.5
    radius = (hi - lo).length * 0.5
    # 画面较长边半视角；竖图/横图不同，取长边角度做保守估计（方形渲染时两轴相同）
    tan_h = cam.data.sensor_width / (2.0 * cam.data.lens)
    aspect = bpy.context.scene.render.resolution_x / max(bpy.context.scene.render.resolution_y, 1)
    tan_v = tan_h / aspect if aspect >= 1.0 else tan_h * aspect
    tan_min = min(tan_h, tan_v)
    dist = radius / math.sin(math.atan(tan_min)) * margin
    direction = (center - cam.location)
    if direction.length < 1e-9:
        direction = Vector((1.0, -1.0, 0.6))
    cam.location = center - direction.normalized() * dist
    d2 = center - cam.location
    cam.rotation_euler = d2.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
```

- 取景对象**不要包含地台**（直径 20m 的地台会把相机推到很远，主体变得很小）；kit 的 `render_views` 默认排除 `setup_floor` 建的地台。
- 想看"构图留白是否合理"，用 8.3 的 NDC 检查代替目测。

### 8.3 验证取景是否完整（NDC 投影）

```python
from bpy_extras.object_utils import world_to_camera_view
bpy.context.view_layer.update()          # 不刷新会拿到 (0.5, 0.5, 0.0) 这种假值（实测）
ndc = world_to_camera_view(bpy.context.scene, cam, Vector((0.0, 0.0, 0.5)))
print(ndc)      # 实测刷新后 (0.5, 0.589, 6.399)
# 判据：x/y ∈ [0.05, 0.95]（留边），z > 0（在相机前方）
in_frame = 0.05 <= ndc.x <= 0.95 and 0.05 <= ndc.y <= 0.95 and ndc.z > 0
```

对包围盒 8 个角点做投影，全部在 `[0,1]` 内且 `z>0` 即"完整入画"；这是 `fit_camera` 自测的判据。

### 8.4 多视角渲染 + 相机恢复

```python
import os
import bpy
from mathutils import Vector

sc = bpy.context.scene
views = {
    "front": Vector((0.0, 1.0, 0.15)),    # 相机在 +Y 侧
    "right": Vector((1.0, 0.0, 0.15)),    # 相机在 +X 侧
    "iso":   Vector((1.0, 1.0, 0.7)),     # 前右上方
}
saved_loc = cam.location.copy()
saved_rot = cam.rotation_euler.copy()
center = Vector((0.0, 0.0, 0.5))          # 主体中心（用 world_bbox 算更准）
dist = 3.0                                # 用 frame_camera 算出的距离

for name, direction in views.items():
    cam.location = center + direction.normalized() * dist
    d = center - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(OUT, "view-%s.png" % name)
    bpy.ops.render.render(write_still=True)

cam.location = saved_loc                   # 恢复原相机（用 copy 保存，别存引用）
cam.rotation_euler = saved_rot
```

- `saved_loc = cam.location.copy()` 必须 `.copy()`，否则保存的是引用，改 location 时会一起变。
- 实测：3 个视角（512×512 / 16 samples / CYCLES CPU）连续渲染约 4-7 秒。

---

## 9. 灯光与世界背景

```python
import bpy

# AREA 灯：energy 单位是瓦特；size 越大阴影越软
bpy.ops.object.light_add(type='AREA', location=(3.0, -3.0, 5.0))
key = bpy.context.object
key.data.energy = 500.0
key.data.size = 3.0
key.data.shape = 'SQUARE'     # 'SQUARE' / 'RECTANGLE' / 'DISK' / 'ELLIPSE'

# 灯光朝向（灯也是 -Z 指向目标）
from mathutils import Vector
d = Vector((0, 0, 0)) - key.location
key.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# 世界背景：Background 节点颜色 + 强度（强度即环境光亮度）
world = bpy.data.worlds.get("World")
if world is None:
    world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
bg.inputs['Color'].default_value = (0.05, 0.05, 0.06, 1.0)   # 近黑背景
bg.inputs['Strength'].default_value = 0.6                    # 0.6 时是柔和环境光
```

- 三点布光经验值（kit `setup_studio_lights` 实测通过、模板出图正常）：key 500W、fill 150W、rim 300W，灯到目标距离约 4m，AREA size 3m 左右；全部朝目标点。
- **实测反例**：只放一盏 key 灯、world strength 0.6 时，背对灯的那个视角几乎只剩环境光（立方体场景 512 图 `std ≈ 2.8`，肉眼接近纯色），多视角交付必须用三点布光，或把 world strength 提到 0.8~1.0 再补 fill。
- 背景强度决定"整体黑不黑"：纯黑 world（strength 0）+ 只靠一盏灯时，暗面容易死黑；`strength=0.5~1.0` 的近黑世界更稳。
- 需要透明背景时用 `scene.render.film_transparent = True`（第 10 节），不是改 world。

---

## 10. 渲染

### 10.1 引擎与采样

```python
sc = bpy.context.scene
sc.render.engine = 'CYCLES'          # 其他实测可用值：'BLENDER_EEVEE'、'BLENDER_WORKBENCH'
sc.cycles.device = 'CPU'             # 无头/无 GPU 环境用 CPU；有 GPU 另配
sc.cycles.samples = 16               # 预览 8-16，终渲 48-64
sc.cycles.use_denoising = True
sc.cycles.denoiser = 'OPENIMAGEDENOISE'   # 实测可设
```

- 三个引擎在 `--factory-startup` 无头模式都能渲染出图（实测 CYCLES / EEVEE / WORKBENCH 均非空 PNG）；EEVEE 在后台可用，无头机器缺 OpenGL 时才需要退回 WORKBENCH。
- `BLENDER_EEVEE` 没有 Cycles 的 `samples` 语义（用 `sc.eevee.taa_render_samples`）；小图快检可直接 WORKBENCH。
- 降噪只在 CYCLES 下有意义；`denoiser` 属性不存在或非法时直接赋值会抛异常，包在 `try/except` 里。

### 10.2 分辨率、格式、透明背景

```python
sc.render.resolution_x = 512
sc.render.resolution_y = 512
sc.render.resolution_percentage = 100      # 最终像素 = x * pct%
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'   # 需要 alpha 时
sc.render.film_transparent = True              # 透明背景
```

- 实测透明背景渲染后图像 alpha ∈ [0, 1]（透明处 0）；不透明场景 alpha 全 1。
- 预览 512×512、终渲 960×960 是本机跑得动的档位；再大注意单图耗时线性上升。

### 10.3 色彩管理（AgX）

```python
s = sc.view_settings
s.view_transform = 'AgX'            # 实测合法值：'Standard','AgX','Filmic','Filmic Log','False Color','Raw'
s.look = 'AgX - Medium High Contrast'   # 实测可设
s.exposure = 0.0
s.gamma = 1.0
```

- 4.0.2 默认 `view_transform='AgX'`、`look='None'`（实测）；'None' 是字符串值，不是 Python None。
- 设置不存在的 look/transform 会抛 `TypeError`（信息形如 `enum "AgX - Not A Real Look" not found in (...)`）；写通用脚本时用 `try/except` 回退到 `'None'`。
- 想让画面"更亮/更透"先调曝光与灯光能量，再考虑 look；不要用 gamma 硬拉。

### 10.4 渲染到文件（含路径坑）

```python
sc.render.filepath = os.path.join(OUT, "preview.png")   # 绝对路径最稳
bpy.ops.render.render(write_still=True)
print(os.path.getsize(sc.render.filepath))              # > 10 KB 才算有内容
```

- **没有扩展名时**会自动补：`sc.render.filepath = ".../noext"` → 实际写出 `noext.png`（实测）。
- 相对路径 `//xxx.png` 是"相对 blend 文件目录"；**未保存过 blend 时实测落到了进程 CWD**，容易找不到文件。一律用绝对路径（脚本里用 `__file__` 或环境变量推导）。
- 也可以在 `bpy.ops.render.render()` 之后用 `Render Result` 存图，但无头模式下 `bpy.data.images["Render Result"].size` 实测读到 `(0, 0)`（仍能 `save_render` 成功），不适合做尺寸校验；优先 `write_still=True`。

### 10.5 耗时参考（本机 Windows / CPU / 立方体场景）

| 设置 | 单图耗时 | PNG 体积 |
| --- | --- | --- |
| CYCLES 512×512 / 16 samples / denoise | ≈ 1.6s | ≈ 248 KB |
| CYCLES 960×960 / 48 samples / denoise | ≈ 3.0s | ≈ 853 KB |
| EEVEE 256×256 | < 1s | ≈ 36 KB |
| WORKBENCH 256×256 | < 1s | ≈ 38 KB |

模板实拍（马克杯 + 地台 + 三点灯）：`--stage full` 总耗时 40.8s（3 张 512 预览 + 3 张 960 终渲 + 导出 blend/glb + 报告）；`--stage render` 6.6s；`--stage build` 1.5s。超过这个量级一个数量级，先查分辨率/采样/对象数。

### 10.6 渲染结果非全黑自检（PNG 像素统计）

```python
import bpy
import numpy as np

def image_stats(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        rgba = buf.reshape(-1, 4)
        mask = rgba[:, 3] > 0.01                  # 忽略透明像素
        lum = rgba[mask, :3].mean(axis=1) * 255.0 # pixels 是 0-1 编码的 sRGB 值
        if lum.size == 0:
            return 0.0, 0.0, 1.0
        return float(lum.mean()), float(lum.std()), float((lum < 8.0).mean())
    finally:
        bpy.data.images.remove(img)

mean, std, black = image_stats(r"F:\path\preview.png")
print(mean, std, black)      # 判据：std > 4 且 black < 0.98；更严：8 <= std <= 120
```

- `img.pixels` 返回 0-1 的 float（PNG 8bit 解码后 = byte/255，实测纯 0.5 灰度 emission 渲染出 188/255=0.7333，sRGB 编码后），乘 255 就是 0-255 尺度。
- `img.pixels` 顺序是 **RGBA 逐像素、从图像左下角开始**；统计与方向无关，但取某个具体位置时要注意。
- **逐视图统计**：单灯场景很容易出现一张通过、另一张接近纯色（见第 9 节实测反例），三张预览图要分别算 `std`/`black_ratio`，不能只看一张。
- 33% 慢的纯 Python 版本也可用：`pixels = list(img.pixels)` 后切片，大图慢；有 numpy（Blender 自带）就用 `foreach_get`。

---

## 11. 导出

### 11.1 保存 .blend

```python
bpy.ops.wm.save_as_mainfile(filepath=r"F:\out\model.blend", check_existing=False)
```

- `check_existing=False` 避免覆盖确认；目录不存在会报错，先 `os.makedirs(dirname, exist_ok=True)`。
- 实测模板场景 `.blend` ≈ 556,892 B；空场景 `.blend` 实测 388,456 B（≈379 KB），文件体积明显小于这个量级说明几乎没内容。

### 11.2 glTF / GLB

```python
bpy.ops.export_scene.gltf(
    filepath=r"F:\out\model.glb",
    export_format='GLB',       # 'GLB' 单文件；'GLTF_SEPARATE' 会额外生成 .bin/贴图
    use_selection=False,       # True 只导选中的
    export_apply=True,         # 导出前应用修改器
    export_cameras=False,
    export_lights=False,
    export_yup=True,           # glTF 是 Y-up，Blender 是 Z-up，默认转换
)
```

- 实测成功，日志有 `export finished in 0.0x sec.`；模板 .glb ≈ 102,452 B。
- 导出后校验文件头：`open(path,'rb').read(4) == b'glTF'`（实测通过）。
- 只导模型时保持 `export_cameras=False, export_lights=False`，否则引擎里会多出相机/灯光节点。

### 11.3 OBJ（4.0 的新操作符）

```python
bpy.ops.wm.obj_export(
    filepath=r"F:\out\model.obj",
    export_selected_objects=False,   # 注意参数名与旧版不同
    apply_modifiers=True,
    export_materials=True,
    export_normals=True,
    export_uv=True,
)
```

- 4.0.2 实测：走 `bpy.ops.wm.obj_export`；旧版操作符 `bpy.ops.export_scene.obj` 已不存在（调用报 `AttributeError: Calling operator ... error, could not be found`）。
- 会额外生成同名 `.mtl`（实测目录里出现 `model.mtl`），这是正常现象，交付时一起带上或忽略。

### 11.4 STL（4.0 走 export_mesh.stl）

```python
bpy.ops.export_mesh.stl(
    filepath=r"F:\out\model.stl",
    use_selection=False,
    ascii=False,             # False = 二进制，体积小
    use_mesh_modifiers=True, # 导出前应用修改器
)
```

- **实测坑**：4.0.2 里 `bpy.ops.wm.stl_export` **不存在**（`get_rna_type()` 抛 `KeyError: 'get_rna_type("WM_OT_stl_export") not found'`），但 `bpy.ops.export_mesh.stl` 可用（插件 `io_mesh_stl` 默认启用）。kit 的 `export_stl()` 按"先试 `wm.stl_export`、失败回退 `export_mesh.stl`"实现，正好兼容两个版本。

### 11.5 FBX

```python
bpy.ops.export_scene.fbx(
    filepath=r"F:\out\model.fbx",
    use_selection=False,
    use_mesh_modifiers=True,
    path_mode='AUTO',
    embed_textures=False,
)
```

- 实测成功；FBX 插件 `io_scene_fbx` 在 `--factory-startup` 下已启用，无需手动开启。

### 11.6 操作符可用性检测（`hasattr` 是陷阱）

`bpy.ops.<mod>.<op>` 是动态属性，`hasattr` 对**不存在的操作符也返回 True**；正确检测方式是 `get_rna_type()` 或直接调用后捕获异常：

```python
def op_exists(op):
    try:
        op.get_rna_type()
        return True
    except KeyError:
        return False

print(hasattr(bpy.ops.wm, "stl_export"))        # True ← 假阳性（实测）
print(op_exists(bpy.ops.wm.stl_export))         # False
print(op_exists(bpy.ops.export_mesh.stl))       # True
print(op_exists(bpy.ops.wm.obj_export))         # True
```

优雅降级写法（kit 实际采用的模式）：

```python
def export_stl_safe(path):
    try:
        bpy.ops.wm.stl_export(filepath=path)
        return path
    except (AttributeError, KeyError):
        pass
    try:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=False,
                                ascii=False, use_mesh_modifiers=True)
        return path
    except Exception as exc:
        print("STL 导出失败（已降级记录）:", exc)
        return ""
```

### 11.7 导出文件校验

```python
def head(path, n=8):
    with open(path, "rb") as f:
        return f.read(n)

print(head("model.blend", 7))  # b'BLENDER'（实测；完整文件头是 b'BLENDER-'）
print(head("model.glb", 4))    # b'glTF'（实测）
print(head("model.stl", 5))    # 二进制 STL 无固定 magic，用体积 > 1KB 判断
```

---

## 12. Blender 4.0 与旧版差异（本机实测）

| 主题 | 4.0.2 实测 | 旧版（2.9x/3.x）写法 |
| --- | --- | --- |
| OBJ 导出 | `bpy.ops.wm.obj_export(...)` | `bpy.ops.export_scene.obj(...)`（4.0.2 已移除，调用报 AttributeError） |
| STL 导出 | `bpy.ops.export_mesh.stl(...)` | 旧版同样走 `export_mesh.stl`；4.0.2 无 `wm.stl_export`（新版本才可能提供） |
| Principled 自发光输入 | `Emission Color` + `Emission Strength` | `Emission`（4.0.2 无此输入） |
| Principled 高光输入 | `Specular IOR Level` | `Specular`（4.0.2 无此输入） |
| Principled 新增输入 | `Weight`、`Coat *`、`Sheen *`、`Transmission Weight` 等 | 旧版权重/涂层参数更少 |
| 默认色彩变换 | `view_transform='AgX'`，`look='None'`（字符串） | 多为 Filmic |
| 自动平滑 | `mesh.use_auto_smooth` + `mesh.auto_smooth_angle` 在 4.0.2 存在且可设（实测） | 同名；换版本以实测为准，写兼容代码用 `hasattr` 保护 |
| EEVEE 引擎 ID | `'BLENDER_EEVEE'`（4.0.2 实测） | 本机只验证 4.0.2，其他版本引擎名以实测为准 |
| 操作符探测 | `get_rna_type()` 抛 `KeyError` 表示不存在 | 同上；不要依赖 `hasattr` |
| 导出插件 | `--factory-startup` 下 glTF/FBX/STL 全部已启用 | 部分旧版本需手动 `addon_enable` |

---

## 13. 常见坑速查表

| # | 症状 | 原因 | 解决 |
| --- | --- | --- | --- |
| 1 | `Cannot render, no camera` | `scene.camera` 未设置 | `scene.camera = cam` |
| 2 | 渲染全黑 | world strength 0 / 灯 energy 0 / 相机在物体内部 / `film_transparent` 且无环境 | 查 world、灯能量、相机位置；临时开 `film_transparent=False` 看背景 |
| 3 | 渲染全白/过曝（mean > 235） | 灯能量过大 / 世界太亮 / exposure 高 | 降 key 能量、降 world strength、exposure 归 0 |
| 4 | `matrix_world` / `dimensions` / `bound_box` 是旧值 | depsgraph 未刷新 | 读之前 `bpy.context.view_layer.update()` |
| 5 | `obj.dimensions` 与实际外廓不符 | dimensions 只含本地 bbox×scale，不含旋转 | 用 `matrix_world @ bound_box` 算世界包围盒 |
| 6 | `hasattr(bpy.ops.x, "op")` 恒为 True | bpy.ops 动态属性 | 用 `get_rna_type()` / 调用后捕获异常 |
| 7 | 调用导出 op 报 `could not be found` | 操作符在该版本不存在（如 4.0 的 `wm.stl_export`、`export_scene.obj`） | 换成 4.0 对应的新 op，或按 11.6 降级 |
| 8 | 布尔 DIFFERENCE 结果异常：静默不切割 / 物体整个消失 / 只剩一个面 | cutter 是单面平面（非实体）；实测四种摆法分别得到 8/8/0/4 顶点 | cutter 必须封闭实体；平面先 Solidify |
| 9 | 中文文字缺字/方块 | 默认字体无中文字形 | 加载 `C:\Windows\Fonts\simhei.ttf` 赋给 `obj.data.font` 再 convert |
| 10 | 透明度没效果 | 只改了 Alpha 没设 blend_method | `mat.blend_method = 'BLEND'` |
| 11 | 修改器/变换"没报错但没效果" | 操作符依赖选中 + active，空选中时静默跳过 | 先 `select_set(True)` + 设 active；读回数据验证 |
| 12 | 渲染文件找不到 | 相对路径 `//` 且 blend 未保存 → 落到 CWD | 用绝对路径；或先保存 blend |
| 13 | `Render Result` 尺寸为 (0,0) | 无头模式限制 | 用 `write_still=True` + `scene.render.filepath` |
| 14 | 找不到导出文件（少扩展名） | `render.filepath` 无扩展名时自动补 `.png` | 路径写全扩展名；用 `os.path.getsize` 校验 |
| 15 | stderr 出现 `TBBmalloc ... unknown prologue` | 正常噪音 | 忽略，只看退出码/异常 |
| 16 | 脚本异常但退出码 0 | 没加 `--python-exit-code 1` | 命令行加 `--python-exit-code 1` |
| 17 | 设置 `look` 抛 `TypeError` | 该 look 名不在枚举里（不同版本列表不同） | `try/except` 回退 `'None'` |
| 18 | 对象重名出现 `.001` | 同名对象已存在 | 统一命名规则 + `bpy.data.objects.get(name)` 查重 |
| 19 | 需要旧 API 的 `Emission` 输入报 KeyError | 4.0 改名 `Emission Color` | 按名字判断是否存在，或统一用 kit `mat()` |
| 20 | 渲染慢到超时 | 分辨率/采样过高、对象/面数过多、开 denoise 但采样过低 | 预览 512/16，终渲 960/48；先 build 验建模 |
| 21 | 多视角里某一张接近全黑/近乎纯色（`std < 4`） | 只有一盏 key 灯，背光面没有补光，世界强度又低 | 三点布光（`setup_studio_lights`）或提高 world strength；本机实测单 key + 0.6 时背光视角 `std ≈ 2.8` |

---

## 14. 与 `blender_kit` 的对应关系

写 `model.py` 时优先用 kit（自带防御、统一命名、自动刷新），只有缺能力时才用本文裸 bpy：

| 目标 | kit 函数（`lib/blender_kit.py`） | 对应旧写法 |
| --- | --- | --- |
| 清场 / 世界 / 布光 / 地台 | `reset_scene` `setup_world` `setup_studio_lights` `setup_floor` | 本文第 3.1、9 节 |
| 相机 / 朝向 / 取景 / 场景一次搭好 | `add_camera` `look_at` `fit_camera` `setup_scene` | 第 8 节 |
| 图元 | `cube` `cylinder` `sphere` `cone` `torus` `plane` `tube` `text` | 第 4 节 |
| 变换 | `place` `rotate` `translate` `scale_obj` `apply_transform` | 第 5.1、5.2 节 |
| 修改器 | `add_bevel` `add_subsurf` `add_mirror` `add_solidify` `add_array` `add_boolean` `add_displace` `apply_modifiers` | 第 6 节 |
| 网格操作 | `join` `duplicate` `shade_smooth` `shade_flat` `set_origin` `mesh_stats`（增补：`world_bbox` `select_only` `delete` `sit_on_floor`） | 第 5.3-5.5、6.4 节 |
| 材质 | `mat` `assign` `assign_all`（增补：`set_text_font`） | 第 7 节 |
| 渲染 | `setup_render` `render_still` `render_views` `render_turntable` | 第 8.4、10 节（含统计） |
| 导出 / 报告 | `save_blend` `export_glb` `export_stl` `export_fbx` `export_obj` `export_all` `scene_report` `save_report` | 第 11 节 |
| 环境 | `stage()`（`BLENDER_STAGE`）`script_args()`（`--` 之后参数） | 第 2 节 |

约定：kit 的旋转参数一律是**度**；材质颜色是 0-1 RGB；`render_views` 默认三视角 `front/right/iso` 并自动排除 `setup_floor` 建的地台；`export_all(out_dir, stem)` 固定写 `<out_dir>/<stem>.blend` 与 `<stem>.glb`，报告写到 `out_dir` 的上一级。

---

## 15. 自检清单（每次改环境/换机器先跑）

1. **版本**：`blender.exe -b --factory-startup -noaudio --python-expr "import bpy;print(bpy.app.version_string)"` → 期望 `4.0.2`。
2. **最小闭环**：跑第 1 节 `smoke.py`，退出码 0、`smoke.png` > 10 KB、`smoke.blend`/`smoke.glb` 存在。
3. **导出可用性**：11.6 的 `op_exists` 打印 `wm.obj_export=True`、`export_mesh.stl=True`、`wm.stl_export=False`（4.0.2）。
4. **渲染非全黑**：10.6 的 `image_stats` → `std > 4`、`black_ratio < 0.98`（更严：`8 <= std <= 120`、`20 <= mean <= 235`）。
5. **取景**：8.3 的 NDC 检查，8 个角点 x/y 在 `[0.05, 0.95]`、`z > 0`。
6. **降级路径**：故意把 `export_stl_safe` 第一段 op 改成不存在名字，确认 fallback 仍能出文件。
