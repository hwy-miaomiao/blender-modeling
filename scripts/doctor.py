# -*- coding: utf-8 -*-
"""环境体检：确认 Blender 建模技能可以工作。

用法：
    python scripts/doctor.py            # 只检查
    python scripts/doctor.py --smoke    # 额外跑一次 64x64 冒烟渲染（约 1-3 秒）
    python scripts/doctor.py --vision   # 视觉探针：机器可验证「代理真的看过图」
    python scripts/doctor.py --json     # 以纯 JSON 输出（便于脚本/CI 解析）

检查项（FAIL 会使退出码为 1）：
1. 当前 Python 版本 >= 3.9
2. 技能目录结构完整（lib/templates/scripts/references）
3. 能找到 Blender，版本 >= 4.0（推荐 4.0.x；其它 4.x 只 WARN）
4. 当前工作目录（cwd）可写（真正的输出目录在建目录时验证）
5. Pillow 是否可用（仅联系表脚本需要，缺失只 WARN）
6. --smoke：kit 导入 + 建体 + 渲染 + glb/blend 导出端到端可用
7. --vision：纯标准库 PNG 解码校验 examples/*/renders（可解码 / 尺寸符合
   report 声明 / 非空白），不需要 Blender 与 Pillow，可在 CI 里证明「交付的
   渲染图真的能被打开看」而不是只有日志。（对应竞品 Amagine3D 的 doctor --vision）
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bl_common  # noqa: E402

RESULTS = []
# --json 模式下逐条结果只收集不打印，保证 stdout 是纯 JSON（否则 jq / 脚本无法解析）
QUIET = False


def record(level, message):
    RESULTS.append((level, message))
    if not QUIET:
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
        # 模式 B（AGENTS 10.5）必须用编辑模板；缺了它文档流程直接不可用
        ("templates/edit_model_template.py",
         os.path.join(bl_common.TEMPLATE_DIR, "edit_model_template.py")),
        ("scripts/run_blender.py", os.path.join(bl_common.SKILL_DIR, "scripts", "run_blender.py")),
        ("scripts/check_output.py", os.path.join(bl_common.SKILL_DIR, "scripts", "check_output.py")),
        # R9 Phase2：变异闸门基准 + 视觉探针（doctor --vision / CI 依赖）
        ("scripts/gate_bench.py", os.path.join(bl_common.SKILL_DIR, "scripts", "gate_bench.py")),
        ("scripts/vision_probe.py",
         os.path.join(bl_common.SKILL_DIR, "scripts", "vision_probe.py")),
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
        # R9-B10：这行日志必须受 QUIET 保护，否则 --json 的 stdout 被污染
        #（json.loads 直接失败，CI/脚本无法解析）。
        if not QUIET:
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


def default_vision_targets():
    """默认视觉探针目标：仓库内 examples/*/renders（CI 无 Blender 也能跑）。"""
    targets = []
    examples = os.path.join(bl_common.SKILL_DIR, "examples")
    if os.path.isdir(examples):
        for name in sorted(os.listdir(examples)):
            out_dir = os.path.join(examples, name)
            if os.path.isdir(os.path.join(out_dir, "renders")):
                targets.append(("examples/%s" % name, out_dir, "out"))
    return targets


def _load_vision_probe():
    try:
        import importlib
        return importlib.import_module("vision_probe")
    except Exception:  # noqa: BLE001
        return None


def check_vision(extra_out=(), extra_dir=()):
    """视觉探针：纯标准库解码 PNG，证明渲染图「真的能被打开看」。

    与 Amagine3D 的 `doctor --vision` 同一目标：不只信日志，用像素级证据
    校验渲染图存在/可解码/尺寸符合 report 声明/非空白（纯色或近纯色）。
    不需要 Blender、不需要 Pillow，可在 ubuntu CI 直接跑。
    返回每个目标的探针 payload 列表（供 --json 汇总）。
    """
    module = _load_vision_probe()
    if module is None:
        record("FAIL", "视觉探针不可用：scripts/vision_probe.py 导入失败")
        return []
    targets = default_vision_targets()
    for path in extra_out:
        targets.append((os.path.abspath(path), os.path.abspath(path), "out"))
    for path in extra_dir:
        targets.append((os.path.abspath(path), os.path.abspath(path), "dir"))
    if not targets:
        record("FAIL", "视觉探针没有目标：未找到 examples/*/renders，"
                       "可用 --vision-out/--vision-dir 指定")
        return []
    payloads = []
    for label, path, mode in targets:
        if not os.path.isdir(path):
            record("FAIL", "视觉探针目标不存在: %s" % path)
            payloads.append({"label": label, "target": os.path.abspath(path),
                             "ok": False, "mode": mode, "files": [],
                             "reasons": ["目标目录不存在"]})
            continue
        try:
            if mode == "dir":
                payload = module.probe_renders(path)
            else:
                payload = module.probe_out_full(path)
        except Exception as exc:  # noqa: BLE001
            record("FAIL", "视觉探针执行异常: %s (%r)" % (path, exc))
            payloads.append({"label": label, "target": os.path.abspath(path),
                             "ok": False, "mode": mode, "files": [],
                             "reasons": [repr(exc)]})
            continue
        payload["label"] = label
        payloads.append(payload)
        files = payload.get("files") or []
        if payload.get("ok"):
            sizes = sorted({"%dx%d" % (item.get("width") or 0, item.get("height") or 0)
                            for item in files if item.get("width")})
            record("PASS", "视觉探针: %s %d 张图可解码且非空白（%s）"
                   % (label, len(files), ", ".join(sizes) or "-"))
        else:
            reasons = [str(item) for item in (payload.get("reasons") or [])
                       or ["未识别原因的失败"]]
            record("FAIL", "视觉探针: %s 未通过：%s"
                   % (label, "; ".join(reasons[:3])))
    return payloads


