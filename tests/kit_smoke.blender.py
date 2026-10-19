# -*- coding: utf-8 -*-
"""kit 冒烟测试：在真实 Blender 里把 blender_kit 的公开 API 全量跑一遍。

这个脚本**不进 CI**（CI 不需要 Blender），是给改了 kit / 模板 / 导出逻辑之后
手动回归用的。它不产出交付物，只验证 API 行为与导出管线。

在技能目录下运行（产物写工作区临时目录，不污染技能目录）：

    python scripts/run_blender.py --script tests/kit_smoke.blender.py \
        --out "<工作区>/blender-models/_kit-smoke" --stage build --timeout 180

约定：通过时最后打印 ``KIT SMOKE OK``；失败抛 RuntimeError 并以非 0 退出。
"""

import json
import os
import struct
import sys

KIT_DIR = os.environ.get("BLENDER_KIT_DIR", "")
if KIT_DIR and KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

import blender_kit as kit  # noqa: E402

OUT = os.environ.get("BLENDER_OUT_DIR", os.path.join(os.getcwd(), "kit-smoke-out"))
RENDERS = os.path.join(OUT, "renders")
EXPORTS = os.path.join(OUT, "exports")
FAILS = []


def check(cond, label, extra=""):
    if cond:
        print("[SMOKE PASS] %s %s" % (label, extra))
    else:
        FAILS.append(label)
        print("[SMOKE FAIL] %s %s" % (label, extra))


def glb_json(path):
    raw = open(path, "rb").read()
    magic, version, _total = struct.unpack("<4sII", raw[:12])
    check(magic == b"glTF" and version == 2, "glb 头部合法", "%r v%d" % (magic, version))
    clen, _ctype = struct.unpack("<I4s", raw[12:20])
    return json.loads(raw[20:20 + clen].decode("utf-8"))


def build_scene():
    """用全部图元 + 修改器搭一个场景，返回对象列表。"""
    kit.reset_scene()
    kit.setup_scene(target=(0, 0, 0.45), distance=3.2, azimuth=-45.0,
                    elevation=22.0, lens=50.0, studio=True, floor=True)

    body_mat = kit.mat("smoke_body", color=(0.55, 0.62, 0.72), roughness=0.35)
    accent = kit.mat("smoke_accent", color=(0.90, 0.45, 0.10), roughness=0.45,
                     metallic=0.2)
    glass = kit.mat("smoke_glass", color=(0.9, 0.9, 0.95), roughness=0.1,
                    metallic=0.0, alpha=0.35)

    objs = []
    # 基底 + 倒角
    base = kit.cube("base", size=(1.2, 0.9, 0.10), location=(0, 0, 0.05),
                    material=body_mat)
    kit.add_bevel(base, width=0.012, segments=2, angle_limit=25.0)
    kit.apply_modifiers(base)
    objs.append(base)

    # 圆柱 + 细分曲面
    col = kit.cylinder("column", radius=0.08, depth=0.55, vertices=24,
                       location=(0, 0, 0.45), material=accent)
    kit.add_subsurf(col, levels=1)
    kit.apply_modifiers(col)
    objs.append(col)

    # 球 + 位移
    ball = kit.sphere("ball", radius=0.18, segments=24, rings=12,
                      location=(0.38, 0.0, 0.30), material=body_mat)
    kit.add_displace(ball, strength=0.01, noise_scale=0.5, texture_type="CLOUDS")
    kit.apply_modifiers(ball)
    objs.append(ball)

    # 圆锥 + 平滑
    cone = kit.cone("cone", radius1=0.14, radius2=0.0, depth=0.32, vertices=20,
                    location=(-0.42, 0.0, 0.28), rotation=(0.0, 0.0, 15.0),
                    material=accent)
    kit.shade_smooth(cone)
    objs.append(cone)

    # 圆环 + 镜像
    ring = kit.torus("ring", major_radius=0.16, minor_radius=0.035,
                     location=(0.0, -0.32, 0.25), rotation=(90.0, 0.0, 0.0),
                     material=glass)
    kit.add_mirror(ring, axis="X")
    kit.apply_modifiers(ring)
    objs.append(ring)

    # 阵列 + 实心化
    plate = kit.plane("plate", size=0.5, location=(0.0, 0.36, 0.012),
                      material=accent)
    kit.add_array(plate, count=3, offset=(0.0, 0.12, 0.0))
    kit.add_solidify(plate, thickness=0.012)
    kit.apply_modifiers(plate)
    objs.append(plate)

    # 布尔：cube 减 sphere
    cut_target = kit.cube("cut_target", size=(0.24, 0.24, 0.24),
                          location=(0.55, 0.42, 0.14), material=body_mat)
    cutter = kit.sphere("cutter", radius=0.16, segments=20, rings=10,
                        location=(0.55, 0.42, 0.20))
    kit.add_boolean(cut_target, cutter, operation="DIFFERENCE", apply=True)
    objs.append(cut_target)

    # 管（曲线转网格）
    tube = kit.tube("pipe", [(0.0, 0.55, 0.02), (0.0, 0.85, 0.02)],
                    radius=0.02, material=accent)
    objs.append(tube)

    # 文字（英文用默认字体；中文必须自己 set_text_font）
    sign = kit.text("sign", body="SMOKE", size=0.16, extrude=0.01,
                    location=(-0.5, 0.45, 0.06), rotation=(90.0, 0.0, 0.0),
                    material=accent)
    objs.append(sign)

    # 变换 / 复制 / 落地 / 原点
    kit.place(ball, scale=(1.0, 1.0, 0.85))
    dup = kit.duplicate(ball, name="ball_dup", location=(-0.38, 0.0, 0.30))
    objs.append(dup)
    kit.translate(dup, (0.0, -0.1, 0.0))
    kit.rotate(dup, 0.0, 0.0, 20.0)
    kit.scale_obj(dup, (0.8, 0.8, 0.8))
    kit.apply_transform(dup)
    kit.sit_on_floor(dup)
    kit.set_origin(dup, "BOTTOM")

    # 合并 / 选择 / 删除
    merged = kit.join([ball, dup], "merged_balls")
    objs = [o for o in objs if o not in (ball, dup)] + [merged]
    kit.shade_flat(merged)
    trash = kit.cube("trash", size=(0.05, 0.05, 0.05), location=(2, 2, 5))
    trash_name = trash.name  # delete 后 RNA 指针失效，名字必须先取出来
    kit.delete(trash)
    kit.select_only(merged)
    check(trash_name not in [o.name for o in kit._scene().objects], "delete 生效")

    for o in objs:
        stats = kit.mesh_stats(o) if o.type == "MESH" else None
        if stats:
            check(stats.get("tris", 0) > 0, "mesh_stats 正常", "%s tris=%s" % (o.name, stats.get("tris")))
    lo, hi = kit.world_bbox(objs)
    check(lo is not None and hi is not None and lo[2] >= -0.01, "world_bbox 正常", "lo=%r" % (lo,))
    return objs


