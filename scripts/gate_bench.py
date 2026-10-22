# -*- coding: utf-8 -*-
"""变异闸门基准（gate_bench）：用确定性「坏产物」证明交付闸门真的会拦截。

背景（竞品融合第 2 批，对应竞品 Amagine3D 的 commit gate 思路）：
「闸门有效」不能只靠一句"跑过了"——要能给出数字证据。本脚本把仓库自带的
合格产物（examples/lowpoly-mug、examples/office-chair）复制到临时目录，逐个
施加确定性变异（缺渲染图、截断/空白 PNG、report 尺寸/统计值被改、NaN/inf、
导出缺失/损坏、路径越界、重复记录、联系表空白……），再分别交给三道闸门判定：

    check_output.py    交付闸门（子进程，--json）
    vision_metrics.py  视觉指标闸门（子进程，--json）
    vision_probe.py    纯 stdlib 视觉探针（doctor --vision 的引擎，同进程）

输出「变异 → 是否被拦 → 命中错误码」表格与抓取率；任何变异逃逸（三道闸门
都没拦住）→ 退出码 1。不依赖 Blender/GPU/网络，CI 可直接跑；确定性：
固定变异、固定输入，同一份产物每次结果一致。

用法：
    python scripts/gate_bench.py                 # 跑全部变异，人读表格
    python scripts/gate_bench.py --json          # 给 README 引用的数字
    python scripts/gate_bench.py --selftest      # 自带夹具自测（无需 examples/）
    python scripts/gate_bench.py --examples lowpoly-mug

退出码：0 = 全部变异被拦截（且基线产物本身干净）；1 = 有逃逸/基线不干净。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
CHECK_OUTPUT = os.path.join(SCRIPT_DIR, "check_output.py")
VISION_METRICS = os.path.join(SCRIPT_DIR, "vision_metrics.py")
VISION_PROBE = os.path.join(SCRIPT_DIR, "vision_probe.py")
DEFAULT_EXAMPLES = ("lowpoly-mug", "office-chair")
GATE_TIMEOUT = 180
CONTACT_SHEET_NAME = "contact-sheet.png"

# 闸门代码（表格/JSON 用；与 check_output/vision_metrics 的 ERROR 文案映射）
CODE_RENDERS = "CHECK_RENDERS"
CODE_EXPORTS = "CHECK_EXPORTS"
CODE_REQUIRED = "CHECK_REQUIRED"
CODE_MODEL = "CHECK_MODEL"
CODE_REPORT = "CHECK_REPORT"
CODE_SCENE = "CHECK_REPORT_SCENE"
CODE_REPORT_RENDERS = "CHECK_REPORT_RENDERS"
CODE_REPORT_EXPORTS = "CHECK_REPORT_EXPORTS"
CODE_VISION = "CHECK_VISION"
CODE_ITERATION = "CHECK_ITERATION"
CODE_OTHER = "CHECK_OTHER"
CODE_PROBE = "VISION_PROBE"

_VISION_CODE_RE = re.compile(r"VISION\d{3}")

# 顺序敏感：先匹配更具体的文案
_CLASSIFY_RULES = (
    ("渲染图数量不足", CODE_RENDERS),
    ("渲染图不是合法 PNG", CODE_RENDERS),
    ("渲染图尺寸过小", CODE_RENDERS),
    ("渲染图过小", CODE_RENDERS),
    ("PNG 结构损坏", CODE_RENDERS),
    ("缺少 renders/", CODE_RENDERS),
    ("缺少导出文件", CODE_EXPORTS),
    ("导出文件魔数不对", CODE_EXPORTS),
    ("导出文件过小", CODE_EXPORTS),
    ("缺少或为空", CODE_REQUIRED),
    ("model.py 未导入", CODE_MODEL),
    ("report.json 缺失", CODE_REPORT),
    ("report.scene.", CODE_SCENE),
    ("report 尺寸与 bbox", CODE_SCENE),
    ("模型尺寸", CODE_SCENE),
    ("report 的导出路径", CODE_REPORT_EXPORTS),
    ("report 记录的", CODE_REPORT_EXPORTS),
    ("导出记录", CODE_REPORT_EXPORTS),
    ("report.renders", CODE_REPORT_RENDERS),
    ("渲染统计", CODE_REPORT_RENDERS),
    ("report.vision", CODE_VISION),
    ("视觉闸门", CODE_VISION),
    ("迭代记录", CODE_ITERATION),
)


def _enable_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load_module(name, path):
    """按文件路径导入同目录脚本；失败返回 None。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        return None


