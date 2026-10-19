# -*- coding: utf-8 -*-
"""blender_kit —— Blender 建模技能的运行时核心库（只能在 Blender 的 Python 进程内 import）。

用法（建模脚本里）::

    import os, sys
    sys.path.insert(0, os.environ["BLENDER_KIT_DIR"])  # run_blender.py 注入
    import blender_kit as kit

    kit.reset_scene()
    kit.setup_scene()
    body = kit.cube("Body", size=(1, 0.6, 0.4), location=(0, 0, 0.2))
    kit.shade_smooth(body, angle=30)
    kit.setup_render(engine="CYCLES", samples=32, resolution=(512, 512))
    kit.render_views(os.path.join(OUT, "renders"))
    kit.export_all(os.path.join(OUT, "exports"), stem="model")

设计原则：
- 所有公开函数返回有意义的值（对象 / 字典 / 路径 / 列表），失败时尽量降级并 print 警告，不抛未捕获异常。
- 不在模块级缓存 bpy.context.scene（reset_scene 之后旧引用会失效），一律现场取。
- 兼容 Blender 4.0.x：对 4.1+ 改动的属性（如 use_auto_smooth）用 hasattr 防御。
- 本模块的公开函数名/参数名/返回语义视为稳定接口，不可破坏性改动；文件末尾的“增补工具函数”是额外便利，不替代主接口。

实测环境：Blender 4.0.2（Windows，headless，CYCLES/EEVEE/WORKBENCH 均可用）。
"""

import bpy
import bmesh
import os
import sys
import math
import json
import time

from mathutils import Vector, Euler

KIT_VERSION = "1.0.0"

# 渲染统计 / 导出记录 / 警告等运行时状态；save_report() 会汇总它们
_STATE = {
    "renders": [],       # render_still 的统计字典列表
    "exports": {},       # {kind: {"path", "bytes"}}
    "warnings": [],      # 降级/失败信息
    "render_setup": {},  # 最近一次 setup_render 的参数
}

# 视为“有几何体”的对象类型（用于 bbox / 取景，不含相机灯光）
_GEOMETRY_TYPES = {"MESH", "CURVE", "FONT", "SURFACE", "META"}

_ENGINE_MAP = {
    "CYCLES": "CYCLES",
    "EEVEE": "BLENDER_EEVEE",
    "BLENDER_EEVEE": "BLENDER_EEVEE",
    "EEVEE_NEXT": "BLENDER_EEVEE",  # 4.2+ 的名字，4.0 自动回退
    "BLENDER_EEVEE_NEXT": "BLENDER_EEVEE",
    "WORKBENCH": "BLENDER_WORKBENCH",
    "BLENDER_WORKBENCH": "BLENDER_WORKBENCH",
}

# render_views 的视角方向（从目标指向相机的单位方向；+Y = 正前方，+X = 右侧）
_VIEW_DIRECTIONS = {
    "front": (0.0, 1.0, 0.22),
    "right": (1.0, 0.0, 0.22),
    "left": (-1.0, 0.0, 0.22),
    "back": (0.0, -1.0, 0.22),
    "iso": (1.0, 1.0, 0.8),
}


# ---------------------------------------------------------------------------
# 内部工具（下划线开头，不属于公开 API）
# ---------------------------------------------------------------------------

def _scene():
    """返回当前场景（每次都现场取，避免 reset_scene 后拿到失效引用）。"""
    return bpy.context.scene


def _log(msg):
    print("[kit] %s" % msg)


def _warn(msg):
    msg = str(msg)
    _STATE["warnings"].append(msg)
    print("[kit][WARN] %s" % msg)


def _ensure_object_mode():
    """确保处于 Object Mode（后台模式下某些 bpy.ops 需要）。"""
    try:
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass


def _unique_object_name(base):
    """返回在 bpy.data.objects 中不重复的对象名（base、base.001、base.002 ...）。"""
    base = str(base) if base else "Object"
    if base not in bpy.data.objects:
        return base
    i = 1
    while True:
        cand = "%s.%03d" % (base, i)
        if cand not in bpy.data.objects:
            return cand
        i += 1


def _unique_data_name(base, data_collection):
    base = str(base) if base else "Data"
    if base not in data_collection:
        return base
    i = 1
    while True:
        cand = "%s.%03d" % (base, i)
        if cand not in data_collection:
            return cand
        i += 1


def _link(obj):
    """把对象链接进当前活动集合（取不到时链接进场景主集合）。"""
    try:
        coll = bpy.context.collection
    except Exception:
        coll = None
    if coll is None:
        coll = bpy.context.scene.collection
    coll.objects.link(obj)
    return obj


def _new_object(name, data):
    """用已建好的 data 创建对象、链接进场景并返回。"""
    obj = bpy.data.objects.new(_unique_object_name(name), data)
    _link(obj)
    return obj


def _activate(obj):
    """把 obj 设为唯一选中 + 激活对象；返回是否成功。"""
    if obj is None:
        return False
    _ensure_object_mode()
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except Exception:
        try:
            for o in bpy.context.scene.objects:
                o.select_set(False)
        except Exception:
            pass
    try:
        obj.select_set(True)
    except Exception:
        return False
    try:
        bpy.context.view_layer.objects.active = obj
    except Exception:
        return False
    return True


