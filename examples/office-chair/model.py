# -*- coding: utf-8 -*-
"""office-chair — 办公转椅（实测样例 / few-shot 参考）。

本脚本是 blender-modeling 技能的第二个实测样例，演示「多部件 + 修改器 + 分组 join」的完整流程：
    1. reset_scene() 清空场景，setup_scene() 搭灯光/相机，setup_floor() 自建深灰地台；
    2. 底座用循环阵列 5 条腿 + 5 个脚轮（cube/cylinder 组合，绕 Z 每 72° 一份）；
    3. 座垫/靠背用 cube + add_bevel 倒圆角，先 apply_modifiers 再 join（join 会丢修改器）；
    4. 按逻辑组 join（base / lift / seat / back / arms）并各自 set_origin(BOTTOM)；
    5. stage 分档：build 只建模 / render 出 512 预览 / full 再导出 blend+glb 与 report.json。

运行（在 <技能目录> 下执行；路径全部走环境变量，不写死绝对路径）：
    python scripts/run_blender.py --script "<本文件>" --out "<本目录>" --stage build
    python scripts/run_blender.py --script "<本文件>" --out "<本目录>" --stage render
    python scripts/run_blender.py --script "<本文件>" --out "<本目录>" --stage full
"""

import math
import os
import sys

# --- 技能目录与输出目录：只从环境变量推导，禁止硬编码 -------------------------
SKILL_DIR = os.environ.get("BLENDER_SKILL_DIR", "")
KIT_DIR = os.environ.get("BLENDER_KIT_DIR", os.path.join(SKILL_DIR, "lib"))
if KIT_DIR and KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

from blender_kit import (  # noqa: E402  （kit 必须先加入 sys.path 才能 import）
    add_bevel,
    apply_modifiers,
    cone,
    cube,
    cylinder,
    export_all,
    join,
    mat,
    render_views,
    reset_scene,
    save_report,
    scene_report,
    set_origin,
    setup_floor,
    setup_scene,
    stage,
)

OUT_DIR = os.environ.get("BLENDER_OUT_DIR", os.path.join(os.getcwd(), "blender-models", "office-chair"))
RENDERS_DIR = os.path.join(OUT_DIR, "renders")
EXPORTS_DIR = os.path.join(OUT_DIR, "exports")

# --- 全部尺寸 / 颜色 / 渲染参数集中在这里 -----------------------------------
# 单位：1 Blender unit = 1 米。整椅约 0.95 m 高（真实人体工学椅尺度）。
# 朝向：座面朝 +Y（render_views 的 front 相机在 +Y），靠背在 -Y 侧。
PARAMS = {
    "scene": {  # 相机/灯光；render_views 会自动按模型 bbox 重新取景
        "target": (0.0, 0.0, 0.50),
        "distance": 3.0,  # 只影响灯光半径 max(distance*0.8, 1.0)
        "azimuth": -45.0,
        "elevation": 20.0,
        "lens": 50.0,
        "studio": True,
        "floor": False,  # 地台自己建（见 floor 块）
    },
    "floor": {"size": 12.0, "color": (0.07, 0.075, 0.085), "roughness": 0.55},
    "base": {  # 五爪底座 + 脚轮
        "hub_radius": 0.065,
        "hub_depth": 0.060,
        "hub_z": 0.090,
        "hub_vertices": 16,
        "leg_count": 5,
        "leg_length": 0.300,
        "leg_width": 0.050,
        "leg_thickness": 0.035,
        "leg_z": 0.075,
        "caster_radius": 0.032,
        "caster_width": 0.022,
        "caster_vertices": 12,
    },
    "lift": {  # 气压杆 + 防尘罩
        "radius": 0.028,
        "height": 0.300,
        "z_center": 0.270,
        "vertices": 16,
        "shroud_radius1": 0.060,
        "shroud_radius2": 0.038,
        "shroud_height": 0.120,
        "shroud_z": 0.180,
    },
    "seat": {  # 座垫
        "size": (0.500, 0.480, 0.090),
        "z": 0.400,
        "bevel": 0.025,
        "bevel_segments": 3,
    },
    "back": {  # 靠背 + 两根支撑柱
        "size": (0.460, 0.070, 0.500),
        "y": -0.210,
        "z": 0.700,
        "tilt": 8.0,
        "bevel": 0.028,
        "bevel_segments": 3,
        "post_size": (0.050, 0.060, 0.180),
        "post_x": 0.130,
        "post_y": -0.190,
        "post_z": 0.460,
    },
    "arm": {  # 两侧扶手：立柱 + 扶手垫
        "x": 0.255,
        "post_size": (0.045, 0.050, 0.200),
        "post_y": 0.020,
        "post_z": 0.500,
        "pad_size": (0.075, 0.260, 0.035),
        "pad_y": -0.010,
        "pad_z": 0.615,
        "pad_bevel": 0.012,
        "pad_bevel_segments": 2,
    },
    "colors": {
        # 深色网布/织物 + 中灰金属 + 近黑脚轮；在三点布光下深色仍有形体和轮廓光
        "fabric": (0.050, 0.055, 0.065),
        "frame": (0.280, 0.290, 0.310),
        "rubber": (0.020, 0.020, 0.022),
    },
    "render": {
        "engine": "CYCLES",
        "views": ("front", "right", "iso"),
        # 样例仓库只保留 512 预览图（体积约束）；真实交付项目按模板再加 final 960 终渲
        "preview": {"resolution": 512, "samples": 16, "denoise": True},
    },
    "export": {"stem": "model"},
}