def _probe_module():
    return _load_module("vision_probe", VISION_PROBE)


def _chunk(ctype, payload):
    return (struct.pack(">I", len(payload)) + ctype + payload
            + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF))


# ---------------------------------------------------------------------------
# 闸门调用
# ---------------------------------------------------------------------------

def _run(cmd, cwd, env, timeout=GATE_TIMEOUT):
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")
        return {"returncode": proc.returncode, "stdout": proc.stdout,
                "stderr": proc.stderr, "timeout": False}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "",
                "timeout": True}
    except OSError as exc:
        return {"returncode": -1, "stdout": "", "stderr": repr(exc),
                "timeout": False, "oserror": True}


def _parse_json_output(text):
    """从子进程 stdout 里解析 JSON（容忍日志混入：取第一个 '{' 到最后一个 '}'）。"""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def classify_message(message):
    """把 check_output 的 ERROR 文案映射成稳定的闸门代码。"""
    match = _VISION_CODE_RE.search(message)
    if match:
        return match.group(0)
    for keyword, code in _CLASSIFY_RULES:
        if keyword in message:
            return code
    return CODE_OTHER


def run_check_output(root, env):
    """子进程跑 check_output --json；返回 {ok, exit, codes, errors, note}。"""
    result = _run([sys.executable, CHECK_OUTPUT, "--out", root, "--json"],
                  cwd=ROOT_DIR, env=env)
    payload = _parse_json_output(result.get("stdout"))
    if payload is None:
        return {"gate": "check_output", "ok": False, "exit": result["returncode"],
                "codes": [CODE_OTHER],
                "errors": ["无法解析 check_output --json 输出：%s"
                           % (result.get("stderr") or result.get("stdout", ""))[-300:]],
                "note": "输出异常"}
    errors = [item["message"] for item in payload.get("items", [])
              if item.get("level") == "ERROR"]
    codes = sorted({classify_message(message) for message in errors})
    return {"gate": "check_output", "ok": bool(payload.get("ok")),
            "exit": result["returncode"], "codes": codes,
            "errors": errors[:4], "note": ""}


def run_vision_metrics(root, env):
    """子进程跑 vision_metrics --json；Pillow 缺失时返回 skipped。"""
    result = _run([sys.executable, VISION_METRICS, "--out", root, "--json"],
                  cwd=ROOT_DIR, env=env)
    payload = _parse_json_output(result.get("stdout"))
    if payload is None:
        return {"gate": "vision_metrics", "ok": False, "exit": result["returncode"],
                "codes": [CODE_OTHER], "note": "输出异常", "skipped": False,
                "errors": ["无法解析 vision_metrics --json 输出"]}
    # 只有「未安装 Pillow」的全局 SKIP 才算放行（vision_metrics.py 的 main 用
    # skipped=True 表示）；analyze_out 的 payload 里 skipped 是「无法解码的文件名
    # 列表」（部分坏图 → VISION009 ERROR），非空列表不能当成 SKIP，否则会把
    # 视觉闸门回归伪装成全绿。
    if payload.get("skipped") is True:
        return {"gate": "vision_metrics", "ok": True, "exit": result["returncode"],
                "codes": [], "note": "SKIP（未安装 Pillow）", "skipped": True,
                "errors": []}
    issues = payload.get("issues") or []
    codes = sorted({str(item.get("code") or CODE_OTHER)
                    for item in issues if item.get("level") == "ERROR"})
    errors = [item.get("message", "") for item in issues
              if item.get("level") == "ERROR"]
    return {"gate": "vision_metrics", "ok": bool(payload.get("ok")),
            "exit": result["returncode"], "codes": codes, "note": "",
            "skipped": False, "errors": errors[:4]}


