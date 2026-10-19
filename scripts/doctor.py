# -*- coding: utf-8 -*-
"""环境体检：确认 Blender 建模技能可以工作。

用法：
    python scripts/doctor.py            # 只检查
    python scripts/doctor.py --smoke    # 额外跑一次 64x64 冒烟渲染（约 1-3 秒）

检查项（FAIL 会使退出码为 1）：
1. 当前 Python 版本 >= 3.9
2. 技能目录结构完整（lib/templates/scripts/references）
3. 能找到 Blender，版本 >= 4.0（推荐 4.0.x；其它 4.x 只 WARN）
4. 当前工作目录（cwd）可写（真正的输出目录在建目录时验证）
5. Pillow 是否可用（仅联系表脚本需要，缺失只 WARN）
6. --smoke：kit 导入 + 建体 + 渲染 + glb/blend 导出端到端可用
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bl_common  # noqa: E402

RESULTS = []


def record(level, message):
    RESULTS.append((level, message))
    print("[%s] %s" % (level, message))


def check_python():
    if sys.version_info >= (3, 9):
        record("PASS", "Python %d.%d.%d (>=3.9)" % sys.version_info[:3])
    else:
        record("FAIL", "Python %d.%d.%d 过低，需要 >=3.9" % sys.version_info[:3])


def check_layout():
    required = [
        ("lib/blender_kit.py", os.path.join(bl_common.KIT_DIR, "blender_kit.py")),
        ("templates/model_template.py", os.path.join(bl_common.TEMPLATE_DIR, "model_template.py")),
        ("scripts/run_blender.py", os.path.join(bl_common.SKILL_DIR, "scripts", "run_blender.py")),
        ("scripts/check_output.py", os.path.join(bl_common.SKILL_DIR, "scripts", "check_output.py")),
    ]
    for label, path in required:
        if os.path.isfile(path):
            record("PASS", "技能文件存在: %s (%.1f KB)" % (label, os.path.getsize(path) / 1024.0))
        else:
            record("FAIL", "缺少技能文件: %s（期望 %s）" % (label, path))
    refs = os.path.join(bl_common.REFERENCES_DIR)
    if os.path.isdir(refs) and any(name.endswith(".md") for name in os.listdir(refs)):
        record("PASS", "references 目录存在（%d 个文档）" % len(
            [n for n in os.listdir(refs) if n.endswith(".md")]))
    else:
        record("WARN", "references 目录缺失或为空: %s" % refs)


def check_blender():
    exe = bl_common.find_blender()
    if not exe:
        record("FAIL", "找不到 Blender：安装 Blender 4.x 或设置环境变量 BLENDER_EXE")
        return None
    version = bl_common.blender_version(exe)
    if not version.get("ok"):
        record("FAIL", "无法运行 Blender: %s (%s)" % (exe, version.get("error")))
        return None
    ver = version["tuple"]
    if ver < (4, 0, 0):
        record("FAIL", "Blender 版本过低: %s，需要 >=4.0（推荐 4.0.2）" % version["version"])
    elif ver[:2] != (4, 0):
        record("WARN", "Blender 版本 %s 非实测目标 4.0.2，建议先跑 --smoke 验证" % version["version"])
        print("       Blender: %s" % exe)
    else:
        record("PASS", "Blender %s: %s" % (version["version"], exe))
    return exe


def check_workspace_write():
    target = os.path.abspath(os.getcwd())
    probe = os.path.join(target, ".bm-doctor-write-test")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        record("PASS", "当前目录可写: %s（输出目录请在建目录时确认）" % target)
    except OSError as exc:
        record("FAIL", "当前目录不可写: %s (%s)" % (target, exc))


def check_pillow():
    try:
        import PIL  # noqa: F401
        record("PASS", "Pillow 可用（可生成 contact-sheet.png）")
    except ImportError:
        record("WARN", "未安装 Pillow：contact_sheet.py 不可用（可选，不影响建模）")


SMOKE_SCRIPT = textwrap.dedent('''\
    # -*- coding: utf-8 -*-
    """doctor.py --smoke 的端到端冒烟脚本。"""
    import os
    import sys

    sys.path.insert(0, os.environ["BLENDER_KIT_DIR"])
    import blender_kit as bk

    out = os.environ["BLENDER_OUT_DIR"]
    bk.reset_scene()
    bk.setup_scene(studio=True, floor=False)
    bk.cube("smoke_cube", size=(1.0, 1.0, 1.0),
            material=bk.mat("smoke_mat", (0.85, 0.30, 0.20), roughness=0.4))
    bk.setup_render(engine="CYCLES", samples=4, resolution=(64, 64))
    render = bk.render_still(os.path.join(out, "renders", "smoke.png"))
    print("SMOKE_RENDER", render)
    bk.export_glb(os.path.join(out, "exports", "smoke.glb"))
    bk.save_blend(os.path.join(out, "exports", "smoke.blend"))
    bk.save_report(out, extra={"smoke": True})
    print("SMOKE_OK")
''')


def check_smoke(exe):
    kit_path = os.path.join(bl_common.KIT_DIR, "blender_kit.py")
    if not os.path.isfile(kit_path):
        record("WARN", "跳过 smoke：lib/blender_kit.py 不存在")
        return
    if not exe:
        record("WARN", "跳过 smoke：没有可用的 Blender")
        return

    tmp = tempfile.mkdtemp(prefix="bm-doctor-smoke-")
    script = os.path.join(tmp, "smoke.py")
    out_dir = os.path.join(tmp, "out")
    os.makedirs(out_dir, exist_ok=True)
    try:
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(SMOKE_SCRIPT)
        result = bl_common.execute(script, out_dir, stage="full", timeout=180,
                                   label="smoke", blender=exe, quiet=True)
        if not result.get("ok"):
            record("FAIL", "smoke 渲染失败：%s" % ("; ".join(result.get("errors") or [])[:400]))
            print("       冒烟目录保留用于排查: %s" % tmp)
            return
        renders = result.get("renders") or []
        exports = result.get("exports") or []
        if not renders:
            record("FAIL", "smoke 未产出渲染图")
        elif not exports:
            record("FAIL", "smoke 未导出 glb/blend")
        else:
            names = [item["path"] for item in exports]
            need = [n for n in ("smoke.glb", "smoke.blend") if not any(n in x for x in names)]
            if need:
                record("FAIL", "smoke 缺少导出: %s" % ", ".join(need))
            else:
                record("PASS", "smoke 端到端通过：渲染 1 张 + 导出 glb/blend（%.1fs）"
                       % (result.get("duration_s") or 0))
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Blender 建模技能环境体检（只检查不安装）")
    parser.add_argument("--smoke", action="store_true", help="额外跑一次端到端冒烟渲染")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    print("=== blender-modeling doctor ===")
    print("技能目录: %s" % bl_common.SKILL_DIR)
    print("工作目录: %s\n" % os.getcwd())

    check_python()
    check_layout()
    exe = check_blender()
    check_workspace_write()
    check_pillow()
    if args.smoke:
        check_smoke(exe)

    fails = [m for level, m in RESULTS if level == "FAIL"]
    warns = [m for level, m in RESULTS if level == "WARN"]
    passes = [m for level, m in RESULTS if level == "PASS"]

    print("\n=== 结果: %d PASS / %d ERROR / %d WARN ===" % (len(passes), len(fails), len(warns)))
    if fails:
        print("存在 ERROR，技能当前不可用；按上面提示修复后重新运行 doctor.py")
        for item in fails:
            print("  ERROR: " + item)
        return 1
    print("环境就绪。下一步：按 AGENTS.md 的阶段 1 开始解析提示词。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
