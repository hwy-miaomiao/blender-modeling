# -*- coding: utf-8 -*-
"""edit_model_template.py —— 修改已有模型的模板（不是从零新建）。

用法（技能目录下执行；`--blend` 后面是已有的 .blend 文件）：

    python scripts/run_blender.py --script "<本文件>" --out "<输出目录>" \
        --stage full -- --blend "<已有模型>/exports/model.blend"

三种 stage 与新建流程一致：
    build  -> 只打开 + 改 + 打印统计（不渲染、不导出）
    render -> 再出 3 张 512 预览图
    full   -> 再导出修改后的 blend + glb 和 report.json

自定义方式：只改下面 EDITS 字典（对象名 -> 操作），其余不用动。
第一次用先跑 --stage build 看打印出来的对象名，再填 EDITS。
"""

import os
import sys

SKILL_DIR = os.environ.get("BLENDER_SKILL_DIR", "")
KIT_DIR = os.environ.get("BLENDER_KIT_DIR", os.path.join(SKILL_DIR, "lib"))
if KIT_DIR and KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

import bpy  # noqa: E402  （只用它按名字找对象，其它操作都走 kit）

from blender_kit import (  # noqa: E402
    assign,
    export_all,
    mat,
    open_blend,
    rotate,
    save_report,
    scale_obj,
    scene_report,
    stage,
    translate,
    render_views,
    script_args,
)

OUT_DIR = os.environ.get("BLENDER_OUT_DIR", os.path.join(os.getcwd(), "blender-models", "edit-model"))
RENDERS_DIR = os.path.join(OUT_DIR, "renders")
EXPORTS_DIR = os.path.join(OUT_DIR, "exports")

# --- 改这里：对象名 -> 改动 -------------------------------------------------
# 支持 rotate=(x,y,z) 度、scale=(x,y,z)、translate=(dx,dy,dz) 米、
# material=(名称, (r,g,b), roughness)（给该对象所有网格换材质）、hide=True 隐藏。
EDITS = {
    # 示例（把模型抬高 0.05 m 并绕 Z 转 30 度）：
    # "mug": {"translate": (0.0, 0.0, 0.05), "rotate": (0.0, 0.0, 30.0)},
}

RENDER = {
    "views": ("front", "right", "iso"),
    "preview_resolution": 512,
    "preview_samples": 16,
    "engine": "CYCLES",
}
EXPORT_STEM = "model-edited"


def parse_args():
    """从 `--` 后面的参数里取 --blend；也支持环境变量 BLENDER_BLEND_IN。"""
    argv = list(script_args())
    blend = os.environ.get("BLENDER_BLEND_IN", "")
    for i, tok in enumerate(argv):
        if tok == "--blend" and i + 1 < len(argv):
            blend = argv[i + 1]
        elif tok.startswith("--blend="):
            blend = tok.split("=", 1)[1]
    return blend


def find_object(name):
    """按名字找场景对象；找不到返回 None。"""
    return bpy.context.scene.objects.get(name) if bpy.context.scene else None


def apply_edits():
    """按 EDITS 逐条改，返回实际改过的对象名列表。"""
    changed = []
    for name, ops in EDITS.items():
        ob = find_object(name)
        if ob is None:
            print("[edit] WARN 找不到对象 %r，跳过（先跑 --stage build 看对象列表）" % (name,))
            continue
        if "material" in ops:
            m_name, color, roughness = ops["material"]
            # update_existing：源文件里已有同名材质时也按本次参数重配（默认同名复用不改参数）；
            # all_slots：多材质槽对象整件换材质（默认只换槽 0，其余槽会留旧材质）。
            assign(ob, mat(m_name, color=color, roughness=roughness, update_existing=True),
                   all_slots=True)
        if "rotate" in ops:
            rotate(ob, *ops["rotate"])
        if "scale" in ops:
            scale_obj(ob, ops["scale"])
        if "translate" in ops:
            translate(ob, ops["translate"])
        if ops.get("hide"):
            ob.hide_render = True
            ob.hide_viewport = True
        changed.append(name)
        print("[edit] %s <- %r" % (name, ops))
    return changed


def main():
    blend_path = parse_args()
    if not blend_path:
        print("Error: 缺少 --blend <path>：请给出要修改的 .blend 文件路径")
        sys.exit(1)
    if not os.path.isfile(blend_path):
        print("Error: 找不到 .blend 文件：%s" % blend_path)
        sys.exit(1)

    info = open_blend(blend_path)
    if not info:
        # AGENTS 10.5：源文件损坏时 open_blend 返回 {} 并打印警告，这里必须明确报错退出，
        # 不能继续用空 info 取 object_count（否则 KeyError 崩溃，错误信息不可读）。
        print("Error: 无法打开 .blend：%s（文件损坏或格式不支持，详见上方 WARN；请重新提供 Blender 4.x .blend）"
              % blend_path)
        sys.exit(1)
    print("[edit] 已打开 %s（%d 对象 / %d 网格 / %d 相机 / %d 灯光）"
          % (blend_path, info["object_count"], info["mesh_count"],
             info["camera_count"], info["light_count"]))
    print("[edit] 场景对象：%r" % ([o.name for o in bpy.context.scene.objects],))

    changed = apply_edits()
    rep = scene_report()
    print("[edit] 改动对象：%r" % (changed,))
    print("[edit] objects=%d tris=%d dims=(%.3f, %.3f, %.3f)"
          % (rep["object_count"], rep["total_tris"],
             rep["dimensions"][0], rep["dimensions"][1], rep["dimensions"][2]))

    st = stage()
    if st in ("render", "full"):
        renders = render_views(
            RENDERS_DIR,
            prefix="view",
            views=tuple(RENDER["views"]),
            engine=RENDER["engine"],
            samples=int(RENDER["preview_samples"]),
            resolution=(int(RENDER["preview_resolution"]), int(RENDER["preview_resolution"])),
        )
        print("[edit] renders=%d" % len(renders))

    if st == "full":
        exported = export_all(EXPORTS_DIR, stem=EXPORT_STEM)
        report_path = save_report(
            OUT_DIR,
            extra={
                "slug": "edit-model",
                "source_blend": os.path.abspath(blend_path),
                "changed_objects": changed,
                "edits": EDITS,
            },
        )
        print("[edit] exports=%r report=%s" % (sorted(exported.keys()), report_path))


if __name__ == "__main__":
    main()