def _build_base(frame, rubber):
    """五爪底座：中心轮毂 + 5 条放射状腿 + 5 个脚轮，合并成 `office-chair_base`。"""
    b = PARAMS["base"]
    parts = []

    # 中心轮毂（竖直圆柱）
    parts.append(
        cylinder(
            "chair_hub",
            radius=b["hub_radius"],
            depth=b["hub_depth"],
            vertices=b["hub_vertices"],
            location=(0.0, 0.0, b["hub_z"]),
            material=frame,
        )
    )

    # 绕 Z 轴每 360/count 度复制一条腿 + 一个脚轮
    for i in range(int(b["leg_count"])):
        angle = 360.0 * i / float(b["leg_count"])
        rad = math.radians(angle)
        cx, cy = math.cos(rad), math.sin(rad)
        # 腿：cube 的局部 X 轴当长度方向，中心放在半径一半处
        parts.append(
            cube(
                "chair_leg_%02d" % i,
                size=(b["leg_length"], b["leg_width"], b["leg_thickness"]),
                location=(cx * b["leg_length"] / 2.0, cy * b["leg_length"] / 2.0, b["leg_z"]),
                rotation=(0.0, 0.0, angle),
                material=frame,
            )
        )
        # 脚轮：圆柱轴向转到切向（rotX=90 让轴水平，再 rotZ=angle 转到切向），轮底正好 z=0
        parts.append(
            cylinder(
                "chair_caster_%02d" % i,
                radius=b["caster_radius"],
                depth=b["caster_width"],
                vertices=b["caster_vertices"],
                location=(cx * b["leg_length"], cy * b["leg_length"], b["caster_radius"]),
                rotation=(90.0, 0.0, angle),
                material=rubber,
            )
        )

    base = join(parts, "office-chair_base")
    set_origin(base, "BOTTOM")
    return base


def _build_lift(frame):
    """气压杆 + 防尘罩，合并成 `office-chair_lift`。"""
    lp = PARAMS["lift"]
    gas = cylinder(
        "chair_gas",
        radius=lp["radius"],
        depth=lp["height"],
        vertices=lp["vertices"],
        location=(0.0, 0.0, lp["z_center"]),
        material=frame,
    )
    shroud = cone(
        "chair_shroud",
        radius1=lp["shroud_radius1"],
        radius2=lp["shroud_radius2"],
        depth=lp["shroud_height"],
        vertices=lp["vertices"],
        location=(0.0, 0.0, lp["shroud_z"]),
        material=frame,
    )
    lift = join([gas, shroud], "office-chair_lift")
    set_origin(lift, "BOTTOM")
    return lift


def _build_seat(fabric):
    """座垫：cube + 倒圆角（先 apply_modifiers，避免 join 时丢修改器）。"""
    s = PARAMS["seat"]
    seat = cube(
        "office-chair_seat",
        size=s["size"],
        location=(0.0, 0.0, s["z"]),
        material=fabric,
    )
    add_bevel(seat, width=s["bevel"], segments=int(s["bevel_segments"]), angle_limit=30.0)
    apply_modifiers(seat)
    set_origin(seat, "BOTTOM")
    return seat