def _ensure_dir_for(path):
    """为文件路径创建父目录（path 已是绝对路径）。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def _set_socket(node, names, value):
    """按候选名字给节点输入赋值：node.inputs[name].default_value = value。"""
    for name in names:
        try:
            sock = node.inputs.get(name)
            if sock is None:
                continue
            sock.default_value = value
            return True
        except Exception:
            continue
    return False


def _configure_material(m, color=(0.8, 0.8, 0.8), roughness=0.5, metallic=0.0,
                        emission=None, emission_strength=0.0, alpha=1.0):
    """把已有材质配置成 Principled BSDF 简单 PBR 材质（内部共用）。"""
    r = min(1.0, max(0.0, float(color[0])))
    g = min(1.0, max(0.0, float(color[1])))
    b = min(1.0, max(0.0, float(color[2])))
    a = min(1.0, max(0.0, float(alpha)))
    m.use_nodes = True
    nt = m.node_tree
    bsdf = None
    for n in nt.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            bsdf = n
            break
    if bsdf is None:
        bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = None
        for n in nt.nodes:
            if n.type == 'OUTPUT_MATERIAL':
                out = n
                break
        if out is None:
            out = nt.nodes.new('ShaderNodeOutputMaterial')
        try:
            nt.links.new(bsdf.outputs[0], out.inputs['Surface'])
        except Exception:
            pass
    _set_socket(bsdf, ("Base Color",), (r, g, b, 1.0))
    _set_socket(bsdf, ("Roughness",), float(roughness))
    _set_socket(bsdf, ("Metallic",), float(metallic))
    _set_socket(bsdf, ("Alpha",), a)
    if emission is not None:
        er = min(1.0, max(0.0, float(emission[0])))
        eg = min(1.0, max(0.0, float(emission[1])))
        eb = min(1.0, max(0.0, float(emission[2])))
        _set_socket(bsdf, ("Emission Color", "Emission"), (er, eg, eb, 1.0))
        _set_socket(bsdf, ("Emission Strength",), float(emission_strength))
    # 视口 / WORKBENCH 渲染用的显示颜色（WORKBENCH + color_type='MATERIAL' 会用）
    try:
        m.diffuse_color = (r, g, b, a)
        m.roughness = float(roughness)
        m.metallic = float(metallic)
    except Exception:
        pass
    if a < 1.0:
        try:
            m.blend_method = 'BLEND'
        except Exception:
            pass
        try:
            m.show_transparent_back = False
        except Exception:
            pass
    return m


def _finalize(obj, name=None, material=None):
    """图元收尾：改名（唯一）、同步 data 名、赋材质。"""
    if obj is None:
        return None
    if name:
        new_name = _unique_object_name(name)
        obj.name = new_name
        data = getattr(obj, "data", None)
        if data is not None:
            try:
                data.name = new_name
            except Exception:
                pass
    if material is not None:
        assign(obj, material)
    # 立即刷新 depsgraph：保证 obj.dimensions / matrix_world / bound_box 立刻可用
    # （新建或修改 mesh 顶点/旋转后这些属性是惰性计算的，不刷新会读到旧值）
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return obj


def _activate_for_modifier(obj):
    """给修改器操作准备上下文；失败返回 False。"""
    return _activate(obj)


def _apply_modifier(obj, mod_name):
    """应用单个修改器（bpy.ops 方式）；失败返回 False 并记警告。"""
    if not _activate_for_modifier(obj):
        _warn("无法激活对象 %r，修改器 %r 未应用" % (getattr(obj, "name", obj), mod_name))
        return False
    try:
        bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception as exc:
        _warn("修改器 %r 应用失败（%r），尝试 depsgraph 烘焙" % (mod_name, exc))
        return False


def _bake_modifiers(obj):
    """用 depsgraph 求值结果整体替换 obj.data（作为 modifier_apply 的兜底）。"""
    if obj is None or obj.type != 'MESH' or not getattr(obj, "modifiers", None):
        return obj
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        new_mesh = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        old = obj.data
        obj.modifiers.clear()
        obj.data = new_mesh
        if old is not None and old.users == 0:
            try:
                bpy.data.meshes.remove(old)
            except Exception:
                pass
    except Exception as exc:
        _warn("depsgraph 烘焙修改器失败: %r" % (exc,))
    return obj


def world_bbox(objects):
    """【增补】计算一组对象的合并世界空间包围盒。

    参数:
        objects: bpy 对象列表（None 会被跳过；只统计有几何体的类型或带 bound_box 的对象）
    返回:
        ((min_x,min_y,min_z), (max_x,max_y,max_z))；列表为空/无有效对象时返回 (None, None)。
    """
    bpy.context.view_layer.update()
    dg = None
    try:
        dg = bpy.context.evaluated_depsgraph_get()
    except Exception:
        dg = None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    found = False
    for obj in (objects or []):
        if obj is None:
            continue
        try:
            bb = list(obj.bound_box)
            mw = obj.matrix_world.copy()
            if dg is not None and obj.type in _GEOMETRY_TYPES:
                try:
                    ev = obj.evaluated_get(dg)
                    bb = list(ev.bound_box)
                    mw = ev.matrix_world.copy()
                except Exception:
                    pass
            if not bb:
                continue
            for corner in bb:
                p = mw @ Vector((corner[0], corner[1], corner[2]))
                for i in range(3):
                    if p[i] < lo[i]:
                        lo[i] = p[i]
                    if p[i] > hi[i]:
                        hi[i] = p[i]
                found = True
        except Exception:
            continue
    if not found:
        return (None, None)
    return (tuple(round(v, 6) for v in lo), tuple(round(v, 6) for v in hi))


# ---------------------------------------------------------------------------
# 4.1 场景与灯光相机
# ---------------------------------------------------------------------------

def reset_scene():
    """清空为工厂默认的空场景（不保留任何对象/材质/灯光/相机）。

    返回:
        None
    """
    _ensure_object_mode()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # 少数情况下（后台模式）read_factory_settings 后没有活动场景，兜底补一个
    try:
        if bpy.context.scene is None and bpy.data.scenes:
            bpy.context.window.scene = bpy.data.scenes[0]
    except Exception:
        pass
    _STATE["renders"] = []
    _STATE["exports"] = {}
    _STATE["warnings"] = []
    _STATE["render_setup"] = {}
    _log("场景已重置为空场景（Blender %s）" % bpy.app.version_string)


def setup_world(color=(0.05, 0.05, 0.06), strength=0.6):
    """设置世界背景颜色与亮度（用 World 节点里的 Background 节点）。

    参数:
        color: 0-1 RGB 背景色（默认近黑，避免死黑也避免过曝）
        strength: 背景强度（0.6 时是柔和的环境光）
    返回:
        None
    """
    sc = _scene()
    w = sc.world
    if w is None:
        w = bpy.data.worlds.get("World")
        if w is None:
            w = bpy.data.worlds.new("World")
        sc.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree
    bg = None
    if nt is not None:
        for n in nt.nodes:
            if n.type == 'BACKGROUND':
                bg = n
                break
        if bg is None:
            bg = nt.nodes.new('ShaderNodeBackground')
            out = None
            for n in nt.nodes:
                if n.type == 'OUTPUT_WORLD':
                    out = n
                    break
            if out is None:
                out = nt.nodes.new('ShaderNodeOutputWorld')
            try:
                nt.links.new(bg.outputs['Background'], out.inputs['Surface'])
            except Exception:
                pass
        try:
            bg.inputs['Color'].default_value = (
                min(1.0, max(0.0, float(color[0]))),
                min(1.0, max(0.0, float(color[1]))),
                min(1.0, max(0.0, float(color[2]))),
                1.0,
            )
            bg.inputs['Strength'].default_value = float(strength)
        except Exception as exc:
            _warn("设置世界背景失败: %r" % (exc,))
    try:
        w.color = (float(color[0]), float(color[1]), float(color[2]))
    except Exception:
        pass


def setup_studio_lights(center=(0, 0, 0), radius=4.0, key_energy=500.0,
                        fill_energy=150.0, rim_energy=300.0):
    """摆 3 盏三点布光的 AREA 灯（key 主光 / fill 补光 / rim 轮廓光），全部朝向 center。

    参数:
        center: 打光目标点
        radius: 布光半径（灯到 center 的距离基准）
        key_energy / fill_energy / rim_energy: 三盏灯的功率（瓦）
    返回:
        灯光对象列表 [key, fill, rim]
    """
    c = Vector((float(center[0]), float(center[1]), float(center[2])))
    r = max(float(radius), 0.5)
    specs = [
        # (名字, 相对方向, 功率, 尺寸系数, 颜色)
        ("Key", Vector((-0.9, 1.1, 1.4)), float(key_energy), 0.55, (1.0, 0.97, 0.92)),
        ("Fill", Vector((1.3, 0.9, 0.55)), float(fill_energy), 0.9, (0.92, 0.96, 1.0)),
        ("Rim", Vector((0.3, -1.5, 1.5)), float(rim_energy), 0.45, (1.0, 0.98, 0.95)),
    ]
    lights = []
    for base, direction, energy, size_ratio, color in specs:
        name = _unique_object_name(base)
        ld = bpy.data.lights.new(name, type='AREA')
        try:
            ld.energy = energy
            ld.size = r * size_ratio
            ld.color = color
            ld.shape = 'SQUARE'
        except Exception as exc:
            _warn("配置灯光 %r 失败: %r" % (base, exc))
        ob = _new_object(name, ld)
        ob.location = c + direction * r
        look_at(ob, c)
        lights.append(ob)
    return lights


def setup_floor(size=20.0, color=(0.35, 0.35, 0.38), roughness=0.8):
    """在 z=0 添加一块地台平面（带材质，标记 kit_role='floor'，取景/统计时会自动排除）。

    参数:
        size: 平面边长（米）
        color: 0-1 RGB
        roughness: 粗糙度
    返回:
        平面对象
    """
    bpy.ops.mesh.primitive_plane_add(size=float(size), location=(0.0, 0.0, 0.0))
    ob = bpy.context.object
    ob.name = _unique_object_name("Floor")
    try:
        ob.data.name = ob.name
    except Exception:
        pass
    m = bpy.data.materials.get("FloorMat")
    if m is None:
        m = mat("FloorMat", color=color, roughness=roughness)
    else:
        # 地台材质被复用：重新配置，保证本次 color/roughness 生效
        _configure_material(m, color=color, roughness=roughness)
    assign(ob, m)
    ob["kit_role"] = "floor"
    return ob


def add_camera(location=(4, -4, 3), target=(0, 0, 0), lens=50):
    """新建相机、放到 location 并朝向 target，同时设为场景当前相机。

    参数:
        location: 相机位置（米）
        target: 注视点
        lens: 焦距（mm，50 为标准视角）
    返回:
        相机对象（bpy.types.Object, type == 'CAMERA'）
    """
    name = _unique_object_name("Camera")
    cd = bpy.data.cameras.new(name)
    cd.lens = float(lens)
    ob = _new_object(name, cd)
    ob.location = Vector((float(location[0]), float(location[1]), float(location[2])))
    look_at(ob, target)
    try:
        _scene().camera = ob
    except Exception:
        pass
    return ob


def look_at(obj, target=(0, 0, 0)):
    """让对象（相机/灯光/任意物体）的 -Z 轴指向世界坐标 target。

    参数:
        obj: bpy 对象
        target: 世界坐标注视点
    返回:
        None
    """
    if obj is None:
        return
    try:
        t = Vector((float(target[0]), float(target[1]), float(target[2])))
        d = t - obj.location
        if d.length < 1e-9:
            return
        obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        # 刷新 depsgraph，保证 matrix_world 立即反映新朝向
        bpy.context.view_layer.update()
    except Exception as exc:
        _warn("look_at 失败: %r" % (exc,))


def _camera_tan_half_fov(camera):
    """返回相机水平/垂直半视角的正切 (tan_x, tan_y)，考虑了 sensor_fit 与渲染分辨率比例。"""
    data = camera.data
    lens = max(float(getattr(data, "lens", 50.0)), 1e-6)
    sensor = float(getattr(data, "sensor_width", 36.0))
    fit = str(getattr(data, "sensor_fit", 'AUTO'))
    try:
        rx = max(int(_scene().render.resolution_x), 1)
        ry = max(int(_scene().render.resolution_y), 1)
    except Exception:
        rx, ry = 1, 1
    aspect = float(rx) / float(ry)
    if fit == 'HORIZONTAL':
        tan_x = sensor / (2.0 * lens)
        tan_y = tan_x / aspect
    elif fit == 'VERTICAL':
        tan_y = sensor / (2.0 * lens)
        tan_x = tan_y * aspect
    else:  # AUTO：sensor_width 作用在较长边
        if aspect >= 1.0:
            tan_x = sensor / (2.0 * lens)
            tan_y = tan_x / aspect
        else:
            tan_y = sensor / (2.0 * lens)
            tan_x = tan_y * aspect
    # 相机 shift 会移动画面中心，保守地把额外余量算上
    shift_x = abs(float(getattr(data, "shift_x", 0.0)))
    shift_y = abs(float(getattr(data, "shift_y", 0.0)))
    tan_x = max(tan_x * (1.0 - 2.0 * shift_x), 1e-6)
    tan_y = max(tan_y * (1.0 - 2.0 * shift_y), 1e-6)
    return tan_x, tan_y


def fit_camera(camera, objects, margin=1.2):
    """把相机沿“当前相机 -> objects 包围盒中心”的方向摆到能完整取景的距离上（并居中取景）。

    参数:
        camera: 相机对象
        objects: 需要入画的对象列表（一般为建模网格；地台建议不传）
        margin: 边距系数，1.2 表示视角里物体四周留 ~20% 空间（1.0 刚好贴边）
    返回:
        None
    """
    if camera is None:
        return
    objs = [o for o in (objects or []) if o is not None]
    if not objs:
        _warn("fit_camera: objects 为空，跳过取景")
        return
    if str(getattr(camera, "type", "")) != 'CAMERA':
        _warn("fit_camera: %r 不是相机，跳过" % (getattr(camera, "name", camera),))
        return
    bpy.context.view_layer.update()
    lo, hi = world_bbox(objs)
    if lo is None:
        _warn("fit_camera: 无法计算包围盒（对象可能已被删除），跳过")
        return
    center = Vector(((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5))
    radius = max((Vector(hi) - Vector(lo)).length * 0.5, 1e-4)
    m = max(float(margin), 0.2)

    to_center = center - camera.location
    if to_center.length < 1e-9:
        dirv = -(camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0)))
        if dirv.length < 1e-9:
            dirv = Vector((0.0, -1.0, -0.4))
        dirv.normalize()
    else:
        dirv = to_center.normalized()

    up_world = Vector((0.0, 0.0, 1.0))
    if abs(dirv.dot(up_world)) > 0.999:
        up_world = Vector((0.0, 1.0, 0.0))
    right = dirv.cross(up_world)
    if right.length < 1e-9:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    up_cam = right.cross(dirv)
    if up_cam.length < 1e-9:
        up_cam = Vector((0.0, 1.0, 0.0))
    up_cam.normalize()

    cam_data = camera.data
    if getattr(cam_data, "type", 'PERSP') == 'ORTHO':
        xmax = ymax = 0.0
        for cx in (lo[0], hi[0]):
            for cy in (lo[1], hi[1]):
                for cz in (lo[2], hi[2]):
                    v = Vector((cx, cy, cz)) - center
                    xmax = max(xmax, abs(v.dot(right)))
                    ymax = max(ymax, abs(v.dot(up_cam)))
        try:
            rx = max(int(_scene().render.resolution_x), 1)
            ry = max(int(_scene().render.resolution_y), 1)
        except Exception:
            rx, ry = 1, 1
        aspect = float(rx) / float(ry)
        scale = max(xmax * 2.0, ymax * 2.0 * aspect) * m
        try:
            cam_data.ortho_scale = max(scale, 1e-3)
        except Exception:
            pass
        camera.location = center - dirv * (radius * 2.0 + 1.0)
        look_at(camera, center)
        return

    tan_x, tan_y = _camera_tan_half_fov(camera)
    dist = radius * 0.25
    for cx in (lo[0], hi[0]):
        for cy in (lo[1], hi[1]):
            for cz in (lo[2], hi[2]):
                v = Vector((cx, cy, cz)) - center
                depth_extra = v.dot(dirv)  # 该角点在中心之前(+)或之后(-)
                need_x = abs(v.dot(right)) / tan_x - depth_extra
                need_y = abs(v.dot(up_cam)) / tan_y - depth_extra
                dist = max(dist, need_x, need_y)
    dist = max(dist, radius * 0.25, 1e-4) * m
    camera.location = center - dirv * dist
    look_at(camera, center)
    try:
        cam_data.clip_start = max(0.001, dist * 0.02)
        cam_data.clip_end = max(float(cam_data.clip_end), dist + radius * 6.0, 10.0)
    except Exception:
        pass


def setup_scene(target=(0, 0, 0), distance=4.0, azimuth=-45.0, elevation=25.0,
                lens=50, studio=True, floor=True):
    """一次性搭好场景：世界背景 + 三点灯 + 地台（可选）+ 相机。

    方位约定：azimuth=0 时相机在目标正前方（+Y）；负值向 +X（画面右侧）旋转；
    elevation 为仰角（度，正值相机在上方）。

    参数:
        target: 场景中心（相机注视点、灯光/地台围绕它布置）
        distance: 相机到 target 的距离（米）
        azimuth: 水平方位角（度）
        elevation: 仰角（度）
        lens: 相机焦距 mm
        studio: 是否创建三点布光
        floor: 是否创建地台
    返回:
        {"camera": 相机对象, "lights": [灯对象...]}
    """
    t = Vector((float(target[0]), float(target[1]), float(target[2])))
    dist = max(float(distance), 0.1)
    az = math.radians(float(azimuth))
    el = math.radians(float(elevation))
    # 从 target 指向相机的方向：az=0 -> +Y；az=-45 -> (+X,+Y) 即前右上方
    direction = Vector((
        math.cos(el) * (-math.sin(az)),
        math.cos(el) * math.cos(az),
        math.sin(el),
    ))
    location = t + direction * dist

    setup_world()
    lights = []
    if studio:
        lights = setup_studio_lights(center=t, radius=max(dist * 0.8, 1.0))
    if floor:
        setup_floor(size=max(20.0, dist * 5.0))
    cam = add_camera(location=location, target=t, lens=lens)
    return {"camera": cam, "lights": lights}


# ---------------------------------------------------------------------------
# 4.2 几何体（全部返回 bpy object；name 唯一；可传 material）
# ---------------------------------------------------------------------------

def cube(name, size=(1, 1, 1), location=(0, 0, 0), rotation=(0, 0, 0), material=None):
    """创建立方体/长方体。

    参数:
        name: 对象名（重复时自动加 .001 后缀）
        size: 三轴边长（米）；传单个数字表示各轴相同
        location / rotation: 位置、旋转（rotation 单位为度）
        material: 可选材质
    返回:
        Mesh 对象（缩放已应用到网格数据，object.scale 保持 1）
    """
    if isinstance(size, (int, float)):
        size = (size, size, size)
    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location,
                                    rotation=[math.radians(v) for v in rotation])
    ob = bpy.context.object
    try:
        for v in ob.data.vertices:
            v.co.x *= sx
            v.co.y *= sy
            v.co.z *= sz
        ob.data.update()
    except Exception as exc:
        _warn("cube 尺寸缩放失败: %r" % (exc,))
    return _finalize(ob, name, material)


def cylinder(name, radius=0.5, depth=1.0, vertices=32, location=(0, 0, 0),
             rotation=(0, 0, 0), material=None):
    """创建圆柱体（轴向沿本地 Z）。

    参数:
        radius: 半径；depth: 高度；vertices: 圆周分段（>=3）
        location / rotation（度）/ material 同上
    返回:
        Mesh 对象
    """
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=max(3, int(vertices)), radius=float(radius), depth=float(depth),
        location=location, rotation=[math.radians(v) for v in rotation])
    return _finalize(bpy.context.object, name, material)


def sphere(name, radius=0.5, segments=32, rings=16, location=(0, 0, 0),
           rotation=(0, 0, 0), material=None):
    """创建 UV 球。

    参数:
        radius: 半径；segments: 经线分段；rings: 纬线环数
        location / rotation（度）/ material 同上
    返回:
        Mesh 对象
    """
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=max(3, int(segments)), ring_count=max(2, int(rings)),
        radius=float(radius), location=location,
        rotation=[math.radians(v) for v in rotation])
    return _finalize(bpy.context.object, name, material)


def cone(name, radius1=0.5, radius2=0.0, depth=1.0, vertices=32, location=(0, 0, 0),
         rotation=(0, 0, 0), material=None):
    """创建圆锥/圆台（轴向沿本地 Z）。

    参数:
        radius1: 底面半径；radius2: 顶面半径（0 = 尖锥）；depth: 高度；vertices: 分段
        location / rotation（度）/ material 同上
    返回:
        Mesh 对象
    """
    bpy.ops.mesh.primitive_cone_add(
        vertices=max(3, int(vertices)), radius1=float(radius1), radius2=float(radius2),
        depth=float(depth), location=location,
        rotation=[math.radians(v) for v in rotation])
    return _finalize(bpy.context.object, name, material)


def torus(name, major_radius=0.5, minor_radius=0.1, location=(0, 0, 0),
          rotation=(0, 0, 0), material=None):
    """创建圆环（甜甜圈）。

    参数:
        major_radius: 环心半径；minor_radius: 管截面半径
        location / rotation（度）/ material 同上
    返回:
        Mesh 对象
    """
    bpy.ops.mesh.primitive_torus_add(
        major_radius=float(major_radius), minor_radius=float(minor_radius),
        location=location, rotation=[math.radians(v) for v in rotation])
    return _finalize(bpy.context.object, name, material)


def plane(name, size=1.0, location=(0, 0, 0), rotation=(0, 0, 0), material=None):
    """创建正方形平面（默认在 XY 平面，法线 +Z）。

    参数:
        size: 边长；location / rotation（度）/ material 同上
    返回:
        Mesh 对象
    """
    bpy.ops.mesh.primitive_plane_add(size=float(size), location=location,
                                     rotation=[math.radians(v) for v in rotation])
    return _finalize(bpy.context.object, name, material)


def tube(name, points, radius=0.02, resolution=12, material=None, closed=False):
    """用折线 + 圆形截面生成管状网格（适合把手、线缆、边框）。

    参数:
        points: [(x,y,z), ...] 折线控制点（只支持 POLY 直线段）
        radius: 管半径（bevel_depth）
        resolution: 曲线细分（resolution_u）
        material: 可选材质
        closed: True 时首尾相连成闭环
    返回:
        Mesh 对象（曲线已转成网格）
    """
    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in (points or [])]
    if not pts:
        _warn("tube: points 为空，返回空网格对象")
        me = bpy.data.meshes.new(_unique_data_name(str(name), bpy.data.meshes))
        return _finalize(_new_object(name, me), name, material)
    if len(pts) == 1:
        pts = [pts[0], pts[0]]
    cd = bpy.data.curves.new(_unique_data_name(str(name), bpy.data.curves), 'CURVE')
    cd.dimensions = '3D'
    sp = cd.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for i, co in enumerate(pts):
        sp.points[i].co = (co[0], co[1], co[2], 1.0)
    try:
        sp.use_cyclic_u = bool(closed)
    except Exception:
        pass
    try:
        cd.bevel_depth = float(radius)
        cd.bevel_resolution = 2
        cd.resolution_u = int(resolution)
    except Exception as exc:
        _warn("tube: 曲线参数设置失败 %r" % (exc,))
    ob = _new_object(name, cd)
    if _activate(ob):
        try:
            bpy.ops.object.convert(target='MESH')
            ob = bpy.context.object
        except Exception as exc:
            _warn("tube: 曲线转网格失败: %r" % (exc,))
    if material is not None:
        assign(ob, material)
    # convert 之后对象名可能变化，统一改名
    new_name = _unique_object_name(str(name))
    ob.name = new_name
    try:
        ob.data.name = new_name
    except Exception:
        pass
    return ob


def text(name, body="A", size=1.0, extrude=0.05, location=(0, 0, 0),
         rotation=(0, 0, 0), material=None):
    """创建文字对象（3D 文字，可挤出；保持 FONT 类型，导出时会被转换）。

    参数:
        body: 文字内容（默认字体不含中文字形，中文请用 set_text_font 指定字体文件）
        size: 字号；extrude: 挤出厚度
        location / rotation（度）/ material 同上
    返回:
        FONT 类型对象
    """
    bpy.ops.object.text_add(location=location,
                            rotation=[math.radians(v) for v in rotation])
    ob = bpy.context.object
    d = ob.data
    try:
        d.body = str(body)
        d.size = float(size)
        d.extrude = float(extrude)
        d.align_x = 'CENTER'
        d.align_y = 'CENTER'
    except Exception as exc:
        _warn("text: 属性设置失败 %r" % (exc,))
    return _finalize(ob, name, material)


# ---------------------------------------------------------------------------
# 4.3 变换与网格操作
# ---------------------------------------------------------------------------

def place(obj, location=None, rotation=None, scale=None):
    """设置对象的绝对位置/旋转/缩放（不累加）。

    参数:
        location: (x,y,z) 或 None 表示不改
        rotation: (rx,ry,rz) 欧拉角，单位为**度**
        scale: (sx,sy,sz)
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        if location is not None:
            obj.location = Vector((float(location[0]), float(location[1]), float(location[2])))
        if rotation is not None:
            if hasattr(rotation, "x") and not isinstance(rotation, (tuple, list)):
                obj.rotation_euler = rotation
            else:
                obj.rotation_euler = Euler([math.radians(float(v)) for v in rotation], 'XYZ')
        if scale is not None:
            if isinstance(scale, (int, float)):
                scale = (scale, scale, scale)
            obj.scale = Vector((float(scale[0]), float(scale[1]), float(scale[2])))
    except Exception as exc:
        _warn("place 失败: %r" % (exc,))
    return obj


