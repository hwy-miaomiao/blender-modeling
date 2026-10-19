# -*- coding: utf-8 -*-
"""model_template.py — Blender 建模脚本骨架（复制到 <输出目录>/model.py 后改 PART 部分）。

用途
----
这是 blender-modeling 技能的标准建模脚本骨架：所有几何、材质、灯光、相机、渲染、
导出都写在脚本里，删掉输出目录后重跑同一条命令即可复现同一模型。默认示例是一个
低多边形马克杯（杯身 + 杯柄），验证「图元 → 修改器 → 合并 → 材质 → 多视角渲染 →
导出 → 报告」全链路。

复制方式
--------
    Copy-Item "<技能目录>\\templates\\model_template.py" "$OUT\\model.py"

运行方式（由 scripts/run_blender.py 调用，也可直接调 Blender）
------------------------------------------------------------
    python scripts/run_blender.py --script "$OUT\\model.py" --out "$OUT" --stage build
    python scripts/run_blender.py --script "$OUT\\model.py" --out "$OUT" --stage render
    python scripts/run_blender.py --script "$OUT\\model.py" --out "$OUT" --stage full

环境变量（run_blender.py 会自动注入）
------------------------------------
    BLENDER_KIT_DIR    kit 的 lib 目录（必需；缺失时回退本文件同级的 ../lib）
    BLENDER_OUT_DIR    输出目录（缺省 <cwd>/blender-models/example-mug）
    BLENDER_STAGE      build | render | full（缺省 full）

三档 stage
----------
    build   只建模，不渲染、不导出（最快，用于查语法/API/几何错误）
    render  建模 + 512x512/16spp 的 view-front/right/iso 三视角预览图
    full    建模 + 预览三视角 + 960x960/48spp 的 final-* 终渲 + exports/model.blend/.glb
            + report.json（scene_report + 渲染统计 + 导出记录）

改模型从哪下手
--------------
    1. 改 PARAMS：尺寸/颜色/位置/采样数/分辨率全集中在顶部，函数体里不写魔法数字。
    2. 改 build()：按 brief.md 的部件表逐个写图元 + 修改器；同逻辑组用 join() 合并，
       再 set_origin(group, "BOTTOM")，方便摆放与检查。
    3. 改 main()：一般不需要动；只有新增交付物（如 stl 导出）时才改。
"""
import os
import sys

# ---------------------------------------------------------------------------
# 路径与 kit 导入（只用环境变量推导，禁止硬编码绝对路径）
# ---------------------------------------------------------------------------
KIT_DIR = os.environ.get("BLENDER_KIT_DIR", "")
if not KIT_DIR:
    # 回退 1：由 BLENDER_SKILL_DIR 推导；回退 2：本文件 ../lib（模板与 lib 同级）
    skill_dir = os.environ.get("BLENDER_SKILL_DIR", "")
    if skill_dir:
        KIT_DIR = os.path.join(skill_dir, "lib")
    else:
        KIT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
KIT_DIR = os.path.abspath(KIT_DIR)
if KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

from blender_kit import (  # noqa: E402  （必须放在 sys.path 处理之后）
    add_bevel,
    apply_modifiers,
    assign,
    cylinder,
    export_all,
    join,
    mat,
    render_views,
    reset_scene,
    save_report,
    scene_report,
    script_args,
    set_origin,
    setup_render,
    setup_scene,
    stage,
    torus,
)

OUT_DIR = os.environ.get("BLENDER_OUT_DIR", os.path.join(os.getcwd(), "blender-models", "example-mug"))
RENDERS_DIR = os.path.join(OUT_DIR, "renders")
EXPORTS_DIR = os.path.join(OUT_DIR, "exports")

# ---------------------------------------------------------------------------
# PARAMS：全部可调参数集中在这里（单位：米 / 度）
# ---------------------------------------------------------------------------
PARAMS = {
    # 场景与相机
    "scene": {
        "target": (0.0, 0.0, 0.048),   # 相机注视点（模型几何中心附近）
        "distance": 3.0,               # 相机到注视点距离
        "azimuth": -45.0,              # 水平方位角（-45 = 前右 45 度）
        "elevation": 25.0,             # 仰角
        "lens": 50.0,                  # 焦距 mm
        "studio": True,                # 三灯棚拍
        "floor": True,                 # 地台
    },
    # 主体层：杯身
    "mug": {
        "radius": 0.045,
        "height": 0.090,
        "vertices": 24,
        "bevel_width": 0.004,
        "bevel_segments": 2,
    },
    # 附件层：杯柄
    "handle": {
        "major_radius": 0.030,
        "minor_radius": 0.006,
        "offset_x": 0.048,
        "height_ratio": 0.55,          # 杯柄中心高度 = 杯高 * 该比例
    },
    # 材质（0-1 RGB）
    "colors": {
        "body": (0.92, 0.92, 0.90),
        "accent": (0.20, 0.45, 0.75),
    },
    # 渲染
    "render": {
        "engine": "CYCLES",
        "views": ("front", "right", "iso"),
        "preview": {"resolution": 512, "samples": 16, "denoise": True},
        "final": {"resolution": 960, "samples": 48, "denoise": True},
    },
    # 导出
    "export": {"stem": "model"},
}