def _build_back(fabric, frame):
    """靠背 + 两根支撑柱，合并成 `office-chair_back`；靠背整体后仰 tilt 度。"""
    bk = PARAMS["back"]
    parts = []
    backrest = cube(
        "chair_backrest",
        size=bk["size"],
        location=(0.0, bk["y"], bk["z"]),
        rotation=(bk["tilt"], 0.0, 0.0),  # 绕 X 后仰，顶部向 -Y
        material=fabric,
    )
    add_bevel(backrest, width=bk["bevel"], segments=int(bk["bevel_segments"]), angle_limit=30.0)
    apply_modifiers(backrest)
    parts.append(backrest)

    for sign in (-1.0, 1.0):
        parts.append(
            cube(
                "chair_back_post_%s" % ("l" if sign < 0 else "r"),
                size=bk["post_size"],
                location=(sign * bk["post_x"], bk["post_y"], bk["post_z"]),
                material=frame,
            )
        )

    back = join(parts, "office-chair_back")
    set_origin(back, "BOTTOM")
    return back


def _build_arms(frame):
    """两侧扶手（立柱 + 扶手垫），合并成 `office-chair_arms`。"""
    ar = PARAMS["arm"]
    parts = []
    for sign in (-1.0, 1.0):
        side = "l" if sign < 0 else "r"
        parts.append(
            cube(
                "chair_arm_post_%s" % side,
                size=ar["post_size"],
                location=(sign * ar["x"], ar["post_y"], ar["post_z"]),
                material=frame,
            )
        )
        pad = cube(
            "chair_arm_pad_%s" % side,
            size=ar["pad_size"],
            location=(sign * ar["x"], ar["pad_y"], ar["pad_z"]),
            material=frame,
        )
        add_bevel(pad, width=ar["pad_bevel"], segments=int(ar["pad_bevel_segments"]), angle_limit=40.0)
        apply_modifiers(pad)
        parts.append(pad)

    arms = join(parts, "office-chair_arms")
    set_origin(arms, "BOTTOM")
    return arms


def build():
    """建出整椅，返回场景对象列表（部件表见 brief.md）。"""
    reset_scene()

    sc = PARAMS["scene"]
    setup_scene(
        target=sc["target"],
        distance=sc["distance"],
        azimuth=sc["azimuth"],
        elevation=sc["elevation"],
        lens=sc["lens"],
        studio=sc["studio"],
        floor=sc["floor"],
    )
    fl = PARAMS["floor"]
    setup_floor(size=fl["size"], color=fl["color"], roughness=fl["roughness"])

    colors = PARAMS["colors"]
    fabric = mat("chair_fabric", color=colors["fabric"], roughness=0.82)
    frame = mat("chair_frame", color=colors["frame"], metallic=0.70, roughness=0.35)
    rubber = mat("chair_rubber", color=colors["rubber"], roughness=0.85)

    base = _build_base(frame, rubber)
    lift = _build_lift(frame)
    seat = _build_seat(fabric)
    back = _build_back(fabric, frame)
    arms = _build_arms(frame)
    return [base, lift, seat, back, arms]


def render_preview():
    """三视角 512×512 预览渲染。"""
    cfg = PARAMS["render"]["preview"]
    size = int(cfg["resolution"])
    return render_views(
        RENDERS_DIR,
        prefix="view",
        views=tuple(PARAMS["render"]["views"]),
        engine=PARAMS["render"]["engine"],
        samples=int(cfg["samples"]),
        resolution=(size, size),
    )


def main():
    st = stage()  # build / render / full
    objects = build()
    rep = scene_report()
    print(
        "[office-chair] objects=%d meshes=%d tris=%d dims=(%.3f, %.3f, %.3f)"
        % (
            rep["object_count"],
            rep["mesh_count"],
            rep["total_tris"],
            rep["dimensions"][0],
            rep["dimensions"][1],
            rep["dimensions"][2],
        )
    )

    if st in ("render", "full"):
        renders = render_preview()
        print("[office-chair] renders=%d" % len(renders))

    if st == "full":
        # 真实交付示例还会在这里加 final 960 终渲；样例仓库只保留 3 张 512 预览图
        exported = export_all(EXPORTS_DIR, stem=PARAMS["export"]["stem"])
        report_path = save_report(
            OUT_DIR,
            extra={"slug": "office-chair", "objects": [o.name for o in objects], "params": PARAMS},
        )
        print("[office-chair] exports=%s" % sorted(exported.keys()))
        print("[office-chair] report=%s" % report_path)


if __name__ == "__main__":
    main()
