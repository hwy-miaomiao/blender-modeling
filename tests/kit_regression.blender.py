# -*- coding: utf-8 -*-
"""kit 回归测试：覆盖 kit-auditor 的 15 条 FINDINGS 及报告路径修复。

手动运行（需要 Blender，不进 CI）：

    python scripts/run_blender.py --script tests/kit_regression.blender.py \
        --out blender-models/_kit-regression --stage build --timeout 300

成功时最后一行打印 `KIT REGRESSION OK`，任何失败以非 0 退出。
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(line_buffering=True)

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.environ.get("BLENDER_KIT_DIR"),
           os.path.join(os.environ.get("BLENDER_SKILL_DIR", ""), "lib"),
           os.path.join(os.path.dirname(_HERE), "lib"),
           _HERE):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import bpy
import blender_kit as kit

OUT_DIR = os.environ.get("BLENDER_OUT_DIR") or os.path.join(_HERE, "_kit_regression_out")
os.makedirs(os.path.join(OUT_DIR, "exports"), exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "renders"), exist_ok=True)

_failures = []
_checks = [0]


def check(name, cond, extra=""):
    _checks[0] += 1
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  " + str(extra)) if extra else ""))
    if not ok:
        _failures.append(name)
    return ok


def warnings_text():
    try:
        return " | ".join(str(w) for w in kit._STATE.get("warnings", []))
    except Exception:
        return ""


def obj_dims(o):
    try:
        return tuple(round(v, 4) for v in o.dimensions)
    except Exception:
        return ()


# ---------- F05 命名自撞 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
a = kit.cube("Cube", size=0.4)
check("F05 cube('Cube') 不带 .001", a.name == "Cube", a.name)
b = kit.text("Text", body="A")
check("F05 text('Text') 不带 .001", b.name == "Text", b.name)
t1 = kit.tube("TubeA", points=[(0, 0, 0), (0, 0, 0.3)], radius=0.02)
t2 = kit.tube("TubeB", points=[(0.2, 0, 0), (0.2, 0, 0.3)], radius=0.02)
check("F05 两个 tube 名字互不重复", t1.name != t2.name, (t1.name, t2.name))
j1 = kit.join([kit.cube("J1", size=0.1), kit.cube("J2", size=0.1)], "Joined")
j2 = kit.join([j1], "Joined")
check("F05 join 后改名不带 .001", j2.name == "Joined", j2.name)

# ---------- F09 cube size 兜底 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
c = kit.cube("Sized", size=(1, 2))
check("F09 cube(size=(1,2)) 补齐为 3 元组",
      tuple(round(v, 4) for v in obj_dims(c)) == (1.0, 2.0, 2.0), obj_dims(c))

# ---------- F10 look_at 重合 ----------
cam = kit.add_camera(location=(3.0, 0.0, 0.5), target=(0, 0, 0.2))
kit.look_at(cam, cam.location)
check("F10 look_at 相机与目标重合时给出警告",
      "look_at: 相机与目标点重合" in warnings_text())

# ---------- F01 add_mirror bisect=False 不切原始几何 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
m = kit.cube("MirrorMe", size=(1.4, 0.4, 0.4))
for _v in m.data.vertices:  # 几何相对对象原点不对称：x 从 -0.8 到 0.6
    _v.co.x -= 0.1
kit.add_mirror(m, axis="X", bisect=False)
kit.apply_modifiers(m)
bb = kit.world_bbox([m])
xmin, xmax = round(bb[0][0], 3), round(bb[1][0], 3)
check("F01 bisect=False 保留跨镜像面几何（x 约 -0.8..0.8）",
      xmin <= -0.75 and xmax >= 0.75, (xmin, xmax))

# ---------- F02 add_boolean cutter 不进导出 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
body = kit.cube("Body", size=0.6, location=(0, 0, 0.3))
cutter = kit.cylinder("HoleCutter", radius=0.1, depth=0.8, location=(0, 0, 0.35))
kit.add_boolean(body, cutter, operation="DIFFERENCE", apply=False)
glb_path = os.path.join(OUT_DIR, "exports", "bool.glb")
kit.export_glb(glb_path)
data = open(glb_path, "rb").read()
check("F02 glb 不含 cutter 节点", b"HoleCutter" not in data, "bytes=%d" % len(data))
check("F02 cutter 被标记 kit_role='cutter'",
      cutter.get("kit_role") == "cutter", cutter.get("kit_role"))

# ---------- F03 隐藏对象不参与统计/取景 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
hidden = kit.cube("GiantHidden", size=40.0, location=(0, 0, -20))
hidden.hide_render = True
visible = kit.cube("Small", size=0.4, location=(0, 0, 0.2))
rep = kit.scene_report()
dims = rep.get("dimensions") or [0, 0, 0]
check("F03 scene_report 忽略 hide_render 对象", max(dims) <= 1.0, dims)
frame_targets = kit._frame_objects()
check("F03 _frame_objects 只返回可见对象",
      [o.name for o in frame_targets] == ["Small"], [o.name for o in frame_targets])
cam2 = kit.add_camera(location=(3.0, 0.0, 1.0), target=(0, 0, 0.2))
kit.fit_camera(cam2, frame_targets)
dist = round(float((cam2.location - __import__("mathutils").Vector((0, 0, 0.2))).length), 2)
check("F03 fit_camera 不被隐藏 40m 对象推远", dist < 10.0, dist)
check("F03 scene_report mats 不含 FloorMat", "FloorMat" not in (rep.get("materials") or []),
      rep.get("materials"))

# ---------- F04 统计包含修改器 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
f4 = kit.cube("BevelSub", size=0.4)
kit.add_bevel(f4, width=0.01, segments=2)
st = kit.mesh_stats(f4)
check("F04 mesh_stats 统计求值网格（bevel 后三角面 > 12）", st["tris"] > 12, st["tris"])
st_base = kit.mesh_stats(f4, evaluated=False)
check("F04 evaluated=False 仍可拿到基础网格统计", st_base["tris"] == 12, st_base["tris"])

# ---------- F06 export_stl 对非网格给警告 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
kit.text("JustText", body="STL")
n_before = len(kit._STATE.get("warnings", []))
kit.export_stl(os.path.join(OUT_DIR, "exports", "text-only.stl"))
_wt = warnings_text()
check("F06 export_stl 对非网格对象给出警告", "STL 只支持网格" in _wt)
check("F06 该警告只出现一次", _wt.count("STL 只支持网格") == 1, _wt[-200:])

# ---------- F11 render_still 渲染后恢复 scene.camera ----------
kit.reset_scene()
kit.setup_scene(studio=True, floor=True)
kit.setup_render(engine="CYCLES", samples=4, resolution=(96, 96), denoise=False)
cam_a = kit.add_camera(location=(2.2, -1.0, 0.8), target=(0, 0, 0.15))
cam_b = kit.add_camera(location=(4.0, 3.0, 1.5), target=(0, 0, 0.15))
kit._scene().camera = cam_a
kit.cube("F11Thing", size=0.3, location=(0, 0, 0.15))
kit.render_still(os.path.join(OUT_DIR, "renders", "f11.png"), camera=cam_b)
check("F11 render_still 后恢复原相机", kit._scene().camera == cam_a,
      getattr(kit._scene().camera, "name", None))
rec = kit._STATE["renders"][-1]
check("F11 report.renders 记录 engine/resolution/samples",
      rec.get("engine") == "CYCLES" and rec.get("resolution") == [96, 96]
      and rec.get("samples") == 4, (rec.get("engine"), rec.get("resolution"), rec.get("samples")))

# ---------- F07 render_views 恢复渲染设置 ----------
kit.setup_render(engine="CYCLES", samples=8, resolution=(160, 160), denoise=False)
kit.render_views(OUT_DIR, prefix="f07", views=("front",), samples=2, resolution=(64, 64))
sc = kit._scene()
check("F07 render_views 后恢复 samples", int(sc.cycles.samples) == 8, sc.cycles.samples)
check("F07 render_views 后恢复 resolution",
      (int(sc.render.resolution_x), int(sc.render.resolution_y)) == (160, 160),
      (sc.render.resolution_x, sc.render.resolution_y))

# ---------- F08 失效对象不抛异常 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=False)
gone = kit.cube("Gone", size=0.2)
bpy.data.objects.remove(gone, do_unlink=True)
err = None
st_gone = {"tris": -1}
try:
    kit.shade_smooth(gone)
    kit.shade_flat(gone)
    kit.apply_modifiers(gone)
    st_gone = kit.mesh_stats(gone)
    kit.assign(gone, kit.mat("M", color=(0.5, 0.5, 0.5)))
    kit.join([gone], "Joined")
except Exception as exc:
    err = repr(exc)
check("F08 失效对象只警告不抛异常", err is None, err)
check("F08 失效对象统计为空", st_gone.get("tris") == 0, st_gone)

# ---------- F14 scene_report materials 排除地台 ----------
kit.reset_scene()
kit.setup_scene(studio=True, floor=True)
kit.cube("MatTest", size=0.3, material=kit.mat("OnlyMe", color=(0.6, 0.2, 0.2)))
rep2 = kit.scene_report()
check("F14 materials 不含 FloorMat", "FloorMat" not in (rep2.get("materials") or []),
      rep2.get("materials"))

# ---------- setup_floor 幂等 ----------
kit.reset_scene()
kit.setup_scene(studio=False, floor=True)
n1 = len([o for o in kit._scene().objects if o.get("kit_role") == "floor"])
kit.setup_floor()
n2 = len([o for o in kit._scene().objects if o.get("kit_role") == "floor"])
check("setup_floor 幂等（不产生 Floor.001）", n1 == 1 and n2 == 1, (n1, n2))

# ---------- 报告相对路径 ----------
kit.reset_scene()
kit.setup_scene(studio=True, floor=True)
kit.setup_render(engine="CYCLES", samples=4, resolution=(96, 96), denoise=False)
kit.add_camera(location=(2.0, -2.0, 1.0), target=(0, 0, 0.15))
kit.cylinder("RelMug", radius=0.1, depth=0.2, location=(0, 0, 0.1))
kit.render_views(OUT_DIR, prefix="rel", views=("front", "iso"))
kit.export_all(os.path.join(OUT_DIR, "exports"))
kit.save_report(OUT_DIR)
rep3 = json.load(open(os.path.join(OUT_DIR, "report.json"), encoding="utf-8"))
bad = [r.get("path") for r in rep3.get("renders", [])
       if not r.get("path") or os.path.isabs(r["path"]) or ":" in r["path"]]
check("报告 renders 路径为相对路径", not bad, bad)
bad_ex = [v.get("path") for v in rep3.get("exports", {}).values()
          if not v.get("path") or os.path.isabs(v["path"]) or ":" in v["path"]]
check("报告 exports 路径为相对路径", not bad_ex, bad_ex)
check("报告的 renders 文件真实存在",
      all(os.path.isfile(os.path.join(OUT_DIR, r["path"])) for r in rep3.get("renders", [])),
      [r.get("path") for r in rep3.get("renders", [])])

# ---------- F12 open_blend 损坏文件 ----------
# 注意：Blender 打开坏文件时会把 "Error: File format is not supported" 打到自己的
# stderr，run_blender 的日志分类会把它当错误。为了不让预期的负向测试污染日志，
# 这里在独立 Blender 子进程里验证，只检查子进程输出与退出码。
corrupt = os.path.join(OUT_DIR, "corrupt.blend")
with open(corrupt, "wb") as f:
    f.write(b"this is definitely not a blend file")
kit_dir = os.path.dirname(os.path.abspath(kit.__file__))
child_code = (
    "import sys\n"
    "sys.path.insert(0, %r)\n" % kit_dir +
    "import blender_kit as kit\n"
    "r = kit.open_blend(%r)\n" % corrupt +
    "print('F12_CHILD_OK', r == {})\n"
)
try:
    proc = subprocess.run(
        [bpy.app.binary_path, "--background", "--factory-startup",
         "--python-exit-code", "1", "--python-expr", child_code],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, cwd=OUT_DIR)
    child_out = (proc.stdout or "") + (proc.stderr or "")
    check("F12 open_blend 损坏文件在独立进程里返回 {} 不抛异常",
          proc.returncode == 0 and "F12_CHILD_OK True" in child_out,
          (proc.returncode, child_out[-200:]))
except Exception as exc:
    check("F12 open_blend 损坏文件在独立进程里返回 {} 不抛异常", False, repr(exc))
err2 = None
try:
    kit.open_blend(os.path.join(OUT_DIR, "nope-does-not-exist.blend"))
except FileNotFoundError:
    err2 = "FileNotFoundError"
except Exception as exc:
    err2 = repr(exc)
check("F12 open_blend 不存在的文件仍抛 FileNotFoundError", err2 == "FileNotFoundError", err2)

# ---------- F15 渲染设置恢复：调用方从未 setup_render 时也要恢复真实场景设置 ----------
# 场景：手工设置引擎/分辨率/透明/曝光/look/格式/路径（相当于调用方自己的设置），
# 然后 render_views 用 engine/samples/resolution 覆盖渲染；结束后必须逐项恢复原值，
# 且 _STATE["render_setup"] 回到空（不能把覆盖值当"原设置"）。
kit.reset_scene()
_sc = bpy.context.scene
_sc.render.engine = 'BLENDER_EEVEE'
_sc.render.resolution_x = 300
_sc.render.resolution_y = 200
_sc.render.resolution_percentage = 100
_sc.render.film_transparent = True
_sc.render.image_settings.file_format = 'JPEG'
_sc.render.filepath = "//f15-original"
_sc.view_settings.exposure = 1.5
_sc.view_settings.look = 'None'
_sc.eevee.taa_render_samples = 7
kit.cube("f15_cube", size=1.0, location=(0, 0, 0.5))
kit.render_views(os.path.join(OUT_DIR, "renders"), prefix="f15", views=("front",),
                 engine="CYCLES", samples=2, resolution=(64, 64))
check("F15 未 setup_render 时 render_views 恢复渲染引擎", _sc.render.engine == 'BLENDER_EEVEE',
      _sc.render.engine)
check("F15 未 setup_render 时恢复 resolution",
      (_sc.render.resolution_x, _sc.render.resolution_y) == (300, 200),
      (_sc.render.resolution_x, _sc.render.resolution_y))
check("F15 恢复 film_transparent", bool(_sc.render.film_transparent) is True,
      _sc.render.film_transparent)
check("F15 恢复 image_format", _sc.render.image_settings.file_format == 'JPEG',
      _sc.render.image_settings.file_format)
check("F15 恢复 render.filepath", _sc.render.filepath == "//f15-original", _sc.render.filepath)
check("F15 恢复 view exposure", abs(float(_sc.view_settings.exposure) - 1.5) < 1e-6,
      _sc.view_settings.exposure)
check("F15 恢复 view look", _sc.view_settings.look == 'None', _sc.view_settings.look)
check("F15 恢复 eevee taa_render_samples", int(_sc.eevee.taa_render_samples) == 7,
      _sc.eevee.taa_render_samples)
check("F15 render_setup 回到空（不记录覆盖值）",
      kit._STATE.get("render_setup") == {}, kit._STATE.get("render_setup"))

# ---------- F16 视口隐藏但参与渲染的对象必须进 glb/obj，且导出后恢复隐藏 ----------
kit.reset_scene()
kit.cube("f16_vis", size=1.0, location=(0, 0, 0.5))
vp_obj = kit.cube("f16_vp", size=1.0, location=(2, 0, 0.5))
vp_obj.hide_viewport = True
vp_obj.hide_render = False


def _glb_node_names(path):
    import struct
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        return []
    json_len, json_type = struct.unpack_from("<II", data, 12)
    payload = data[20:20 + json_len]
    doc = json.loads(payload.decode("utf-8"))
    names = []
    for n in doc.get("nodes", []):
        if n.get("name"):
            names.append(n["name"])
    return names


targets16 = kit._export_targets()
check("F16 视口隐藏对象仍在导出目标里", vp_obj in targets16,
      [getattr(o, "name", "?") for o in targets16])
glb16 = kit.export_glb(os.path.join(OUT_DIR, "exports", "f16.glb"))
names16 = _glb_node_names(glb16) if glb16 else []
check("F16 视口隐藏对象导出进 glb", bool(glb16) and "f16_vp" in names16, names16)
check("F16 glb 导出后恢复 hide_viewport", bool(vp_obj.hide_viewport), vp_obj.hide_viewport)
obj16 = kit.export_obj(os.path.join(OUT_DIR, "exports", "f16.obj"))
obj_txt16 = ""
try:
    with open(obj16, "r", encoding="utf-8", errors="replace") as f:
        obj_txt16 = f.read()
except Exception:
    pass
check("F16 视口隐藏对象导出进 obj", bool(obj16) and "o f16_vp" in obj_txt16, obj16)
check("F16 obj 导出后恢复 hide_viewport", bool(vp_obj.hide_viewport), vp_obj.hide_viewport)

# ---------- F17 ORTHO 竖幅取景不能横向裁切（ortho_scale 按 sensor_fit 长边换算） ----------
kit.reset_scene()
_f17_obj = kit.cube("f17_obj", size=2.0, location=(0, 0, 1.0))
_f17_sc = bpy.context.scene
_f17_sc.render.resolution_x = 160
_f17_sc.render.resolution_y = 320
_f17_sc.render.resolution_percentage = 100
_f17_cam = kit.add_camera(location=(4, -4, 3))
_f17_cam.data.type = 'ORTHO'
kit.fit_camera(_f17_cam, [_f17_obj], margin=1.2)
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402

_f17_coords = []
for _corner in _f17_obj.bound_box:
    _world = _f17_obj.matrix_world @ __import__("mathutils").Vector(_corner)
    _f17_coords.append(world_to_camera_view(_f17_sc, _f17_cam, _world))
check("F17 ORTHO 竖幅取景全部角点在画面内",
      all(-0.001 <= c.x <= 1.001 and -0.001 <= c.y <= 1.001 for c in _f17_coords),
      [(round(c.x, 3), round(c.y, 3)) for c in _f17_coords])
check("F17 ORTHO ortho_scale 为正值", float(_f17_cam.data.ortho_scale) > 0,
      _f17_cam.data.ortho_scale)

# ---------- F18 render_turntable 也要恢复 ORTHO 相机的 ortho_scale ----------
kit.reset_scene()
kit.cube("f18_obj", size=2.0, location=(0, 0, 1.0))
_f18_sc = bpy.context.scene
_f18_sc.render.resolution_x = 200
_f18_sc.render.resolution_y = 200
_f18_sc.render.resolution_percentage = 100
_f18_cam = kit.add_camera(location=(4, -4, 3))
_f18_cam.data.type = 'ORTHO'
_f18_cam.data.ortho_scale = 7.0
kit.render_turntable(os.path.join(OUT_DIR, "renders"), prefix="f18", count=2,
                     engine="CYCLES", samples=1, resolution=(64, 64))
check("F18 render_turntable 恢复 ORTHO ortho_scale",
      abs(float(_f18_cam.data.ortho_scale) - 7.0) < 1e-6, _f18_cam.data.ortho_scale)
check("F18 render_turntable 后相机仍为 ORTHO", _f18_cam.data.type == 'ORTHO',
      _f18_cam.data.type)

# ---------- F19 mat(update_existing) / assign(all_slots) 材质 API ----------
kit.reset_scene()
_red = kit.mat("f19_red", color=(1.0, 0.0, 0.0), roughness=0.5)
_green = kit.mat("f19_red", color=(0.0, 1.0, 0.0), roughness=0.2, update_existing=True)
_bsdf = _green.node_tree.nodes.get("Principled BSDF")
_base = tuple(round(float(v), 3) for v in _bsdf.inputs["Base Color"].default_value[:3])
_rough = round(float(_bsdf.inputs["Roughness"].default_value), 3)
check("F19 mat(update_existing=True) 复用同一材质", _green is _red, _green.name)
check("F19 mat(update_existing=True) 更新颜色", _base == (0.0, 1.0, 0.0), _base)
check("F19 mat(update_existing=True) 更新粗糙度", _rough == 0.2, _rough)
_blue = kit.mat("f19_blue", color=(0.0, 0.0, 1.0))
_o1 = kit.cube("f19_a", material=_green)
_o2 = kit.cube("f19_b", location=(2, 0, 0), material=_blue)
_joined = kit.join([_o1, _o2], "f19_joined")
_new = kit.mat("f19_new", color=(0.5, 0.5, 0.5))
kit.assign(_joined, _new, all_slots=True)
_slots = list(getattr(_joined.data, "materials", []) or [])
check("F19 assign(all_slots=True) 覆盖全部材质槽",
      len(_slots) >= 2 and all(m == _new for m in _slots),
      [getattr(m, "name", "?") for m in _slots])
kit.assign(_joined, _green)
_slots2 = list(getattr(_joined.data, "materials", []) or [])
check("F19 assign 默认只替换第一个材质槽",
      len(_slots2) >= 2 and _slots2[0] == _green and _slots2[1] == _new,
      [getattr(m, "name", "?") for m in _slots2])

# ---------- F20 render_views(views=字符串) 不能被逐字符迭代 ----------
_RENDERS_DIR = os.path.join(OUT_DIR, "renders")
kit.reset_scene()
kit.cube("f20_obj", size=1.0)
kit.render_views(_RENDERS_DIR, prefix="f20", views="front",
                 engine="CYCLES", samples=1, resolution=(64, 64))
_names20 = sorted(n for n in os.listdir(_RENDERS_DIR) if n.startswith("f20-"))
check("F20 render_views(views='front') 只渲染 front 一张",
      _names20 == ["f20-front.png"], _names20)

# ---------- F21 render_views(views=[]) 必须明确告警，不能静默无输出 ----------
_before21 = len(kit._STATE["warnings"])
_results21 = kit.render_views(_RENDERS_DIR, prefix="f21", views=[],
                              engine="CYCLES", samples=1, resolution=(64, 64))
check("F21 render_views(views=[]) 返回空列表", _results21 == [], _results21)
check("F21 render_views(views=[]) 记录告警",
      len(kit._STATE["warnings"]) > _before21,
      kit._STATE["warnings"][_before21:])

# ---------- F22 render_still 结束后恢复 render.filepath / 图片格式 ----------
kit.reset_scene()
kit.setup_scene(floor=False)
_sc22 = bpy.context.scene
kit.setup_render(engine="CYCLES", samples=1, resolution=(64, 64))
_sc22.render.filepath = "//f22-original"
_sc22.render.image_settings.file_format = 'JPEG'
kit.render_still(os.path.join(_RENDERS_DIR, "f22.png"), label="f22")
check("F22 render_still 恢复 render.filepath",
      _sc22.render.filepath == "//f22-original", _sc22.render.filepath)
check("F22 render_still 恢复 image_settings.file_format",
      _sc22.render.image_settings.file_format == 'JPEG',
      _sc22.render.image_settings.file_format)

# ---------- F23 PERSP + sensor_fit=VERTICAL 取景不能纵向裁切 ----------
kit.reset_scene()
_f23_obj = kit.cube("f23_obj", size=2.0, location=(0, 0, 1.0))
_sc23 = bpy.context.scene
_sc23.render.resolution_x = 200
_sc23.render.resolution_y = 100
_sc23.render.resolution_percentage = 100
_f23_cam = kit.add_camera(location=(4, -4, 3))
_f23_cam.data.type = 'PERSP'
_f23_cam.data.sensor_fit = 'VERTICAL'
_f23_cam.data.sensor_width = 36.0
_f23_cam.data.sensor_height = 24.0
_f23_cam.data.lens = 50.0
kit.fit_camera(_f23_cam, [_f23_obj], margin=1.1)
_coords23 = []
for _corner in _f23_obj.bound_box:
    _world = _f23_obj.matrix_world @ __import__("mathutils").Vector(_corner)
    _coords23.append(world_to_camera_view(_sc23, _f23_cam, _world))
check("F23 PERSP VERTICAL 取景全部角点在画面内",
      all(-0.001 <= c.x <= 1.001 and -0.001 <= c.y <= 1.001 for c in _coords23),
      [(round(c.x, 3), round(c.y, 3)) for c in _coords23])

# ---------- F24 部分覆盖不能把未指定的引擎重置为 CYCLES ----------
kit.reset_scene()
kit.cube("f24_obj", size=1.0)
_sc24 = bpy.context.scene
_sc24.render.engine = 'BLENDER_EEVEE'
_sc24.render.resolution_x = 64
_sc24.render.resolution_y = 64
_old_setup24 = dict(kit._STATE.get("render_setup") or {})
kit._STATE["render_setup"] = {}
try:
    _info24 = kit._maybe_reconfigure_render(samples=2)
finally:
    kit._STATE["render_setup"] = _old_setup24
check("F24 部分覆盖保持当前 EEVEE 引擎",
      bool(_info24) and str(_info24.get("engine")) == 'BLENDER_EEVEE', _info24)
check("F24 部分覆盖应用显式 samples",
      bool(_info24) and int(_info24.get("samples")) == 2, _info24)

# ---------- F25 sensor_fit=AUTO 横/竖幅取景回归 ----------
for _tag25, _rx25, _ry25 in (("横幅", 200, 100), ("竖幅", 100, 200)):
    kit.reset_scene()
    _obj25 = kit.cube("f25_obj", size=2.0, location=(0, 0, 1.0))
    _sc25 = bpy.context.scene
    _sc25.render.resolution_x = _rx25
    _sc25.render.resolution_y = _ry25
    _sc25.render.resolution_percentage = 100
    _cam25 = kit.add_camera(location=(4, -4, 3))
    _cam25.data.sensor_fit = 'AUTO'
    kit.fit_camera(_cam25, [_obj25], margin=1.1)
    _coords25 = []
    for _corner in _obj25.bound_box:
        _world = _obj25.matrix_world @ __import__("mathutils").Vector(_corner)
        _coords25.append(world_to_camera_view(_sc25, _cam25, _world))
    check("F25 AUTO %s取景全部角点在画面内" % _tag25,
          all(-0.001 <= c.x <= 1.001 and -0.001 <= c.y <= 1.001 for c in _coords25),
          [(round(c.x, 3), round(c.y, 3)) for c in _coords25])

print("")
if _failures:
    print("KIT REGRESSION FAILED: %d/%d 项未通过 -> %r" % (len(_failures), _checks[0], _failures))
    raise SystemExit(1)
print("KIT REGRESSION OK (%d checks)" % _checks[0])
