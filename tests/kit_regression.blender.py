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

print("")
if _failures:
    print("KIT REGRESSION FAILED: %d/%d 项未通过 -> %r" % (len(_failures), _checks[0], _failures))
    raise SystemExit(1)
print("KIT REGRESSION OK (%d checks)" % _checks[0])