def _vision_summary(payloads):
    summary = []
    for payload in payloads or []:
        item = {
            "label": payload.get("label"),
            "target": payload.get("target"),
            "ok": bool(payload.get("ok")),
            "files": len(payload.get("files") or []),
            "reasons": payload.get("reasons") or [],
        }
        sheet = payload.get("sheet")
        if isinstance(sheet, dict):
            item["sheet_ok"] = bool(sheet.get("ok"))
        summary.append(item)
    return {"ok": bool(summary) and all(item["ok"] for item in summary),
            "targets": summary}


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
    keep_dir = False
    try:
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(SMOKE_SCRIPT)
        if QUIET:
            # --json 时 execute(quiet=True) 仍会打印一行 BM_RESULT，这里整体吞掉
            with contextlib.redirect_stdout(io.StringIO()):
                result = bl_common.execute(script, out_dir, stage="full", timeout=180,
                                           label="smoke", blender=exe, quiet=True)
        else:
            result = bl_common.execute(script, out_dir, stage="full", timeout=180,
                                       label="smoke", blender=exe, quiet=True)
        if not result.get("ok"):
            record("FAIL", "smoke 渲染失败：%s" % ("; ".join(result.get("errors") or [])[:400]))
            keep_dir = True
            print("       冒烟目录保留用于排查: %s" % tmp)
            return
        renders = result.get("renders") or []
        exports = result.get("exports") or []
        if not renders:
            record("FAIL", "smoke 未产出渲染图")
            keep_dir = True
        elif not exports:
            record("FAIL", "smoke 未导出 glb/blend")
            keep_dir = True
        else:
            names = [item["path"] for item in exports]
            need = [n for n in ("smoke.glb", "smoke.blend") if not any(n in x for x in names)]
            if need:
                record("FAIL", "smoke 缺少导出: %s" % ", ".join(need))
                keep_dir = True
            else:
                record("PASS", "smoke 端到端通过：渲染 1 张 + 导出 glb/blend（%.1fs）"
                       % (result.get("duration_s") or 0))
        if keep_dir:
            print("       冒烟目录保留用于排查: %s" % tmp)
    finally:
        if not keep_dir and os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Blender 建模技能环境体检（只检查不安装）")
    parser.add_argument("--smoke", action="store_true", help="额外跑一次端到端冒烟渲染")
    parser.add_argument("--vision", action="store_true",
                        help="视觉探针：纯标准库校验渲染图可解码/尺寸符合声明/非空白"
                             "（不需要 Blender 与 Pillow）")
    parser.add_argument("--vision-out", action="append", default=[], metavar="DIR",
                        help="额外检查的输出目录（含 renders/ 与 report.json；可重复）")
    parser.add_argument("--vision-dir", action="append", default=[], metavar="DIR",
                        help="额外检查的 renders 目录（可重复）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    global QUIET
    QUIET = bool(args.json)
    if not args.json:
        print("=== blender-modeling doctor ===")
        print("技能目录: %s" % bl_common.SKILL_DIR)
        print("工作目录: %s\n" % os.getcwd())

    vision_payloads = None
    check_python()
    check_layout()
    if args.vision:
        # 视觉探针模式不依赖 Blender：CI（ubuntu）也能验证「代理真的看过图」
        check_pillow()
        vision_payloads = check_vision(args.vision_out, args.vision_dir)
        if args.smoke:
            exe = check_blender()
            check_workspace_write()
            check_smoke(exe)
    else:
        exe = check_blender()
        check_workspace_write()
        check_pillow()
        if args.smoke:
            check_smoke(exe)

    fails = [m for level, m in RESULTS if level == "FAIL"]
    warns = [m for level, m in RESULTS if level == "WARN"]
    passes = [m for level, m in RESULTS if level == "PASS"]

    if args.json:
        payload = {
            "ok": not fails,
            "skill_dir": bl_common.SKILL_DIR,
            "cwd": os.getcwd(),
            "smoke": bool(args.smoke),
            "vision": _vision_summary(vision_payloads) if args.vision else None,
            "counts": {"pass": len(passes), "error": len(fails), "warn": len(warns)},
            "items": [{"level": level, "message": message} for level, message in RESULTS],
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 1 if fails else 0

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