def run_vision_probe(root):
    """同进程跑 vision_probe.probe_out_full（doctor --vision 的同一引擎）。"""
    module = _probe_module()
    if module is None:
        return {"gate": "vision_probe", "ok": False, "codes": [CODE_PROBE],
                "note": "vision_probe.py 不可导入", "errors": []}
    try:
        payload = module.probe_out_full(root)
    except Exception as exc:  # noqa: BLE001
        return {"gate": "vision_probe", "ok": False, "codes": [CODE_PROBE],
                "note": "探测异常", "errors": [repr(exc)]}
    return {"gate": "vision_probe", "ok": bool(payload.get("ok")),
            "codes": [] if payload.get("ok") else [CODE_PROBE],
            "note": "", "errors": (payload.get("reasons") or [])[:4]}


def run_all_gates(root, env):
    gates = {
        "check_output": run_check_output(root, env),
        "vision_metrics": run_vision_metrics(root, env),
        "vision_probe": run_vision_probe(root),
    }
    codes = set()
    for gate in gates.values():
        codes.update(gate.get("codes") or [])
    return gates, sorted(codes)


# ---------------------------------------------------------------------------
# 变异定义
# ---------------------------------------------------------------------------

def _load_report(ctx):
    with open(ctx["report_path"], "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_report(ctx, report):
    with open(ctx["report_path"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=True)
        handle.write("\n")


def _write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def _probe_helpers():
    module = _probe_module()
    if module is None:
        raise RuntimeError("vision_probe.py 不可导入，无法构造 PNG 变异")
    return module


def m_missing_render(ctx):
    """删掉一张渲染图（交付物缺失视角）。"""
    os.remove(ctx["view_paths"][1])


def m_truncated_png(ctx):
    """把一张渲染图截断到 60%（下载/写盘中断的典型坏图）。"""
    path = ctx["view_paths"][0]
    data = _read_bytes(path)
    _write_bytes(path, data[:max(32, int(len(data) * 0.6))])


def m_blank_png(ctx):
    """用纯色空白 PNG 替换一张渲染图（先看日志不真看图的典型伪造）。"""
    probe = _probe_helpers()
    data = probe._encode_rgb_png(512, 512, probe._solid_pixels(512, 512))
    _write_bytes(ctx["view_paths"][0], data)


def m_corrupt_partial_png(ctx):
    """合法 PNG 头 + 垃圾字节（无 IDAT/IEND），文件体积仍达标。"""
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 512, 512, 8, 2, 0, 0, 0))
    data = b"\x89PNG\r\n\x1a\n" + ihdr + b"\x00" * 16000
    _write_bytes(ctx["view_paths"][1], data)


def m_report_dimensions_tampered(ctx):
    """report 里模型尺寸被改（冒充实物尺寸）。"""
    report = _load_report(ctx)
    report["scene"]["dimensions"][0] = round(
        report["scene"]["dimensions"][0] * 2.0, 6)
    _save_report(ctx, report)


def m_report_bbox_inf(ctx):
    """report.bbox 里注入 inf（JSON 非标准值，旧闸门会静默放行）。"""
    report = _load_report(ctx)
    report["scene"]["bbox_max"][2] = float("inf")
    _save_report(ctx, report)


def m_report_dimensions_inf(ctx):
    """report.dimensions 里注入 inf。"""
    report = _load_report(ctx)
    report["scene"]["dimensions"][0] = float("inf")
    _save_report(ctx, report)


def m_report_render_width(ctx):
    """report.renders 记录的像素宽度被改。"""
    report = _load_report(ctx)
    report["renders"][0]["width"] = int(report["renders"][0]["width"]) + 8
    _save_report(ctx, report)


def m_report_render_bytes(ctx):
    """report.renders 记录的渲染图字节数被改。"""
    report = _load_report(ctx)
    report["renders"][0]["bytes"] = int(report["renders"][0]["bytes"]) + 1
    _save_report(ctx, report)


def m_report_render_stats_nan(ctx):
    """report.renders 的 std 注入 NaN（旧 _is_number 接受 NaN → 静默通过）。"""
    report = _load_report(ctx)
    report["renders"][0]["std"] = float("nan")
    _save_report(ctx, report)


def m_export_missing(ctx):
    """删掉导出的 glb（只交渲染图不交模型）。"""
    os.remove(ctx["exports"]["glb"])


def m_export_glb_corrupt(ctx):
    """glb 魔数被破坏（文件大小仍达标）。"""
    path = ctx["exports"]["glb"]
    data = _read_bytes(path)
    _write_bytes(path, b"\x00" * 8 + data[8:])


