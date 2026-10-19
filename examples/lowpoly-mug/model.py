# -*- coding: utf-8 -*-
"""lowpoly-mug — 低多边形马克杯（实测样例 / few-shot 参考）。

本脚本是 blender-modeling 技能的「标准流程」参考实现，演示：
    1. reset_scene() 清空场景；
    2. setup_scene() 一次搭好 世界 + 三点灯 + 地台 + 相机；
    3. 只用 kit 图元建部件，每个部件建件时就赋自己的材质（join 会保留材质槽）；
    4. 修改器先 apply_modifiers 再 join，join 后 set_origin(BOTTOM)；
    5. stage 分档：build 只建模 / render 出 512 预览 / full 再导出 blend+glb 与 report.json。

运行（在 <技能目录> 下执行；不写死任何绝对路径，路径全部走环境变量）：
    python scripts/run_blender.py --script "<本文件>" --out "<本目录>" --stage build
    python scripts/run_blender.py --script "<本文件>" --out "<本目录>" --stage render
    python scripts/run_blender.py --script "<本文件>" --out "<本目录>" --stage full
"""

import os
import sys

# --- 技能目录与输出目录：只从环境变量推导，禁止硬编码 -------------------------
SKILL_DIR = os.environ.get("BLENDER_SKILL_DIR", "")
KIT_DIR = os.environ.get("BLENDER_KIT_DIR", os.path.join(SKILL_DIR, "lib"))
if KIT_DIR and KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

from blender_kit import (  # noqa: E402  （kit 必须先加入 sys.path 才能 import）
    add_bevel,
    add_boolean,
    apply_modifiers,
    cylinder,
    export_all,
    join,
    mat,
    render_views,
    reset_scene,
    rotate,
    save_report,
    scene_report,
    set_origin,
    setup_floor,
    setup_scene,
    stage,
    torus,
)

OUT_DIR = os.environ.get("BLENDER_OUT_DIR", os.path.join(os.getcwd(), "blender-models", "lowpoly-mug"))
RENDERS_DIR = os.path.join(OUT_DIR, "renders")
EXPORTS_DIR = os.path.join(OUT_DIR, "exports")

# --- 全部尺寸 / 颜色 / 渲染参数集中在这里 -----------------------------------
# 单位：1 Blender unit = 1 米。杯子总高约 0.10 m（真实马克杯尺度）。
PARAMS = {
    "scene": {  # 相机/灯光；render_views 会自动按模型 bbox 重新取景
        "target": (0.0, 0.0, 0.05),
        "distance": 3.0,   # 只影响灯光半径 max(distance*0.8, 1.0)
        "azimuth": -45.0,
        "elevation": 22.0,
        "lens": 50.0,
        "studio": True,
        "floor": False,    # 地台自己建（见 floor 块），默认灰地台会让白杯糊在背景里
    },
    "floor": {"size": 12.0, "color": (0.07, 0.075, 0.085), "roughness": 0.55},
    "body": {  # 杯身：实心圆柱 → 布尔挖出杯腔
        "radius": 0.045,
        "height": 0.091,
        "vertices": 24,
        "wall_thickness": 0.006,
        "bottom_thickness": 0.008,
        "cavity_depth": 0.120,  # 顶部高出杯口，保证布尔完全切开
        "rim_bevel": 0.0012,
        "rim_segments": 2,
    },
    "foot": {"radius": 0.043, "height": 0.008},  # 底圈（强调色）
    "handle": {  # 杯柄：竖立的圆环，装在 +X 侧
        "major_radius": 0.027,
        "minor_radius": 0.0055,
        "offset_x": 0.047,
        "height_ratio": 0.55,
        "yaw_deg": -35.0,  # 整体绕 Z 转一点，让 front/right/iso 三个视角都能看到杯柄圆环
    },
    "colors": {
        "ceramic": (0.86, 0.86, 0.84),
        "accent": (0.16, 0.40, 0.70),
    },
    "render": {
        "engine": "CYCLES",
        "views": ("front", "right", "iso"),
        # 样例仓库只保留 512 预览图（体积约束）；真实交付项目按模板再加 final 960 终渲
        "preview": {"resolution": 512, "samples": 16, "denoise": True},
    },
    "export": {"stem": "model"},
}