def rotate(obj, x=0, y=0, z=0):
    """在现有欧拉角上**增量**旋转（单位：度）。

    参数:
        x/y/z: 各轴增量角度
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        obj.rotation_euler.x += math.radians(float(x))
        obj.rotation_euler.y += math.radians(float(y))
        obj.rotation_euler.z += math.radians(float(z))
    except Exception as exc:
        _warn("rotate 失败: %r" % (exc,))
    return obj


def translate(obj, delta=(0, 0, 0)):
    """把对象按增量平移（米）。

    参数:
        delta: (dx,dy,dz)
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        obj.location = Vector(obj.location) + Vector(
            (float(delta[0]), float(delta[1]), float(delta[2])))
    except Exception as exc:
        _warn("translate 失败: %r" % (exc,))
    return obj


def scale_obj(obj, scale=(1, 1, 1)):
    """设置对象的绝对缩放（与 place 的 scale 参数一致）。

    参数:
        scale: (sx,sy,sz) 或单个数字
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        if isinstance(scale, (int, float)):
            scale = (scale, scale, scale)
        obj.scale = Vector((float(scale[0]), float(scale[1]), float(scale[2])))
    except Exception as exc:
        _warn("scale_obj 失败: %r" % (exc,))
    return obj


def apply_transform(obj, location=True, rotation=True, scale=True):
    """把对象的变换烘焙进网格数据（object 的 loc/rot/scale 复位）。

    参数:
        location/rotation/scale: 分别控制哪些分量要应用
    返回:
        obj
    """
    if obj is None:
        return obj
    if not _activate(obj):
        _warn("apply_transform: 无法激活对象，跳过")
        return obj
    try:
        bpy.ops.object.transform_apply(location=bool(location), rotation=bool(rotation),
                                       scale=bool(scale))
    except Exception as exc:
        _warn("apply_transform 失败: %r" % (exc,))
    return obj


def shade_smooth(obj, angle=30.0):
    """平滑着色；4.0 下同时开启 auto_smooth 并设置角度（4.1+ 属性被移除则只平滑）。

    参数:
        angle: auto smooth 角度阈值（度）
    返回:
        obj
    """
    if obj is None:
        return obj
    _activate(obj)
    try:
        bpy.ops.object.shade_smooth()
    except Exception as exc:
        _warn("shade_smooth 失败: %r" % (exc,))
    me = getattr(obj, "data", None)
    if me is not None and hasattr(me, "use_auto_smooth"):
        try:
            me.use_auto_smooth = True
            me.auto_smooth_angle = math.radians(float(angle))
        except Exception:
            pass
    return obj


def shade_flat(obj):
    """平面着色（硬边）。

    参数:
        obj: 对象
    返回:
        obj
    """
    if obj is None:
        return obj
    _activate(obj)
    try:
        bpy.ops.object.shade_flat()
    except Exception as exc:
        _warn("shade_flat 失败: %r" % (exc,))
    return obj


def apply_modifiers(obj):
    """把对象当前所有修改器应用到网格（逐个 apply；全部失败时用 depsgraph 烘焙兜底）。

    参数:
        obj: 对象
    返回:
        obj
    """
    if obj is None:
        return obj
    if not getattr(obj, "modifiers", None):
        return obj
    for mod in list(obj.modifiers):
        if not _apply_modifier(obj, mod.name):
            _bake_modifiers(obj)
            break
    return obj


def join(objects, name):
    """把一组网格对象合并为一个对象（使用第一个对象作为目标）。

    参数:
        objects: 对象列表
        name: 合并后对象名（唯一化）
    返回:
        合并后的对象；列表为空时返回 None
    """
    objs = [o for o in (objects or []) if o is not None]
    if not objs:
        _warn("join: objects 为空，返回 None")
        return None
    if len(objs) == 1:
        if name:
            objs[0].name = _unique_object_name(str(name))
        return objs[0]
    _ensure_object_mode()
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except Exception:
        pass
    for o in objs:
        try:
            o.select_set(True)
        except Exception:
            pass
    target = objs[0]
    try:
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.join()
    except Exception as exc:
        _warn("join 失败: %r" % (exc,))
        return target
    if name:
        target.name = _unique_object_name(str(name))
    return target


def duplicate(obj, name=None, location=(0, 0, 0)):
    """复制对象（连同 mesh/curve 数据一起复制，修改器随对象复制）。

    参数:
        obj: 原对象
        name: 新对象名（None 时用 <原名>_copy）
        location: 新对象的位置
    返回:
        新对象；obj 为 None 时返回 None
    """
    if obj is None:
        return None
    try:
        new = obj.copy()
        data = getattr(obj, "data", None)
        if data is not None:
            try:
                new.data = data.copy()
            except Exception:
                pass
        _link(new)
        base = name if name else ("%s_copy" % obj.name)
        new.name = _unique_object_name(str(base))
        new.location = Vector((float(location[0]), float(location[1]), float(location[2])))
        return new
    except Exception as exc:
        _warn("duplicate 失败: %r" % (exc,))
        return None


def add_bevel(obj, width=0.02, segments=3, angle_limit=30.0):
    """加倒角修改器（只在夹角大于 angle_limit 的边上倒角）。

    参数:
        width: 倒角宽度（米）；segments: 分段数；angle_limit: 角度阈值（度）
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        mod = obj.modifiers.new(name="Bevel", type='BEVEL')
        mod.width = float(width)
        mod.segments = max(1, int(segments))
        try:
            mod.limit_method = 'ANGLE'
            mod.angle_limit = math.radians(float(angle_limit))
        except Exception:
            pass
    except Exception as exc:
        _warn("add_bevel 失败: %r" % (exc,))
    return obj