def m_export_bytes_nan(ctx):
    """report.exports.glb.bytes 注入 NaN（旧闸门 int(NaN) 会抛异常）。"""
    report = _load_report(ctx)
    report["exports"]["glb"]["bytes"] = float("nan")
    _save_report(ctx, report)


def m_report_render_traversal(ctx):
    """report.renders 路径改成 ../ 越界，指向输出目录外同样合法的一张图。"""
    probe = _probe_helpers()
    report = _load_report(ctx)
    path = ctx["view_paths"][0]
    outside = os.path.join(os.path.dirname(ctx["root"]), "traversal-escape.png")
    shutil.copyfile(path, outside)
    entry = report["renders"][0]
    entry["path"] = "../traversal-escape.png"
    entry["bytes"] = os.path.getsize(outside)
    # 宽高/统计值与真实文件一致（否则别的检查会先报错，掩盖路径越界）
    width, height = probe.read_png_header(outside) or (entry.get("width"),
                                                      entry.get("height"))
    entry["width"] = int(width)
    entry["height"] = int(height)
    _save_report(ctx, report)
    return [outside]


def m_report_render_duplicate(ctx):
    """report.renders 复制一条记录（重复计数/重复统计）。"""
    report = _load_report(ctx)
    report["renders"].append(dict(report["renders"][0]))
    _save_report(ctx, report)


def m_contact_sheet_blank(ctx):
    """伪造一张空白 contact-sheet.png（现有闸门不看联系表）。"""
    probe = _probe_helpers()
    data = probe._encode_rgb_png(400, 200, probe._solid_pixels(400, 200))
    _write_bytes(os.path.join(ctx["renders_dir"], CONTACT_SHEET_NAME), data)


def m_wrong_size_view(ctx):
    """用 256x256 的小图替换 512x512 渲染图（report 仍声明 512）。"""
    probe = _probe_helpers()
    data = probe._encode_rgb_png(256, 256, probe._gradient_pixels(256, 256))
    _write_bytes(ctx["view_paths"][0], data)


MUTATIONS = (
    {"id": "M01", "title": "缺失渲染图", "apply": m_missing_render,
     "expected": [CODE_RENDERS]},
    {"id": "M02", "title": "PNG 截断 60%", "apply": m_truncated_png,
     "expected": [CODE_RENDERS, "VISION009"]},
    {"id": "M03", "title": "空白/纯色 PNG", "apply": m_blank_png,
     "expected": [CODE_RENDERS]},
    {"id": "M04", "title": "PNG 头合法+垃圾数据", "apply": m_corrupt_partial_png,
     "expected": [CODE_RENDERS, "VISION009"]},
    {"id": "M05", "title": "report 尺寸被改", "apply": m_report_dimensions_tampered,
     "expected": [CODE_SCENE]},
    {"id": "M06", "title": "report.bbox=inf", "apply": m_report_bbox_inf,
     "expected": [CODE_SCENE]},
    {"id": "M07", "title": "report.dimensions=inf", "apply": m_report_dimensions_inf,
     "expected": [CODE_SCENE]},
    {"id": "M08", "title": "report.renders 宽度被改", "apply": m_report_render_width,
     "expected": [CODE_REPORT_RENDERS]},
    {"id": "M09", "title": "report.renders 字节数被改", "apply": m_report_render_bytes,
     "expected": [CODE_REPORT_RENDERS]},
    {"id": "M10", "title": "report.renders std=NaN", "apply": m_report_render_stats_nan,
     "expected": [CODE_REPORT_RENDERS]},
    {"id": "M11", "title": "导出 glb 缺失", "apply": m_export_missing,
     "expected": [CODE_EXPORTS]},
    {"id": "M12", "title": "导出 glb 魔数损坏", "apply": m_export_glb_corrupt,
     "expected": [CODE_EXPORTS]},
    {"id": "M13", "title": "exports.bytes=NaN", "apply": m_export_bytes_nan,
     "expected": [CODE_REPORT_EXPORTS]},
    {"id": "M14", "title": "renders 路径 ../ 越界", "apply": m_report_render_traversal,
     "expected": [CODE_REPORT_RENDERS]},
    {"id": "M15", "title": "report.renders 重复记录", "apply": m_report_render_duplicate,
     "expected": [CODE_REPORT_RENDERS]},
    {"id": "M16", "title": "联系表空白", "apply": m_contact_sheet_blank,
     "expected": [CODE_PROBE]},
    {"id": "M17", "title": "渲染图尺寸被换", "apply": m_wrong_size_view,
     "expected": [CODE_REPORT_RENDERS]},
)