def main():
    os.makedirs(RENDERS, exist_ok=True)
    os.makedirs(EXPORTS, exist_ok=True)

    objs = build_scene()
    names = [o.name for o in objs]
    print("[SMOKE] objects=%r" % (names,))

    # ---- 渲染 ----
    kit.setup_render(engine="CYCLES", samples=8, resolution=(160, 160))
    still = os.path.join(RENDERS, "smoke-still.png")
    kit.render_still(still, label="smoke")
    check(os.path.exists(still) and os.path.getsize(still) > 2048, "render_still 出图",
          "%d B" % (os.path.getsize(still) if os.path.exists(still) else 0))
    views = kit.render_views(RENDERS, prefix="view", views=("front", "right", "iso"),
                            engine="CYCLES", samples=8, resolution=(160, 160))
    check(len(views) == 3, "render_views 出 3 张图", "%d" % len(views))

    # ---- 报告 ----
    rep = kit.scene_report()
    check(rep.get("mesh_count", 0) >= 8, "scene_report mesh_count", "%d" % rep.get("mesh_count", 0))
    check(rep.get("total_tris", 0) > 100, "scene_report total_tris", "%d" % rep.get("total_tris", 0))
    check(len(rep.get("dimensions", [])) == 3 and rep["dimensions"][2] > 0,
          "scene_report dimensions", "%r" % (rep.get("dimensions"),))

    # ---- 导出 ----
    blend = kit.save_blend(os.path.join(EXPORTS, "smoke.blend"))
    check(bool(blend) and os.path.getsize(blend) > 10240, "save_blend",
          "%d B" % (os.path.getsize(blend) if blend else 0))
    glb = kit.export_glb(os.path.join(EXPORTS, "smoke.glb"))
    check(bool(glb) and os.path.getsize(glb) > 256, "export_glb",
          "%d B" % (os.path.getsize(glb) if glb else 0))
    js = glb_json(glb)
    node_names = [n.get("name", "") for n in js.get("nodes", [])]
    check(not any("Floor" in n for n in node_names), "glb 不含摄影棚地台",
          "nodes=%d" % len(node_names))
    stl = kit.export_stl(os.path.join(EXPORTS, "smoke.stl"))
    check(bool(stl) and os.path.getsize(stl) > 256, "export_stl",
          "%d B" % (os.path.getsize(stl) if stl else 0))
    obj = kit.export_obj(os.path.join(EXPORTS, "smoke.obj"))
    check(bool(obj) and os.path.getsize(obj) > 256, "export_obj",
          "%d B" % (os.path.getsize(obj) if obj else 0))
    fbx = kit.export_fbx(os.path.join(EXPORTS, "smoke.fbx"))
    check(bool(fbx) and os.path.getsize(fbx) > 256, "export_fbx",
          "%d B" % (os.path.getsize(fbx) if fbx else 0))
    exported = kit.export_all(os.path.join(EXPORTS, "all"), stem="model")
    check(bool(exported["blend"]["path"]) and bool(exported["glb"]["path"]),
          "export_all 产出 blend+glb")
    report_path = kit.save_report(OUT, extra={"slug": "kit-smoke"})
    check(os.path.exists(report_path), "save_report 落盘", os.path.basename(report_path))
    data = json.load(open(report_path, encoding="utf-8"))
    check(data.get("object_count", 0) >= 8, "report.json 结构正常")

    # ---- open_blend 回环：打开刚才的 blend，对象应全部回来 ----
    before = len(kit._scene().objects)
    info = kit.open_blend(exported["blend"]["path"])
    check(info.get("object_count") == before, "open_blend 对象数一致",
          "%d == %d" % (info.get("object_count", -1), before))
    check(kit.kit_info().get("kit_version") == kit.KIT_VERSION, "kit_info 版本一致")

    print("=" * 60)
    if FAILS:
        raise RuntimeError("SMOKE FAILED: %r" % (FAILS,))
    print("KIT SMOKE OK")


if __name__ == "__main__":
    main()