def add_subsurf(obj, levels=2, render_levels=2):
    """加细分曲面修改器。

    参数:
        levels: 视口/求值级别；render_levels: 渲染级别
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        mod = obj.modifiers.new(name="Subdivision", type='SUBSURF')
        mod.levels = max(0, int(levels))
        mod.render_levels = max(0, int(render_levels))
    except Exception as exc:
        _warn("add_subsurf 失败: %r" % (exc,))
    return obj


def add_mirror(obj, axis="X", bisect=False):
    """加镜像修改器。

    参数:
        axis: "X" / "Y" / "Z" 或轴列表
        bisect: True 时用 bisect 方式（沿轴切掉一半再镜像）
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        axes = axis if isinstance(axis, (list, tuple, set)) else [axis]
        idx = {str(a).upper(): i for a, i in (("X", 0), ("Y", 1), ("Z", 2))}
        mod = obj.modifiers.new(name="Mirror", type='MIRROR')
        for name in ("use_axis", "use_bisect_axis"):
            try:
                vals = list(getattr(mod, name))
                vals = [False, False, False]
                for a in axes:
                    i = idx.get(str(a).upper())
                    if i is not None:
                        vals[i] = True
                setattr(mod, name, vals)
            except Exception:
                pass
        if bisect:
            try:
                mod.use_clip = True
            except Exception:
                pass
    except Exception as exc:
        _warn("add_mirror 失败: %r" % (exc,))
    return obj