# ---------------------------------------------------------------------------
# 产物快照/还原
# ---------------------------------------------------------------------------

def snapshot_tree(root):
    files = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            files[rel] = _read_bytes(full)
    return files


def restore_tree(root, snapshot):
    current = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            current.add(os.path.relpath(os.path.join(dirpath, name), root))
    for rel in current - set(snapshot):
        try:
            os.remove(os.path.join(root, rel))
        except OSError:
            pass
    for rel, data in snapshot.items():
        full = os.path.join(root, rel)
        parent = os.path.dirname(full)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        _write_bytes(full, data)


def _example_view_paths(root):
    renders_dir = os.path.join(root, "renders")
    names = sorted(name for name in os.listdir(renders_dir)
                   if name.lower().endswith(".png") and name != CONTACT_SHEET_NAME)
    return renders_dir, names, [os.path.join(renders_dir, name) for name in names]


def _report_for_fixture(root):
    """构造一个最小但自洽的 report.json（不含 vision，走宽松迭代校验）。"""
    renders_dir, names, _paths = _example_view_paths(root)
    probe = _probe_helpers()
    renders = []
    for name in names:
        path = os.path.join(renders_dir, name)
        header = probe.read_png_header(path)
        width, height = header if header else (0, 0)
        with open(path, "rb") as handle:
            data = handle.read()
        decoded = probe.decode_png(data)
        pixels = decoded["pixels"]
        total = width * height
        lums = []
        black = 0
        for index in range(total):
            lum = (pixels[index * 3] * 0.2126 + pixels[index * 3 + 1] * 0.7152
                   + pixels[index * 3 + 2] * 0.0722)
            lums.append(lum)
            if lum < 8.0:
                black += 1
        mean = sum(lums) / total
        variance = max(sum(value * value for value in lums) / total - mean * mean, 0.0)
        renders.append({
            "path": "renders/" + name, "width": width, "height": height,
            "bytes": len(data), "mean": round(mean, 4),
            "std": round(variance ** 0.5, 4),
            "black_ratio": round(black / float(total), 4),
            "label": name.split(".")[0].replace("view-", ""),
        })
    exports = {}
    for key, ext in (("blend", "blend"), ("glb", "glb")):
        path = os.path.join(root, "exports", "model." + ext)
        exports[key] = {"path": "exports/model." + ext,
                        "bytes": os.path.getsize(path)}
    scene = {
        "object_count": 2, "mesh_count": 1, "camera_count": 1, "light_count": 2,
        "total_verts": 100, "total_tris": 180,
        "non_manifold_edges": 0, "dimensions": [1.0, 1.0, 1.0],
        "bbox_min": [0.0, 0.0, 0.0], "bbox_max": [1.0, 1.0, 1.0],
        "materials": ["test_mat"], "blender_version": "4.0.2", "engine": "CYCLES",
    }
    report = dict(scene)
    report.update({"scene": scene, "renders": renders, "exports": exports,
                   "generated_at": "2026-01-01T00:00:00", "stage": "full"})
    return report