# ---------------------------------------------------------------------------
# 可选命令行覆盖：python scripts/run_blender.py ... -- --distance 3.5 --samples 8
# ---------------------------------------------------------------------------
def apply_cli_overrides():
    """读取 `--` 之后的透传参数，覆盖 PARAMS 中的少量调试项（只支持下列键）。"""
    argv = script_args()
    i = 0
    while i < len(argv):
        key = argv[i]
        if key in ("--distance", "--preview-size", "--samples") and i + 1 < len(argv):
            try:
                value = float(argv[i + 1])
            except (TypeError, ValueError):
                print("[template][WARN] 参数 %s 的值不是数字：%r" % (key, argv[i + 1]))
                i += 1
                continue
            if key == "--distance":
                PARAMS["scene"]["distance"] = value
            elif key == "--preview-size":
                PARAMS["render"]["preview"]["resolution"] = max(32, int(value))
            else:  # --samples 只影响预览档，避免误伤终渲
                PARAMS["render"]["preview"]["samples"] = max(1, int(value))
            i += 2
        else:
            i += 1


# ---------------------------------------------------------------------------
# 建模：改这里
# ---------------------------------------------------------------------------
def build():
    """搭建场景并返回主体对象列表（供渲染取景与报告使用）。

    结构（对应 brief.md 的部件表）：
        主体层  mug_body   圆柱 r=0.045 h=0.09 + 倒角
        附件层  mug_handle 圆环 R=0.03 r=0.006，绕 X 轴 90 度竖起来
        场景层  地台/三灯/相机（由 setup_scene 统一生成）
    合并成一个对象 mug，并把 origin 放到「底部中心」，方便后续摆放。
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

    colors = PARAMS["colors"]
    body_mat = mat("mug_white", color=colors["body"], roughness=0.35)
    accent_mat = mat("mug_accent", color=colors["accent"], roughness=0.4)

    # ---- 主体层：杯身 ----
    mug = PARAMS["mug"]
    body = cylinder(
        "mug_body",
        radius=mug["radius"],
        depth=mug["height"],
        vertices=mug["vertices"],
        location=(0.0, 0.0, mug["height"] / 2.0),
        material=body_mat,
    )
    add_bevel(body, width=mug["bevel_width"], segments=mug["bevel_segments"])
    apply_modifiers(body)

    # ---- 附件层：杯柄 ----
    h = PARAMS["handle"]
    handle = torus(
        "mug_handle",
        major_radius=h["major_radius"],
        minor_radius=h["minor_radius"],
        location=(h["offset_x"], 0.0, mug["height"] * h["height_ratio"]),
        rotation=(90.0, 0.0, 0.0),  # 绕 X 轴转 90 度，让圆环立在 XZ 平面
        material=accent_mat,
    )

    # ---- 合并逻辑组：一个对象，origin 在底部中心 ----
    mug_obj = join([body, handle], "mug")
    set_origin(mug_obj, mode="BOTTOM")
    assign(mug_obj, body_mat)
    return [mug_obj]


# ---------------------------------------------------------------------------
# 渲染 / 导出 / 报告：一般不需要改
# ---------------------------------------------------------------------------
def _render_preview():
    """渲染 512x512 预览三视角 -> renders/view-<view>.png。"""
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


def _render_final():
    """渲染 960x960 终渲三视角 -> renders/final-<view>.png。"""
    cfg = PARAMS["render"]["final"]
    size = int(cfg["resolution"])
    setup_render(
        engine=PARAMS["render"]["engine"],
        samples=int(cfg["samples"]),
        resolution=(size, size),
        denoise=bool(cfg["denoise"]),
    )
    return render_views(
        RENDERS_DIR,
        prefix="final",
        views=tuple(PARAMS["render"]["views"]),
        engine=PARAMS["render"]["engine"],
        samples=int(cfg["samples"]),
        resolution=(size, size),
    )


def main():
    """按 BLENDER_STAGE 分档执行：build 只建模 / render 加预览 / full 全量交付。"""
    apply_cli_overrides()
    st = str(stage()).strip().lower()
    print("[template] 开始 stage=%s" % st)
    print("[template] KIT_DIR=%s" % KIT_DIR)
    print("[template] OUT_DIR=%s" % OUT_DIR)

    objects = build()
    report = scene_report()
    print("[template] 建模完成：objects=%d mesh=%d tris=%d dims=%r"
          % (report.get("object_count", 0), report.get("mesh_count", 0),
             report.get("total_tris", 0), report.get("dimensions")))
    if not objects:
        print("[template][WARN] build() 没有返回任何对象")

    if st in ("render", "full"):
        renders = _render_preview()
        print("[template] 预览渲染完成：%d 张" % len(renders))

    if st == "full":
        finals = _render_final()
        print("[template] 终渲完成：%d 张" % len(finals))
        exported = export_all(EXPORTS_DIR, stem=PARAMS["export"]["stem"])  # 内部已写 report.json
        print("[template] 导出完成：blend=%r glb=%r"
              % (exported.get("blend", {}).get("bytes"), exported.get("glb", {}).get("bytes")))
        report_path = save_report(OUT_DIR, extra={"slug": "example-mug", "params": PARAMS})  # 覆盖并补充 extra 字段
        print("[template] 报告已写入：%s" % report_path)

    print("[template] 结束 stage=%s" % st)


if __name__ == "__main__":
    main()