def add_solidify(obj, thickness=0.02):
    """加实体化修改器（给没有厚度的面片增加厚度）。

    参数:
        thickness: 厚度（米，负值向内）
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        mod = obj.modifiers.new(name="Solidify", type='SOLIDIFY')
        mod.thickness = float(thickness)
    except Exception as exc:
        _warn("add_solidify 失败: %r" % (exc,))
    return obj


def add_array(obj, count=3, offset=(0, 0, 0)):
    """加阵列修改器（绝对位移常量偏移）。

    参数:
        count: 阵列数量
        offset: 每个副本的位移 (dx,dy,dz)（米）；全 0 会重叠，建议显式给值
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        off = list(offset or (0, 0, 0))
        while len(off) < 3:
            off.append(0.0)
        mod = obj.modifiers.new(name="Array", type='ARRAY')
        mod.count = max(1, int(count))
        mod.use_relative_offset = False
        mod.use_constant_offset = True
        mod.constant_offset_displace = Vector((float(off[0]), float(off[1]), float(off[2])))
    except Exception as exc:
        _warn("add_array 失败: %r" % (exc,))
    return obj


def add_boolean(obj, cutter, operation="DIFFERENCE", solver="EXACT", apply=True):
    """加布尔修改器。

    参数:
        obj: 被操作对象
        cutter: 切割体对象
        operation: "DIFFERENCE" / "UNION" / "INTERSECT"
        solver: "EXACT" / "FAST"
        apply: True 时立即求值应用修改器并删除 cutter；False 时保留活动修改器，
               并把 cutter 设为 hide_render（避免它出现在渲染里）
    返回:
        obj（失败时也返回 obj，错误打到 log）
    """
    if obj is None or cutter is None:
        _warn("add_boolean: obj 或 cutter 为 None，跳过")
        return obj
    try:
        mod = obj.modifiers.new(name="Boolean", type='BOOLEAN')
        mod.object = cutter
        mod.operation = str(operation).upper()
        try:
            mod.solver = str(solver).upper()
        except Exception:
            try:
                mod.solver = 'EXACT'
            except Exception:
                pass
        if apply:
            if _apply_modifier(obj, mod.name):
                try:
                    bpy.data.objects.remove(cutter, do_unlink=True)
                except Exception:
                    pass
            else:
                _bake_modifiers(obj)
                try:
                    bpy.data.objects.remove(cutter, do_unlink=True)
                except Exception:
                    pass
        else:
            try:
                cutter.hide_render = True
            except Exception:
                pass
    except Exception as exc:
        _warn("add_boolean 失败: %r" % (exc,))
    return obj


def add_displace(obj, strength=0.02, noise_scale=0.5, texture_type="CLOUDS"):
    """加置换修改器（程序纹理噪声，做石块/布料起伏）。

    参数:
        strength: 置换强度（米）
        noise_scale: 噪声尺度（越大起伏越缓）
        texture_type: Blender 纹理类型（"CLOUDS"/"STUCCI"/"VORONOI" ...）
    返回:
        obj
    """
    if obj is None:
        return obj
    try:
        tex = bpy.data.textures.new(_unique_data_name("DisplaceTex", bpy.data.textures),
                                    type=str(texture_type).upper())
        try:
            tex.noise_scale = float(noise_scale)
        except Exception:
            pass
        mod = obj.modifiers.new(name="Displace", type='DISPLACE')
        mod.texture = tex
        mod.strength = float(strength)
        mod.mid_level = 0.5
    except Exception as exc:
        _warn("add_displace 失败: %r" % (exc,))
    return obj


def set_origin(obj, mode="BOTTOM"):
    """移动对象原点位置（几何体在世界空间中的位置不变）。

    参数:
        mode: "BOTTOM" = 原点移到世界包围盒底部中心（建模基线常用）；
              "CENTER" = 原点移到包围盒几何中心
    返回:
        obj
    """
    if obj is None:
        return obj
    mode_u = str(mode).upper()
    if mode_u not in ("BOTTOM", "CENTER"):
        mode_u = "BOTTOM"
    lo, hi = world_bbox([obj])
    if lo is None:
        _warn("set_origin: 无法计算包围盒，跳过")
        return obj
    if not _activate(obj):
        _warn("set_origin: 无法激活对象，跳过")
        return obj
    cursor_old = None
    try:
        cursor_old = Vector(_scene().cursor.location)
    except Exception:
        cursor_old = None
    try:
        if mode_u == "CENTER":
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        else:
            _scene().cursor.location = ((lo[0] + hi[0]) * 0.5,
                                        (lo[1] + hi[1]) * 0.5,
                                        lo[2])
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    except Exception as exc:
        _warn("set_origin 失败: %r" % (exc,))
    finally:
        if cursor_old is not None:
            try:
                _scene().cursor.location = cursor_old
            except Exception:
                pass
    return obj


def mesh_stats(obj):
    """返回网格统计。

    参数:
        obj: 对象（非 Mesh 对象返回全 0 统计）
    返回:
        {"name": str, "verts": int, "tris": int, "non_manifold_edges": int}
        注：开口边界边也算 non_manifold（与 Blender 的 Non Manifold 选择一致）。
    """
    out = {"name": getattr(obj, "name", ""), "verts": 0, "tris": 0, "non_manifold_edges": 0}
    if obj is None or str(getattr(obj, "type", "")) != 'MESH':
        return out
    me = getattr(obj, "data", None)
    if me is None:
        return out
    try:
        out["verts"] = len(me.vertices)
        me.calc_loop_triangles()
        out["tris"] = len(me.loop_triangles)
    except Exception as exc:
        _warn("mesh_stats(tris) 失败: %r" % (exc,))
    try:
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            out["non_manifold_edges"] = sum(1 for e in bm.edges if not e.is_manifold)
        finally:
            bm.free()
    except Exception as exc:
        _warn("mesh_stats(non_manifold) 失败: %r" % (exc,))
    return out


# ---------------------------------------------------------------------------
# 4.4 材质
# ---------------------------------------------------------------------------

def mat(name, color=(0.8, 0.8, 0.8), roughness=0.5, metallic=0.0,
        emission=None, emission_strength=0.0, alpha=1.0):
    """创建/获取 Principled BSDF 材质（同名直接复用已有材质，不再改参数）。

    参数:
        name: 材质名（缓存键）
        color: 0-1 RGB 基础色
        roughness: 粗糙度 0-1；metallic: 金属度 0-1
        emission: 自发光颜色 0-1 RGB 或 None
        emission_strength: 自发光强度（要发光必须 >0；None/0 时不自发光）
        alpha: 不透明度 0-1（<1 时自动设置 BLEND 混合）
    返回:
        bpy.types.Material
    """
    m = bpy.data.materials.get(str(name))
    if m is not None:
        return m
    m = bpy.data.materials.new(str(name))
    return _configure_material(m, color=color, roughness=roughness, metallic=metallic,
                               emission=emission, emission_strength=emission_strength,
                               alpha=alpha)


def assign(obj, material):
    """给对象赋予材质（替换第一个材质槽；没有槽时追加）。

    参数:
        obj: 对象；material: 材质
    返回:
        obj
    """
    if obj is None or material is None:
        return obj
    data = getattr(obj, "data", None)
    if data is None:
        return obj
    try:
        mats = data.materials
    except Exception:
        return obj
    if mats is None:
        return obj
    try:
        if len(mats) == 0:
            mats.append(material)
        else:
            mats[0] = material
    except Exception as exc:
        _warn("assign 失败: %r" % (exc,))
    return obj


def assign_all(objects, material):
    """给一组对象全部赋予同一材质。

    参数:
        objects: 对象列表（None 会被跳过）
        material: 材质
    返回:
        None
    """
    for obj in (objects or []):
        if obj is not None:
            assign(obj, material)


# ---------------------------------------------------------------------------
# 4.5 渲染
# ---------------------------------------------------------------------------

def _image_pixel_stats(img):
    """读取 bpy Image 的像素，返回 (mean, std, black_ratio)，均按 0-255 尺度、忽略透明像素。"""
    w = int(img.size[0]) if img.size[0] else 0
    h = int(img.size[1]) if img.size[1] else 0
    total = w * h
    if total <= 0:
        return 0.0, 0.0, 1.0
    try:
        import numpy as np
    except Exception:
        np = None
    if np is not None:
        try:
            buf = np.empty(total * 4, dtype=np.float32)
            img.pixels.foreach_get(buf)
            px = buf.reshape(total, 4)
            rgb = px[:, :3].astype(np.float64) * 255.0
            lum = rgb[:, 0] * 0.2126 + rgb[:, 1] * 0.7152 + rgb[:, 2] * 0.0722
            alpha = px[:, 3]
            visible = alpha > 0.01
            if bool(visible.any()):
                lum = lum[visible]
            if lum.size == 0:
                return 0.0, 0.0, 1.0
            return (float(lum.mean()), float(lum.std()), float((lum < 8.0).mean()))
        except Exception:
            pass
    # 纯 Python 兜底：按需抽样（>120 万像素时隔点取）
    try:
        px = list(img.pixels)
    except Exception as exc:
        _warn("读取渲染像素失败: %r" % (exc,))
        return 0.0, 0.0, 1.0
    stride = 1 if total <= 1200000 else 2
    lums = []
    step = 4 * stride
    n = len(px) - 3
    for i in range(0, n, step):
        if px[i + 3] > 0.01:
            lums.append((px[i] * 0.2126 + px[i + 1] * 0.7152 + px[i + 2] * 0.0722) * 255.0)
    if not lums:
        return 0.0, 0.0, 1.0
    cnt = float(len(lums))
    mean = sum(lums) / cnt
    var = sum((v - mean) ** 2 for v in lums) / cnt
    black = sum(1 for v in lums if v < 8.0) / cnt
    return (float(mean), float(math.sqrt(var)), float(black))