def make_fixture(root, size=96):
    """造一个能过闸门的合成产物（自测用；无需 examples/ 与 Blender）。"""
    probe = _probe_helpers()
    os.makedirs(os.path.join(root, "renders"))
    os.makedirs(os.path.join(root, "exports"))
    with open(os.path.join(root, "model.py"), "w", encoding="utf-8") as handle:
        handle.write("# -*- coding: utf-8 -*-\n"
                     "import os\nfrom blender_kit import cube\n"
                     "OUT = os.environ.get('BLENDER_OUT_DIR', '')\n")
    with open(os.path.join(root, "brief.md"), "w", encoding="utf-8") as handle:
        handle.write("# brief\n\n## 迭代记录\n\n"
                     "| 轮次 | 看了哪张图 | 问题 | 改了什么 | 重跑结果 |\n"
                     "| --- | --- | --- | --- | --- |\n"
                     "| 1 | renders/view-front.png | 正常 | PARAMS 初值 | mean=120 |\n")
    width, height = size, size
    for index, name in enumerate(("view-front.png", "view-right.png", "view-iso.png")):
        # 平滑渐变背景 + 居中偏下的亮色主体：让视觉闸门看到「真实构图」，
        # 同时用 tEXt 填充块把文件撑到 >15KB（合成分辨率小，压不出体积）。
        pixels = bytearray(width * height * 3)
        shift = index * 3
        for y in range(height):
            for x in range(width):
                at = (y * width + x) * 3
                if width // 4 <= x < width * 3 // 4 and height // 3 <= y < height * 4 // 5:
                    pixels[at] = 200 - shift
                    pixels[at + 1] = 172
                    pixels[at + 2] = 120 + shift
                else:
                    pixels[at] = 30 + 30 * y // max(1, height - 1)
                    pixels[at + 1] = 34 + 30 * y // max(1, height - 1)
                    pixels[at + 2] = 42 + 20 * y // max(1, height - 1)
        png = probe._encode_rgb_png(width, height, bytes(pixels))
        seed = 24680 + index * 1357
        filler = bytearray()
        for _ in range(24000):
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            filler.append((seed >> 15) & 0xFF)
        padding = _chunk(b"tEXt", b"Comment\x00" + bytes(filler))
        png = png[:-12] + padding + png[-12:]
        _write_bytes(os.path.join(root, "renders", name), png)
    _write_bytes(os.path.join(root, "exports", "model.blend"),
                 b"BLENDER" + b"\x00" * 2048)
    _write_bytes(os.path.join(root, "exports", "model.glb"),
                 b"glTF" + b"\x00" * 1024)
    report = _report_for_fixture(root)
    with open(os.path.join(root, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return root


# ---------------------------------------------------------------------------
# 基准主流程
# ---------------------------------------------------------------------------

def _gate_env(tmp_dir):
    env = dict(os.environ)
    for key in ("TMP", "TEMP", "TMPDIR"):
        env[key] = tmp_dir
    return env


def bench_example(example_dir, mutations, workdir, env):
    """对一个合格产物跑基线与全部变异；返回该示例的 rows 与基线清况。"""
    name = os.path.basename(example_dir.rstrip("\\/"))
    root = os.path.join(workdir, name)
    if os.path.isdir(root):
        shutil.rmtree(root)
    shutil.copytree(example_dir, root)
    snapshot = snapshot_tree(root)
    renders_dir, names, view_paths = _example_view_paths(root)
    if len(names) < 3:
        return {"example": name, "ok": False, "rows": [],
                "baseline": {"ok": False,
                             "reason": "渲染图不足 3 张: %s" % (names,)}}
    report_path = os.path.join(root, "report.json")
    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    exports = {}
    for key in ("blend", "glb"):
        record = (report.get("exports") or {}).get(key) or {}
        rel = str(record.get("path") or ("exports/model." + key)).replace("\\", "/")
        exports[key] = os.path.join(root, rel)
    ctx = {
        "root": root, "renders_dir": renders_dir,
        "view_names": names, "view_paths": view_paths,
        "report_path": report_path, "exports": exports,
    }
    baseline_gates, baseline_codes = run_all_gates(root, env)
    baseline_ok = (baseline_gates["check_output"]["ok"]
                   and baseline_gates["vision_metrics"]["ok"]
                   and baseline_gates["vision_probe"]["ok"])
    rows = []
    for mutation in mutations:
        extra = []
        try:
            extra = mutation["apply"](ctx) or []
        except Exception as exc:  # noqa: BLE001
            rows.append({"example": name, "id": mutation["id"],
                         "title": mutation["title"], "error": repr(exc)})
            restore_tree(root, snapshot)
            continue
        try:
            gates, codes = run_all_gates(root, env)
        finally:
            restore_tree(root, snapshot)
            for path in extra:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
        caught_by = [gate_name for gate_name, gate in gates.items()
                     if not gate.get("ok")]
        expected = mutation.get("expected") or []
        matched = (not expected) or bool(set(expected) & set(codes))
        rows.append({
            "example": name,
            "id": mutation["id"],
            "title": mutation["title"],
            "expected": expected,
            "codes": codes,
            "caught_by": caught_by,
            "intercepted": bool(caught_by),
            "reason_matched": matched,
            "gates": {key: {"ok": gate.get("ok"), "codes": gate.get("codes"),
                            "note": gate.get("note"),
                            "errors": gate.get("errors")}
                      for key, gate in gates.items()},
        })
    return {"example": name, "ok": True, "rows": rows,
            "baseline": {"ok": baseline_ok, "codes": baseline_codes,
                         "gates": baseline_gates,
                         "vision_metrics_skipped":
                             baseline_gates["vision_metrics"].get("skipped", False)}}


def bench(example_dirs, mutations=MUTATIONS, keep=False, quiet=False):
    """跑完整基准；返回 payload dict（ok 表示无逃逸且基线干净）。"""
    workdir = tempfile.mkdtemp(prefix="bm-gate-bench-")
    tmp_dir = os.path.join(workdir, "tmp")
    os.makedirs(tmp_dir)
    env = _gate_env(tmp_dir)
    examples = []
    try:
        for example_dir in example_dirs:
            if not os.path.isdir(example_dir):
                examples.append({"example": os.path.basename(example_dir),
                                 "ok": False, "rows": [],
                                 "baseline": {"ok": False,
                                              "reason": "示例目录不存在: %s"
                                                        % example_dir}})
                continue
            if not quiet:
                print("[gate_bench] 基线校验 + %d 个变异: %s"
                      % (len(mutations), example_dir))
            examples.append(bench_example(example_dir, mutations, workdir, env))
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)
        elif not quiet:
            print("[gate_bench] 工作目录保留: %s" % workdir)

    rows = [row for example in examples for row in example.get("rows", [])]
    total = len(rows)
    caught = sum(1 for row in rows if row.get("intercepted"))
    escaped = total - caught
    mismatched = [row for row in rows
                  if row.get("intercepted") and not row.get("reason_matched")]
    examples_ran = bool(examples) and all(example.get("ok") for example in examples)
    baseline_ok = examples_ran and all(
        example.get("baseline", {}).get("ok") for example in examples)
    vision_metrics_available = examples_ran and all(
        not example.get("baseline", {}).get("vision_metrics_skipped")
        for example in examples)
    payload = {
        "bench_version": 1,
        "examples": examples,
        "rows": rows,
        "totals": {
            "mutations": total,
            "intercepted": caught,
            "escaped": escaped,
            "rate": (caught / float(total)) if total else 0.0,
            "reason_mismatched": len(mismatched),
            "baseline_ok": baseline_ok,
        },
        "pillow_available": vision_metrics_available,
        "ok": (total > 0 and escaped == 0 and baseline_ok),
    }
    return payload


def _print_table(payload):
    print("\n=== gate_bench: 变异闸门基准 ===")
    header = ("ID", "变异", "check_output", "vision_metrics", "vision_probe",
              "结论")
    print("%-4s %-22s %-18s %-16s %-14s %s" % header)
    for row in payload["rows"]:
        if "error" in row:
            print("%-4s %-22s 变异执行失败: %s" % (row["id"], row["title"],
                                                  row["error"]))
            continue
        gates = row["gates"]
        parts = []
        for key, label in (("check_output", "check_output"),
                           ("vision_metrics", "vision_metrics"),
                           ("vision_probe", "vision_probe")):
            gate = gates[key]
            if gate["ok"]:
                parts.append("PASS")
            elif gate.get("note"):
                parts.append("BLOCKED(%s)" % gate["note"])
            else:
                parts.append("BLOCKED %s" % (",".join(gate["codes"]) or "-"))
        verdict = "拦截" if row["intercepted"] else "**逃逸**"
        if row["intercepted"] and not row["reason_matched"]:
            verdict += "(原因未命中)"
        print("%-4s %-22s %-18s %-16s %-14s %s"
              % (row["id"], row["title"], parts[0], parts[1], parts[2], verdict))
    totals = payload["totals"]
    print("\n=== 汇总: %d 个变异, 拦截 %d, 逃逸 %d（抓取率 %.1f%%）, 原因未命中 %d ==="
          % (totals["mutations"], totals["intercepted"], totals["escaped"],
             totals["rate"] * 100.0, totals["reason_mismatched"]))
    for example in payload["examples"]:
        baseline = example.get("baseline", {})
        if not example.get("ok"):
            print("[FAIL] 基线不干净: %s (%s)"
                  % (example.get("example"), baseline.get("reason", "-")))
        elif not baseline.get("ok"):
            print("[FAIL] 合格产物未通过基线校验: %s（基准失真，先修闸门/产物）"
                  % example.get("example"))
    if payload["ok"]:
        print("结论: 合格产物基线干净，全部变异被至少一道闸门拦截。")
    else:
        print("结论: FAIL（有变异逃逸或基线不干净）")


def selftest():
    failures = []

    def expect(name, condition):
        if condition:
            print("[PASS] selftest: " + name)
        else:
            print("[FAIL] selftest: " + name)
            failures.append(name)

    probe = _probe_module()
    if probe is None:
        print("[FAIL] selftest: vision_probe.py 不可导入")
        return 1
    with tempfile.TemporaryDirectory(prefix="bm-gate-bench-self-") as tmp:
        fixture = make_fixture(os.path.join(tmp, "fixture"))
        payload = bench([fixture], quiet=True)
        totals = payload["totals"]
        expect("合成产物基线干净", payload["totals"]["baseline_ok"])
        expect("合成产物全部变异被拦截", totals["escaped"] == 0)
        expect("合成产物原因全部命中", totals["reason_mismatched"] == 0)
        expect("总变异数等于变异表长度", totals["mutations"] == len(MUTATIONS))
        expect("基准 ok 为真", payload["ok"])

        # 逃逸必须被如实报出来（用「什么都不改」的变异模拟闸门漏检）
        noop = {"id": "S00", "title": "空变异（模拟漏检）",
                "apply": lambda ctx: None, "expected": [CODE_RENDERS]}
        escaped_payload = bench([fixture], mutations=(noop,), quiet=True)
        expect("空变异被判定为逃逸", escaped_payload["totals"]["escaped"] == 1)
        expect("存在逃逸时基准 ok 为假", not escaped_payload["ok"])

        # 基线不干净时不能假绿：删掉一张渲染图再跑
        dirty = os.path.join(tmp, "dirty")
        shutil.copytree(fixture, dirty)
        os.remove(os.path.join(dirty, "renders", "view-right.png"))
        dirty_payload = bench([dirty], mutations=(MUTATIONS[0],), quiet=True)
        expect("基线不干净时基准 ok 为假", not dirty_payload["ok"])
        expect("基线不干净被标注", not dirty_payload["totals"]["baseline_ok"])

        # 分类函数：典型 ERROR 文案 -> 稳定代码
        expect("分类: VISION009", classify_message(
            "视觉闸门: 部分渲染图无法解码（VISION009）：1/3 张") == "VISION009")
        expect("分类: 渲染图数量不足", classify_message(
            "渲染图数量不足: 2 张 < 3 张") == CODE_RENDERS)
        expect("分类: report.scene", classify_message(
            "report.scene.dimensions 必须是 3 个数字") == CODE_SCENE)
        expect("分类: 路径越界", classify_message(
            "report 的渲染统计路径必须是相对路径: '../escape.png'")
               == CODE_REPORT_RENDERS)

    if failures:
        print("\nSELFTEST FAILED: %d 项失败" % len(failures))
        return 1
    print("\nSELFTEST OK")
    return 0


def main(argv=None):
    _enable_utf8_console()
    parser = argparse.ArgumentParser(
        description="变异闸门基准：用确定性坏产物证明交付闸门/视觉探针有效")
    parser.add_argument("--examples", default=None,
                        help="逗号分隔的示例名（默认为 %s）"
                             % ",".join(DEFAULT_EXAMPLES))
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（给 README 数字用）")
    parser.add_argument("--selftest", action="store_true", help="运行自带夹具自测")
    parser.add_argument("--keep", action="store_true", help="保留临时工作目录（排障用）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    names = ([item.strip() for item in args.examples.split(",")
              if item.strip()] if args.examples else list(DEFAULT_EXAMPLES))
    example_dirs = [os.path.join(ROOT_DIR, "examples", name) for name in names]
    payload = bench(example_dirs, keep=args.keep, quiet=args.json)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_table(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