def build():
    """建出马克杯并返回场景对象列表。

    部件表（与 brief.md 对应）：
        P01 mug_body   主体   圆柱 + 布尔挖腔 + 杯口倒角
        P02 mug_cavity 工具   布尔 cutter（用完自动删除）
        P03 mug_foot   细节   底圈
        P04 mug_handle 附件   圆环杯柄
    合并为单个对象 `mug`，origin 落在杯底中心。
    """
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
    # 产品图常用的深灰地台：比 kit 默认的 0.35 灰更暗，白色主体才有分离度
    fl = PARAMS["floor"]
    setup_floor(size=fl["size"], color=fl["color"], roughness=fl["roughness"])

    colors = PARAMS["colors"]
    ceramic = mat("mug_ceramic", color=colors["ceramic"], roughness=0.30)
    accent = mat("mug_accent", color=colors["accent"], roughness=0.38)

    body_p = PARAMS["body"]
    foot_p = PARAMS["foot"]
    foot_h = foot_p["height"]

    # P03 底圈：薄圆柱垫在杯身下方，让整体落在一个小台阶上
    foot = cylinder(
        "mug_foot",
        radius=foot_p["radius"],
        depth=foot_h,
        vertices=body_p["vertices"],
        location=(0.0, 0.0, foot_h / 2.0),
        material=accent,
    )

    # P01 杯身：先建实心圆柱
    body = cylinder(
        "mug_body",
        radius=body_p["radius"],
        depth=body_p["height"],
        vertices=body_p["vertices"],
        location=(0.0, 0.0, foot_h + body_p["height"] / 2.0),
        material=ceramic,
    )

    # P02 布尔 cutter：内腔圆柱。半径 = 外半径 - 壁厚；底部留 bottom_thickness 杯底。
    # 注意：cutter 必须带材质——布尔新生成的面会继承 cutter 的材质槽索引，
    # 不带材质时这些面会拿到非法索引（渲染花屏/串色），这里给同一个陶瓷材质即可归入槽 0。
    cavity_radius = body_p["radius"] - body_p["wall_thickness"]
    cavity_z = foot_h + body_p["bottom_thickness"]
    cutter = cylinder(
        "mug_cavity",
        radius=cavity_radius,
        depth=body_p["cavity_depth"],
        vertices=body_p["vertices"],
        location=(0.0, 0.0, cavity_z + body_p["cavity_depth"] / 2.0),
        material=ceramic,
    )
    add_boolean(body, cutter, operation="DIFFERENCE", apply=True)  # apply=True 时 cutter 自动删除

    # 杯口倒角：让杯沿有一圈高光，低多边形也不显得像刀片
    add_bevel(
        body,
        width=body_p["rim_bevel"],
        segments=body_p["rim_segments"],
        angle_limit=25.0,
    )
    # join 会丢掉非活动对象的修改器，所以先把杯身倒角烘焙进网格
    apply_modifiers(body)

    # P04 杯柄：圆环竖起来（rotation X=90° 让圆环平面变成 XZ 平面），装在 +X 侧杯壁上
    h = PARAMS["handle"]
    handle = torus(
        "mug_handle",
        major_radius=h["major_radius"],
        minor_radius=h["minor_radius"],
        location=(h["offset_x"], 0.0, foot_h + body_p["height"] * h["height_ratio"]),
        rotation=(90.0, 0.0, 0.0),
        material=accent,
    )

    # 合并成一个对象：材质槽随 join 保留（各部件建件时已指定，join 后不要再 assign）
    mug = join([body, foot, handle], "mug")
    # 整体绕 Z 轴偏转：front 视角能看见杯柄轮廓，right/iso 视角能看见圆环开口
    rotate(mug, 0.0, 0.0, h["yaw_deg"])
    set_origin(mug, "BOTTOM")  # origin 落到杯底，方便后续摆放
    return [mug]


def render_preview():
    """三视角 512×512 预览渲染，测试与样例仓库都用它。"""
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
        "[lowpoly-mug] objects=%d tris=%d dims=(%.3f, %.3f, %.3f)"
        % (
            rep["object_count"],
            rep["total_tris"],
            rep["dimensions"][0],
            rep["dimensions"][1],
            rep["dimensions"][2],
        )
    )

    if st in ("render", "full"):
        renders = render_preview()
        print("[lowpoly-mug] renders=%d" % len(renders))

    if st == "full":
        # 真实交付示例还会在这里加 final 960 终渲；样例仓库只保留 3 张 512 预览图
        exported = export_all(EXPORTS_DIR, stem=PARAMS["export"]["stem"])
        report_path = save_report(
            OUT_DIR,
            extra={"slug": "lowpoly-mug", "objects": [o.name for o in objects], "params": PARAMS},
        )
        print("[lowpoly-mug] exports=%s" % sorted(exported.keys()))
        print("[lowpoly-mug] report=%s" % report_path)


if __name__ == "__main__":
    main()