def _image_stats(path):
    """读取图片文件，返回渲染统计字典（含 path/width/height/bytes/mean/std/black_ratio）。"""
    stats = {
        "path": str(path), "width": 0, "height": 0, "bytes": 0,
        "mean": 0.0, "std": 0.0, "black_ratio": 1.0,
    }
    if not path or not os.path.exists(path):
        _warn("渲染统计: 文件不存在 %r" % (path,))
        return stats
    stats["bytes"] = int(os.path.getsize(path))
    img = None
    try:
        img = bpy.data.images.load(path)
        stats["width"] = int(img.size[0])
        stats["height"] = int(img.size[1])
        mean, std, black = _image_pixel_stats(img)
        stats["mean"] = round(mean, 4)
        stats["std"] = round(std, 4)
        stats["black_ratio"] = round(black, 4)
    except Exception as exc:
        _warn("渲染统计失败 %r: %r" % (path, exc))
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass
    return stats


def setup_render(engine="CYCLES", samples=48, resolution=(960, 960), transparent=False,
                 denoise=True, film_exposure=1.0, color_look="AgX - Medium High Contrast"):
    """配置渲染引擎与输出参数。

    参数:
        engine: "CYCLES" | "EEVEE" | "WORKBENCH"（大小写不敏感；非法值回退 CYCLES）
        samples: 采样数（CYCLES samples / EEVEE taa_render_samples）
        resolution: (宽, 高) 像素
        transparent: True 时渲染透明背景（film_transparent）
        denoise: CYCLES 是否开降噪（优先 OPENIMAGEDENOISE）
        film_exposure:  ViewSettings 曝光值
        color_look: 色彩 look；当前版本不接受时回退 "None"，不报错
    返回:
        dict（实际生效的 engine/samples/resolution/... 参数）
    """
    sc = _scene()
    req = str(engine or "CYCLES").strip().upper()
    eng = _ENGINE_MAP.get(req, req)
    if eng not in ("CYCLES", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        _warn("setup_render: 未知引擎 %r，回退 CYCLES" % (engine,))
        eng = "CYCLES"
    actual = "CYCLES"
    try:
        sc.render.engine = eng
        actual = sc.render.engine
    except Exception as exc:
        _warn("setup_render: 引擎 %r 不可用（%r），回退 CYCLES" % (eng, exc))
        try:
            sc.render.engine = "CYCLES"
            actual = "CYCLES"
        except Exception:
            actual = getattr(sc.render, "engine", "UNKNOWN")
    try:
        rx = max(int(resolution[0]), 1)
        ry = max(int(resolution[1]), 1)
    except Exception:
        rx = ry = 960
    try:
        sc.render.resolution_x = rx
        sc.render.resolution_y = ry
        sc.render.resolution_percentage = 100
        sc.render.image_settings.file_format = 'PNG'
    except Exception as exc:
        _warn("setup_render: 分辨率设置失败 %r" % (exc,))
    samples = max(1, int(samples))
    if actual == "CYCLES":
        cy = getattr(sc, "cycles", None)
        if cy is not None:
            try:
                cy.device = 'CPU'
            except Exception:
                pass
            try:
                cy.samples = samples
            except Exception:
                pass
            try:
                cy.use_adaptive_sampling = True
            except Exception:
                pass
            if denoise:
                try:
                    cy.use_denoising = True
                except Exception:
                    pass
                denoiser_ok = False
                for dname in ("OPENIMAGEDENOISE", "OPTIX"):
                    try:
                        cy.denoiser = dname
                        denoiser_ok = True
                        break
                    except Exception:
                        continue
                if not denoiser_ok:
                    _warn("setup_render: 没有可用降噪器，关闭降噪")
                    try:
                        cy.use_denoising = False
                    except Exception:
                        pass
            else:
                try:
                    cy.use_denoising = False
                except Exception:
                    pass
    elif actual == "BLENDER_EEVEE":
        try:
            sc.eevee.taa_render_samples = samples
        except Exception as exc:
            _warn("setup_render: EEVEE 采样设置失败 %r" % (exc,))
    else:  # BLENDER_WORKBENCH
        try:
            shading = sc.display.shading
            shading.light = 'STUDIO'
            shading.color_type = 'MATERIAL'
            shading.show_shadows = True
            shading.show_cavity = True
        except Exception as exc:
            _warn("setup_render: WORKBENCH 设置失败 %r" % (exc,))
    try:
        sc.render.film_transparent = bool(transparent)
    except Exception:
        pass
    exposure = 1.0
    try:
        sc.view_settings.exposure = float(film_exposure)
        exposure = float(sc.view_settings.exposure)
    except Exception as exc:
        _warn("setup_render: 曝光设置失败 %r" % (exc,))
    applied_look = "None"
    if color_look:
        try:
            sc.view_settings.look = str(color_look)
            applied_look = sc.view_settings.look
        except Exception:
            try:
                sc.view_settings.look = 'None'
            except Exception:
                pass
            applied_look = "None"
            _warn("setup_render: color_look %r 不被当前版本接受，回退 None" % (color_look,))
    view_transform = "UNKNOWN"
    try:
        view_transform = sc.view_settings.view_transform
    except Exception:
        pass
    info = {
        "engine": actual,
        "engine_requested": req,
        "samples": samples,
        "resolution": [rx, ry],
        "transparent": bool(transparent),
        "denoise": bool(denoise),
        "film_exposure": exposure,
        "look": applied_look,
        "color_look": color_look,
        "view_transform": view_transform,
        "image_format": "PNG",
    }
    _STATE["render_setup"] = dict(info)
    _log("渲染设置: engine=%s samples=%d res=%dx%d denoise=%s look=%s" %
         (actual, samples, rx, ry, denoise, applied_look))
    return info


def render_still(path, camera=None, label=None):
    """渲染单帧并写 PNG，随后读回图像统计（用于自动判断是否全黑）。

    参数:
        path: 输出 PNG 路径（相对路径会转成绝对路径；无扩展名时自动按 .png 找）
        camera: 可选相机；给了就临时设为场景相机
        label: 统计里的标签，默认取文件名
    返回:
        dict: {"path","width","height","bytes","mean","std","black_ratio","label"}
        mean/std 为 0-255 尺度亮度；black_ratio 为亮度 <8/255 的像素占比（透明像素不计入）。
    """
    sc = _scene()
    absp = os.path.abspath(os.fspath(path))
    _ensure_dir_for(absp)
    if camera is not None:
        try:
            sc.camera = camera
        except Exception as exc:
            _warn("render_still: 设置相机失败 %r" % (exc,))
    if sc.camera is None:
        _warn("render_still: 场景没有相机，自动创建一台")
        add_camera()
    try:
        sc.render.image_settings.file_format = 'PNG'
    except Exception:
        pass
    sc.render.filepath = absp
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    seconds = round(time.time() - t0, 3)
    final = absp
    if not os.path.exists(final) and os.path.exists(final + ".png"):
        final = final + ".png"
    stats = _image_stats(final)
    stats["label"] = str(label) if label is not None else os.path.splitext(
        os.path.basename(final))[0]
    record = dict(stats)
    record["seconds"] = seconds
    _STATE["renders"].append(record)
    _log("渲染完成 %s (%.2fs, %dx%d, bytes=%d, std=%.2f, black=%.3f)" % (
        final, seconds, stats["width"], stats["height"], stats["bytes"],
        stats["std"], stats["black_ratio"]))
    return {k: stats[k] for k in ("path", "width", "height", "bytes",
                                  "mean", "std", "black_ratio", "label")}


def _maybe_reconfigure_render(engine=None, samples=None, resolution=None):
    """按需用 setup_render 覆盖渲染参数（缺省沿用上次 setup_render 的值）。"""
    if engine is None and samples is None and resolution is None:
        return None
    cur = dict(_STATE.get("render_setup") or {})
    return setup_render(
        engine=engine if engine is not None else (cur.get("engine_requested") or "CYCLES"),
        samples=int(samples if samples is not None else cur.get("samples", 48)),
        resolution=tuple(resolution if resolution is not None else cur.get("resolution", (960, 960))),
        transparent=bool(cur.get("transparent", False)),
        denoise=bool(cur.get("denoise", True)),
        film_exposure=float(cur.get("film_exposure", 1.0)),
        color_look=cur.get("look", "AgX - Medium High Contrast"),
    )


def _frame_objects():
    """取景目标：场景里所有有几何体、且不是地台的对象。"""
    out = []
    for o in _scene().objects:
        try:
            if o.type in _GEOMETRY_TYPES and o.get("kit_role") != "floor":
                out.append(o)
        except Exception:
            continue
    return out


def _aim_camera(cam, targets, direction, margin=1.15):
    """把相机放到 bbox 中心 + direction 方向上，并用 fit_camera 自动取景。"""
    bpy.context.view_layer.update()
    lo, hi = world_bbox(targets)
    if lo is None:
        center = Vector((0.0, 0.0, 0.0))
        radius = 1.0
    else:
        center = Vector(((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5,
                         (lo[2] + hi[2]) * 0.5))
        radius = max((Vector(hi) - Vector(lo)).length * 0.5, 0.05)
    dirv = Vector((float(direction[0]), float(direction[1]), float(direction[2])))
    if dirv.length < 1e-9:
        dirv = Vector((0.0, 1.0, 0.2))
    dirv.normalize()
    cam.location = center + dirv * max(radius * 3.0, 1.0)
    look_at(cam, center)
    if targets:
        fit_camera(cam, targets, margin=margin)
    else:
        try:
            cam.data.clip_end = max(float(cam.data.clip_end), 100.0)
        except Exception:
            pass


def render_views(out_dir, prefix="view", views=("front", "right", "iso"), camera=None,
                 engine=None, samples=None, resolution=None):
    """按视角渲染多张预览图（front=+Y 前方、right=+X 右侧、iso=前右上方）。

    参数:
        out_dir: 输出目录（不存在会自动创建）
        prefix: 文件名前缀 -> <out_dir>/<prefix>-<view>.png
        views: 视角名元组（front/right/left/back/iso，未知名字按 iso 处理）
        camera: 可选相机；None 时用场景当前相机（没有就自动创建）
        engine/samples/resolution: 可选，覆盖 setup_render 的设置
        （取景目标是场景中除地台外的所有几何对象；拍完恢复原相机与原设置）
    返回:
        render_still 返回字典的列表
    """
    out_dir = os.path.abspath(os.fspath(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    _maybe_reconfigure_render(engine, samples, resolution)
    sc = _scene()
    cam = camera if camera is not None else sc.camera
    created = False
    if cam is None:
        _warn("render_views: 场景没有相机，自动创建一台")
        cam = add_camera()
        created = True
    old_scene_camera = sc.camera
    old_loc = cam.location.copy()
    old_rot = cam.rotation_euler.copy()
    old_clip = (float(cam.data.clip_start), float(cam.data.clip_end))
    old_ortho = float(getattr(cam.data, "ortho_scale", 0.0))
    targets = _frame_objects()
    results = []
    try:
        for view in views:
            vname = str(view).lower()
            direction = _VIEW_DIRECTIONS.get(vname)
            if direction is None:
                _warn("render_views: 未知视角 %r，按 iso 处理" % (view,))
                vname = "iso"
                direction = _VIEW_DIRECTIONS["iso"]
            _aim_camera(cam, targets, direction)
            path = os.path.join(out_dir, "%s-%s.png" % (prefix, vname))
            results.append(render_still(path, camera=cam, label=vname))
    finally:
        try:
            cam.location = old_loc
            cam.rotation_euler = old_rot
            cam.data.clip_start = old_clip[0]
            cam.data.clip_end = old_clip[1]
            if old_ortho > 0:
                cam.data.ortho_scale = old_ortho
            sc.camera = old_scene_camera
        except Exception as exc:
            _warn("render_views: 恢复相机失败 %r" % (exc,))
    return results


def render_turntable(out_dir, prefix="turn", count=6, elevation=20.0, **kw):
    """绕场景中心拍一圈转台图（角度从正前方 +Y 开始递增，逆时针绕 Z）。

    参数:
        out_dir: 输出目录
        prefix: 文件名前缀 -> <out_dir>/<prefix>-00.png ...
        count: 张数（>=1）
        elevation: 相机仰角（度）
        **kw: camera / engine / samples / resolution / margin 可选覆盖
    返回:
        render_still 返回字典的列表
    """
    out_dir = os.path.abspath(os.fspath(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    kw = dict(kw or {})
    cam = kw.pop("camera", None)
    engine = kw.pop("engine", None)
    samples = kw.pop("samples", None)
    resolution = kw.pop("resolution", None)
    margin = float(kw.pop("margin", 1.15))
    if kw:
        _warn("render_turntable: 忽略未知参数 %r" % (sorted(kw.keys()),))
    _maybe_reconfigure_render(engine, samples, resolution)
    sc = _scene()
    if cam is None:
        cam = sc.camera
    created = False
    if cam is None:
        _warn("render_turntable: 场景没有相机，自动创建一台")
        cam = add_camera()
        created = True
    old_scene_camera = sc.camera
    old_loc = cam.location.copy()
    old_rot = cam.rotation_euler.copy()
    old_clip = (float(cam.data.clip_start), float(cam.data.clip_end))
    targets = _frame_objects()
    el = math.radians(float(elevation))
    count = max(1, int(count))
    results = []
    try:
        for i in range(count):
            az = 2.0 * math.pi * float(i) / float(count)
            direction = (math.sin(az) * math.cos(el),
                         math.cos(az) * math.cos(el),
                         math.sin(el))
            _aim_camera(cam, targets, direction, margin=margin)
            path = os.path.join(out_dir, "%s-%02d.png" % (prefix, i))
            results.append(render_still(path, camera=cam, label="%s-%02d" % (prefix, i)))
    finally:
        try:
            cam.location = old_loc
            cam.rotation_euler = old_rot
            cam.data.clip_start = old_clip[0]
            cam.data.clip_end = old_clip[1]
            sc.camera = old_scene_camera
        except Exception as exc:
            _warn("render_turntable: 恢复相机失败 %r" % (exc,))
    return results


# ---------------------------------------------------------------------------
# 4.6 导出 / 报告
# ---------------------------------------------------------------------------

def _record_export(kind, path):
    """把导出结果记进 _STATE（供 save_report 使用），返回 {"path","bytes"}。"""
    absp = os.path.abspath(path)
    size = int(os.path.getsize(absp)) if os.path.exists(absp) else 0
    info = {"path": absp, "bytes": size}
    _STATE["exports"][kind] = info
    return info


def _normalize_export_path(path, ext):
    absp = os.path.abspath(os.fspath(path))
    if not absp.lower().endswith(ext.lower()):
        absp += ext
    _ensure_dir_for(absp)
    return absp


def save_blend(path):
    """保存 .blend 工程文件。

    参数:
        path: 输出路径（自动补 .blend 后缀、自动建父目录）
    返回:
        实际保存的绝对路径；失败返回 ""
    """
    _ensure_object_mode()
    absp = _normalize_export_path(path, ".blend")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=absp, check_existing=False)
        if not os.path.exists(absp):
            _warn("save_blend: 文件未生成 %r" % (absp,))
            return ""
        _record_export("blend", absp)
        _log("已保存 blend: %s (%d bytes)" % (absp, os.path.getsize(absp)))
        return absp
    except Exception as exc:
        _warn("save_blend 失败: %r" % (exc,))
        return ""


def export_glb(path):
    """导出 glTF 二进制 .glb（模型/材质；默认不导出相机灯光）。

    参数:
        path: 输出路径（自动补 .glb 后缀）
    返回:
        成功返回绝对路径，失败返回 ""（原因打到 log）
    """
    _ensure_object_mode()
    absp = _normalize_export_path(path, ".glb")
    attempts = [
        dict(filepath=absp, export_format='GLB', use_selection=False, export_apply=True,
             export_cameras=False, export_lights=False, export_yup=True),
        dict(filepath=absp, export_format='GLB'),
    ]
    for i, kwargs in enumerate(attempts):
        try:
            bpy.ops.export_scene.gltf(**kwargs)
            if os.path.exists(absp) and os.path.getsize(absp) > 0:
                _record_export("glb", absp)
                _log("已导出 glb: %s (%d bytes)" % (absp, os.path.getsize(absp)))
                return absp
        except Exception as exc:
            _warn("export_glb 尝试 %d 失败: %r" % (i + 1, exc))
    _warn("export_glb: 最终失败 %r" % (absp,))
    return ""


def export_stl(path):
    """导出 STL 网格。

    Blender 4.0.2 里 STL 导出器是插件操作符 bpy.ops.export_mesh.stl（4.1+ 才有
    bpy.ops.wm.stl_export），这里自动尝试两种，取可用的那个。

    参数:
        path: 输出路径（自动补 .stl 后缀）
    返回:
        成功返回绝对路径，失败返回 ""
    """
    _ensure_object_mode()
    absp = _normalize_export_path(path, ".stl")
    calls = [
        ("wm.stl_export", dict(filepath=absp)),
        ("export_mesh.stl", dict(filepath=absp, use_selection=False, ascii=False,
                                 use_mesh_modifiers=True)),
    ]
    for op_name, kwargs in calls:
        try:
            mod_name, func_name = op_name.split(".")
            op = getattr(getattr(bpy.ops, mod_name), func_name)
            op(**kwargs)
            if os.path.exists(absp) and os.path.getsize(absp) > 0:
                _record_export("stl", absp)
                _log("已导出 stl: %s (%d bytes)" % (absp, os.path.getsize(absp)))
                return absp
        except Exception as exc:
            _warn("export_stl: %s 不可用/失败: %r" % (op_name, exc))
    _warn("export_stl: 最终失败 %r" % (absp,))
    return ""


def export_fbx(path):
    """导出 FBX（插件 op export_scene.fbx；带修改器求值）。

    参数:
        path: 输出路径（自动补 .fbx 后缀）
    返回:
        成功返回绝对路径，失败返回 ""
    """
    _ensure_object_mode()
    absp = _normalize_export_path(path, ".fbx")
    kwargs = dict(filepath=absp, use_selection=False, use_mesh_modifiers=True,
                  path_mode='AUTO', embed_textures=False)
    try:
        bpy.ops.export_scene.fbx(**kwargs)
        if os.path.exists(absp) and os.path.getsize(absp) > 0:
            _record_export("fbx", absp)
            _log("已导出 fbx: %s (%d bytes)" % (absp, os.path.getsize(absp)))
            return absp
    except Exception as exc:
        _warn("export_fbx 失败: %r" % (exc,))
    _warn("export_fbx: 最终失败 %r" % (absp,))
    return ""


def export_obj(path):
    """导出 Wavefront OBJ（4.0 用 bpy.ops.wm.obj_export，不是旧的 export_scene.obj）。

    参数:
        path: 输出路径（自动补 .obj 后缀）
    返回:
        成功返回绝对路径，失败返回 ""
    """
    _ensure_object_mode()
    absp = _normalize_export_path(path, ".obj")
    kwargs = dict(filepath=absp, export_selected_objects=False, apply_modifiers=True,
                  export_materials=True, export_normals=True, export_uv=True)
    try:
        bpy.ops.wm.obj_export(**kwargs)
        if os.path.exists(absp) and os.path.getsize(absp) > 0:
            _record_export("obj", absp)
            _log("已导出 obj: %s (%d bytes)" % (absp, os.path.getsize(absp)))
            return absp
    except Exception as exc:
        _warn("export_obj 失败: %r" % (exc,))
    _warn("export_obj: 最终失败 %r" % (absp,))
    return ""


def export_all(out_dir, stem="model"):
    """导出交付必需的 blend + glb，并在 out_dir 的上一级保存 report.json。

    参数:
        out_dir: 导出目录（通常是 <输出目录>/exports）
        stem: 文件名主干 -> <out_dir>/<stem>.blend、<out_dir>/<stem>.glb
    返回:
        {"blend": {"path","bytes"}, "glb": {...}, "report": {"path","bytes"}}

    说明：stl/fbx/obj 不是必需导出，调用方需要时自行调 export_stl/export_fbx/export_obj；
    某些格式在特定版本不可用时只记录警告，不中断主流程。
    """
    out_dir = os.path.abspath(os.fspath(out_dir).rstrip("\\/") or ".")
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    blend_path = save_blend(os.path.join(out_dir, "%s.blend" % stem))
    result["blend"] = {"path": blend_path,
                       "bytes": int(os.path.getsize(blend_path)) if blend_path and os.path.exists(blend_path) else 0}
    glb_path = export_glb(os.path.join(out_dir, "%s.glb" % stem))
    result["glb"] = {"path": glb_path,
                     "bytes": int(os.path.getsize(glb_path)) if glb_path and os.path.exists(glb_path) else 0}
    report_dir = os.path.dirname(out_dir)
    if not report_dir:
        report_dir = out_dir
    report_path = save_report(report_dir)
    result["report"] = {"path": report_path,
                        "bytes": int(os.path.getsize(report_path)) if os.path.exists(report_path) else 0}
    if not result["blend"]["path"] or not result["glb"]["path"]:
        _warn("export_all: blend 或 glb 导出失败，请检查 log")
    return result


def scene_report():
    """汇总当前场景统计（供 report.json / 自动校验）。

    返回:
        {
          "object_count": 场景全部对象数,
          "mesh_count": 网格对象数（不含 kit_role='floor' 的地台）,
          "camera_count", "light_count",
          "total_verts", "total_tris", "non_manifold_edges": 网格统计（不含地台）,
          "dimensions": [x,y,z] 包围盒尺寸（不含地台；无几何体时全 0）,
          "bbox_min", "bbox_max": 包围盒（不含地台；无几何体时全 0）,
          "materials": [材质名...],
          "blender_version": str,
          "engine": 当前渲染引擎标识
        }
    """
    sc = _scene()
    objs = list(sc.objects)
    floor_tagged = []
    for o in objs:
        try:
            if o.get("kit_role") == "floor":
                floor_tagged.append(o)
        except Exception:
            pass
    model_meshes = [o for o in objs if o.type == 'MESH' and o not in floor_tagged]
    total_verts = 0
    total_tris = 0
    non_manifold = 0
    for o in model_meshes:
        st = mesh_stats(o)
        total_verts += int(st["verts"])
        total_tris += int(st["tris"])
        non_manifold += int(st["non_manifold_edges"])
    bbox_objs = [o for o in objs if o.type in _GEOMETRY_TYPES and o not in floor_tagged]
    lo, hi = world_bbox(bbox_objs)
    if lo is None:
        dimensions = [0.0, 0.0, 0.0]
        bbox_min = [0.0, 0.0, 0.0]
        bbox_max = [0.0, 0.0, 0.0]
    else:
        dimensions = [round(hi[i] - lo[i], 6) for i in range(3)]
        bbox_min = [round(lo[i], 6) for i in range(3)]
        bbox_max = [round(hi[i], 6) for i in range(3)]
    mats = []
    seen = set()
    for o in objs:
        data = getattr(o, "data", None)
        if data is None:
            continue
        try:
            slot_mats = list(getattr(data, "materials", []) or [])
        except Exception:
            slot_mats = []
        for m in slot_mats:
            if m is None:
                continue
            try:
                if m.name not in seen:
                    seen.add(m.name)
                    mats.append(m.name)
            except Exception:
                continue
    engine = "UNKNOWN"
    try:
        engine = sc.render.engine
    except Exception:
        pass
    return {
        "object_count": len(objs),
        "mesh_count": len(model_meshes),
        "camera_count": len([o for o in objs if o.type == 'CAMERA']),
        "light_count": len([o for o in objs if o.type == 'LIGHT']),
        "total_verts": total_verts,
        "total_tris": total_tris,
        "non_manifold_edges": non_manifold,
        "dimensions": dimensions,
        "bbox_min": bbox_min,
        "bbox_max": bbox_max,
        "materials": mats,
        "blender_version": bpy.app.version_string,
        "engine": engine,
    }


def save_report(out_dir, extra=None):
    """把场景统计 + 渲染统计 + 导出结果 + 参数写进 <out_dir>/report.json。

    参数:
        out_dir: 报告目录（不存在会自动创建）
        extra: 可选 dict，合并进 report["params"]（可放建模参数）；同时原样写进 report["extra"]
    返回:
        report.json 的绝对路径
    """
    out_dir = os.path.abspath(os.fspath(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    scene = scene_report()
    report = dict(scene)
    report["scene"] = dict(scene)
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["stage"] = stage()
    report["renders"] = [dict(r) for r in _STATE["renders"]]
    report["exports"] = {k: dict(v) for k, v in _STATE["exports"].items()}
    params = dict(_STATE.get("render_setup") or {})
    if isinstance(extra, dict):
        params.update(extra)
        report["extra"] = dict(extra)
    report["params"] = params
    report["warnings"] = list(_STATE["warnings"])
    report["kit_version"] = KIT_VERSION
    path = os.path.join(out_dir, "report.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        _log("已保存报告: %s" % path)
    except Exception as exc:
        _warn("save_report 写文件失败: %r" % (exc,))
        return ""
    return path


def script_args():
    """返回 sys.argv 中 "--" 之后的透传参数列表（没有则返回 []）。"""
    argv = list(sys.argv)
    if "--" in argv:
        idx = argv.index("--")
        return list(argv[idx + 1:])
    return []


def stage():
    """返回当前构建阶段：环境变量 BLENDER_STAGE（小写），缺省 "full"。"""
    value = str(os.environ.get("BLENDER_STAGE") or "full").strip().lower()
    return value or "full"


# ---------------------------------------------------------------------------
# 增补工具函数（公开 API 之外的小工具，方便写建模脚本；可放心使用）
# ---------------------------------------------------------------------------

def select_only(obj):
    """【增补】只选中 obj（并设为活动对象）。返回 obj。"""
    _activate(obj)
    return obj


def delete(obj):
    """【增补】删除对象（安全处理 None / 已删除对象）。返回 None。"""
    if obj is None:
        return None
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception as exc:
        _warn("delete 失败: %r" % (exc,))
    return None


def sit_on_floor(obj, floor_z=0.0):
    """【增补】把一个对象沿 Z 平移，使其世界包围盒底部正好落在 floor_z 上。返回 obj。"""
    if obj is None:
        return obj
    lo, hi = world_bbox([obj])
    if lo is None:
        return obj
    try:
        obj.location.z += float(floor_z) - lo[2]
    except Exception as exc:
        _warn("sit_on_floor 失败: %r" % (exc,))
    return obj


def set_text_font(obj, font_path):
    """【增补】给文字对象加载字体文件（.ttf/.otf，中文文字必须显式指定中文字体）。

    参数:
        obj: FONT 类型对象
        font_path: 字体文件绝对路径
    返回:
        obj（失败原样返回并记警告）
    """
    if obj is None or str(getattr(obj, "type", "")) != 'FONT':
        _warn("set_text_font: 对象不是文字对象")
        return obj
    try:
        if not os.path.exists(font_path):
            _warn("set_text_font: 字体文件不存在 %r" % (font_path,))
            return obj
        font = bpy.data.fonts.load(font_path)
        obj.data.font = font
    except Exception as exc:
        _warn("set_text_font 失败: %r" % (exc,))
    return obj


def kit_info():
    """【增补】返回运行环境信息字典：kit 版本 / Blender 版本 / Python 版本。"""
    return {
        "kit_version": KIT_VERSION,
        "blender_version": bpy.app.version_string,
        "python_version": sys.version.split()[0],
        "engine": getattr(_scene().render, "engine", "UNKNOWN"),
    }


__all__ = [
    # 4.1
    "reset_scene", "setup_world", "setup_studio_lights", "setup_floor",
    "add_camera", "look_at", "fit_camera", "setup_scene",
    # 4.2
    "cube", "cylinder", "sphere", "cone", "torus", "plane", "tube", "text",
    # 4.3
    "place", "rotate", "translate", "scale_obj", "apply_transform", "shade_smooth",
    "shade_flat", "apply_modifiers", "join", "duplicate", "add_bevel", "add_subsurf",
    "add_mirror", "add_solidify", "add_array", "add_boolean", "add_displace",
    "set_origin", "mesh_stats",
    # 4.4
    "mat", "assign", "assign_all",
    # 4.5
    "setup_render", "render_still", "render_views", "render_turntable",
    # 4.6
    "save_blend", "export_glb", "export_stl", "export_fbx", "export_obj",
    "export_all", "scene_report", "save_report", "script_args", "stage",
    # 增补
    "world_bbox", "select_only", "delete", "sit_on_floor", "set_text_font", "kit_info",
    "KIT_VERSION",
]
