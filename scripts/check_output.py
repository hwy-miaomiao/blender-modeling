# -*- coding: utf-8 -*-
"""交付闸门：检查 blender-models 输出目录是否达到可交付标准。

用法：
    python scripts/check_output.py --out <输出目录>
    python scripts/check_output.py --out <输出目录> --min-views 4
    python scripts/check_output.py --selftest      # 纯函数自测，不需要真实输出

检查内容：
- 必需文件：model.py / brief.md / report.json
- 导出文件：优先按 report.json 的 exports 记录定位，其次 exports/model.blend、exports/model.glb，
  最后扫描 exports/ 下的 .blend/.glb；模式 B（AGENTS 10.5）的 model-edited.* 与自定义
  export stem 都能通过，但文件内容仍按魔数与最小体积严格校验
- 文件魔数与尺寸：.blend 以 BLENDER（或 gzip）开头，.glb 以 glTF 开头，非空
- renders/ 至少有 --min-views 张 PNG，每张有真实内容（>15 KB），并校验 PNG 头部合法
- report.json 场景统计：物体/网格/三角面/尺寸/相机/灯光/导出记录
- report.json 渲染统计：std>4.0 且 black_ratio<0.98（防止交付全黑图）
- report.json 的 exports.*.bytes 与实际文件大小不一致时只 WARN（旧版 report 可能陈旧，不阻断）
- model.py 通过 BLENDER_KIT_DIR 导入 kit（防止交付跑不起来的脚本）

通过条件：0 ERROR。WARN 需人工判断。退出码：通过 0，失败 1。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import tempfile


def _enable_utf8_console():
    """让脚本在 Windows 上以 UTF-8 输出中文（避免 GBK 控制台把中文写成乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_enable_utf8_console()

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GLB_MAGIC = b"glTF"
BLEND_MAGIC = b"BLENDER"
GZIP_MAGIC = b"\x1f\x8b"

MIN_PNG_BYTES = 15 * 1024
MIN_BLEND_BYTES = 1024
MIN_GLB_BYTES = 256
MIN_STD = 4.0
MAX_BLACK_RATIO = 0.98
MIN_VIEW_SIZE = 64  # 渲染图最小边长（像素），防止 1x1 补零图混过闸门


def _is_number(value):
    """数值判断（排除 bool：isinstance(True, int) 为真但不能当统计值）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# 纯函数工具
# ---------------------------------------------------------------------------

def read_head(path, count=64):
    try:
        with open(path, "rb") as fh:
            return fh.read(count)
    except OSError:
        return b""


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def png_size(path):
    """解析 PNG 头，返回 (width, height)；不是合法 PNG 返回 None。"""
    head = read_head(path, 33)
    if len(head) < 24 or not head.startswith(PNG_MAGIC):
        return None
    if head[12:16] != b"IHDR":
        return None
    try:
        width, height = struct.unpack(">II", head[16:24])
    except struct.error:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def is_blend_bytes(head):
    return head.startswith(BLEND_MAGIC) or head.startswith(GZIP_MAGIC)


def is_glb_bytes(head):
    return head.startswith(GLB_MAGIC)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def scene_block(report):
    """兼容两种 report 结构：{"scene": {...}} 或扁平字段。"""
    if not isinstance(report, dict):
        return {}
    scene = report.get("scene")
    if isinstance(scene, dict):
        return scene
    return report


def export_paths(report):
    """从 report 中取出 blend/glb 的路径记录。"""
    exports = report.get("exports") if isinstance(report, dict) else None
    result = {}
    if isinstance(exports, dict):
        for key in ("blend", "glb"):
            value = exports.get(key)
            if isinstance(value, dict):
                result[key] = value.get("path")
            elif isinstance(value, str):
                result[key] = value
    return result


def render_entries(report):
    """从 report 中取出渲染统计列表，兼容扁平/嵌套结构。"""
    if not isinstance(report, dict):
        return []
    entries = report.get("renders")
    if isinstance(entries, list):
        return [item for item in entries if isinstance(item, dict)]
    return []


def resolve_out_path(out_dir, path):
    """把 report 里的相对路径解析成绝对路径；绝对路径返回 None（report 必须可移植）。"""
    if not path:
        return None
    text = str(path)
    if os.path.isabs(text) or re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
        return None
    return os.path.join(out_dir, text.replace("/", os.sep))


def _export_candidates(out_dir, report, key):
    """按优先级列出 export 候选文件：report 记录 → 规范名 → exports/ 扫描。"""
    base = "blend" if key == "blend" else "glb"
    candidates = []
    recorded = export_paths(report).get(key) if isinstance(report, dict) else None
    resolved = resolve_out_path(out_dir, recorded)
    if resolved:
        candidates.append(resolved)
    candidates.append(os.path.join(out_dir, "exports", "model." + base))
    exports_dir = os.path.join(out_dir, "exports")
    if os.path.isdir(exports_dir):
        try:
            names = sorted(os.listdir(exports_dir))
        except OSError:
            names = []
        for name in names:
            if name.lower().endswith("." + base):
                candidates.append(os.path.join(exports_dir, name))
    return candidates


def find_export_file(out_dir, report, key, magic_ok, min_size):
    """定位交付导出文件；找不到返回 None。

    模式 B 模板固定导出 model-edited.blend/glb（AGENTS 10.5），所以不能只认
    exports/model.*。report 记录或规范名一旦存在就返回（后续统一报魔数/体积错误，
    损坏的文件不会被静默替换）；都不存在时才扫描 exports/ 里内容合法的候选。
    """
    candidates = _export_candidates(out_dir, report, key)
    for path in candidates[:2]:
        if os.path.isfile(path):
            return path
    seen = set()
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            continue
        seen.add(norm)
        if not os.path.isfile(path):
            continue
        if not magic_ok(read_head(path, 8)) or file_size(path) < min_size:
            continue
        return path
    return None


# ---------------------------------------------------------------------------
# 检查器
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self):
        self.items = []

    def ok(self, message):
        self.items.append(("PASS", message))

    def warn(self, message):
        self.items.append(("WARN", message))

    def error(self, message):
        self.items.append(("ERROR", message))

    @property
    def failed(self):
        return any(level == "ERROR" for level, _ in self.items)

    def summary(self):
        counts = {"PASS": 0, "WARN": 0, "ERROR": 0}
        for level, _ in self.items:
            counts[level] += 1
        return counts


def check_required_files(checker, out_dir):
    files = {
        "model.py": os.path.join(out_dir, "model.py"),
        "brief.md": os.path.join(out_dir, "brief.md"),
        "report.json": os.path.join(out_dir, "report.json"),
    }
    for label, path in files.items():
        if os.path.isfile(path) and file_size(path) > 0:
            checker.ok("必需文件: %s (%.1f KB)" % (label, file_size(path) / 1024.0))
        else:
            checker.error("缺少或为空: %s" % path)

    report = load_json(os.path.join(out_dir, "report.json"))
    for key, min_size, magic_ok in (
        ("blend", MIN_BLEND_BYTES, is_blend_bytes),
        ("glb", MIN_GLB_BYTES, is_glb_bytes),
    ):
        path = find_export_file(out_dir, report, key, magic_ok, min_size)
        if path is None:
            checker.error(
                "缺少导出文件: 未找到 .%s（查了 report 记录、exports/model.%s 与 exports/ 目录）" % (key, key))
            continue
        rel = os.path.relpath(path, out_dir).replace(os.sep, "/")
        size = file_size(path)
        head = read_head(path, 8)
        if not magic_ok(head):
            checker.error("导出文件魔数不对（可能损坏）: %s head=%r" % (rel, head))
        elif size < min_size:
            checker.error("导出文件过小: %s (%.1f KB)" % (rel, size / 1024.0))
        else:
            checker.ok("导出文件: %s (%.1f KB)" % (rel, size / 1024.0))

    model_script = os.path.join(out_dir, "model.py")
    if os.path.isfile(model_script):
        try:
            with open(model_script, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        if "BLENDER_KIT_DIR" in text or "blender_kit" in text:
            checker.ok("model.py 通过 BLENDER_KIT_DIR 导入 kit")
        else:
            checker.error("model.py 未导入 blender_kit（脚本不可复现）")


def check_renders(checker, out_dir, min_views):
    renders_dir = os.path.join(out_dir, "renders")
    if not os.path.isdir(renders_dir):
        checker.error("缺少 renders/ 目录: %s" % renders_dir)
        return []
    pngs = []
    for name in sorted(os.listdir(renders_dir)):
        if not name.lower().endswith(".png"):
            continue
        if name == "contact-sheet.png":
            continue
        path = os.path.join(renders_dir, name)
        if os.path.isfile(path):
            pngs.append(path)

    if len(pngs) < min_views:
        checker.error("渲染图数量不足: %d 张 < %d 张" % (len(pngs), min_views))
    else:
        checker.ok("渲染图数量: %d 张" % len(pngs))

    for path in pngs:
        name = os.path.basename(path)
        size = file_size(path)
        dims = png_size(path)
        if dims is None:
            checker.error("渲染图不是合法 PNG: %s (%d bytes)" % (name, size))
            continue
        if dims[0] < MIN_VIEW_SIZE or dims[1] < MIN_VIEW_SIZE:
            checker.error("渲染图尺寸过小: %s (%dx%d < %d)" % (
                name, dims[0], dims[1], MIN_VIEW_SIZE))
        elif size < MIN_PNG_BYTES:
            checker.error("渲染图过小，疑似空/黑图: %s (%.1f KB)" % (name, size / 1024.0))
        else:
            checker.ok("渲染图: %s %dx%d (%.1f KB)" % (name, dims[0], dims[1], size / 1024.0))
    return pngs


def check_report(checker, out_dir):
    report_path = os.path.join(out_dir, "report.json")
    report = load_json(report_path)
    if not isinstance(report, dict):
        checker.error("report.json 缺失或不是合法 JSON: %s" % report_path)
        return

    scene = scene_block(report)
    checks = (
        ("object_count", 1, "物体数量"),
        ("mesh_count", 1, "网格数量"),
        ("total_tris", 8, "三角面数量"),
        ("camera_count", 1, "相机数量"),
        ("light_count", 1, "灯光数量"),
    )
    for key, minimum, label in checks:
        value = scene.get(key)
        if not _is_number(value):
            checker.error("report.scene.%s 缺失或不是数字: %r" % (key, value))
        elif value < minimum:
            checker.error("report.scene.%s=%r 低于要求 %r（%s）" % (key, value, minimum, label))
        else:
            checker.ok("%s: %s" % (label, value))

    dims = scene.get("dimensions")
    if not isinstance(dims, (list, tuple)) or len(dims) != 3:
        checker.error("report.scene.dimensions 必须是 3 个数字: %r" % (dims,))
    else:
        try:
            positive = all(_is_number(d) and float(d) > 1e-6 for d in dims)
        except (TypeError, ValueError):
            positive = False
        if positive:
            checker.ok("模型尺寸: %.3f x %.3f x %.3f 米" % tuple(float(d) for d in dims))
        else:
            checker.error("模型尺寸存在非正数或非数字: %r" % (dims,))

    exports = export_paths(report)
    # export_paths 只返回路径字符串；bytes 字段要回原始 exports 记录里取
    exports_doc = report.get("exports")
    if not isinstance(exports_doc, dict):
        exports_doc = {}
    for key in ("blend", "glb"):
        raw = exports.get(key)
        record = exports_doc.get(key)
        if raw is None:
            # AGENTS 第 11 节 ERROR 关键字要求单独报「report 缺少 blend/glb 记录」，
            # 不能复用「相对路径」文案（否则排查时会被误导成路径问题）。
            checker.error("report 缺少 %s 导出记录（report.json 的 exports.%s）" % (key, key))
            continue
        path = resolve_out_path(out_dir, raw)
        if path is None:
            checker.error("report 的导出路径必须是相对路径: %r" % (raw,))
        elif os.path.isfile(path):
            actual = file_size(path)
            recorded = record.get("bytes") if isinstance(record, dict) else None
            if _is_number(recorded) and actual >= 0 and int(recorded) != actual:
                # 旧版 report 的 bytes 可能陈旧（甚至只更新了文件没更新字段），
                # 按 AGENTS「WARN 可带过」口径：只 WARN，不阻断交付。
                checker.warn(
                    "report 记录 %s bytes=%d 与实际文件大小 %d 不一致"
                    "（WARN：旧版 report 可能未更新，不阻断交付）"
                    % (key, int(recorded), actual))
            else:
                checker.ok("report 记录导出 %s" % key)
        else:
            checker.error("report 缺少 %s 导出记录或文件不存在: %r" % (key, raw))

    entries = render_entries(report)
    if not entries:
        checker.error("report.renders 为空：缺少渲染统计，无法判定是否全黑")
        return
    for entry in entries:
        Path = entry.get("path") or entry.get("file")
        std = entry.get("std")
        black_ratio = entry.get("black_ratio")
        label = os.path.basename(str(Path)) if Path else "?"
        if not _is_number(std):
            checker.error("渲染统计缺少 std（%s）" % label)
        elif float(std) <= MIN_STD:
            checker.error("渲染图疑似纯色/全黑（std=%.2f <= %.1f）: %s" % (float(std), MIN_STD, label))
        else:
            checker.ok("渲染统计正常: %s std=%.1f" % (label, float(std)))
        if not _is_number(black_ratio):
            checker.error("渲染统计缺少 black_ratio（%s）" % label)
        elif float(black_ratio) >= MAX_BLACK_RATIO:
            checker.error("渲染图黑像素占比过高（%.3f）: %s" % (float(black_ratio), label))
        resolved = resolve_out_path(out_dir, Path)
        if resolved is None:
            checker.error("渲染统计里的路径必须是相对路径: %r" % (Path,))
        elif not os.path.isfile(resolved):
            checker.error("渲染统计记录的文件不存在: %s" % resolved)


def run_checks(out_dir, min_views=3):
    checker = Checker()
    if not os.path.isdir(out_dir):
        checker.error("输出目录不存在: %s" % out_dir)
        return checker
    check_required_files(checker, out_dir)
    check_renders(checker, out_dir, min_views)
    check_report(checker, out_dir)
    return checker


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8cfc0f01f0005000101a5f645b0"
    "0000000049454e44ae426082"
)


def _png_header(width, height):
    """生成一个只有 IHDR 的合法 PNG 头（用于自测构造任意尺寸的假图）。"""
    import zlib
    ihdr = struct.pack(">IIBBBBB", int(width), int(height), 8, 6, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(
        ">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    return PNG_MAGIC + chunk


def selftest():
    failures = []

    def expect(name, condition):
        if condition:
            print("[PASS] selftest: " + name)
        else:
            print("[FAIL] selftest: " + name)
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="bm-check-selftest-") as tmp:
        png_path = os.path.join(tmp, "tiny.png")
        with open(png_path, "wb") as fh:
            fh.write(_TINY_PNG)
        expect("png_size 解析 1x1", png_size(png_path) == (1, 1))

        big_header_png = os.path.join(tmp, "512.png")
        with open(big_header_png, "wb") as fh:
            fh.write(_png_header(512, 512))
        expect("png_size 解析 512x512", png_size(big_header_png) == (512, 512))

        bad_png = os.path.join(tmp, "bad.png")
        with open(bad_png, "wb") as fh:
            fh.write(b"not a png")
        expect("png_size 拒绝非法 PNG", png_size(bad_png) is None)

        blend = os.path.join(tmp, "a.blend")
        with open(blend, "wb") as fh:
            fh.write(BLEND_MAGIC + b"x" * 100)
        expect("blend 魔数", is_blend_bytes(read_head(blend, 8)))
        glb = os.path.join(tmp, "a.glb")
        with open(glb, "wb") as fh:
            fh.write(GLB_MAGIC + b"x" * 100)
        expect("glb 魔数", is_glb_bytes(read_head(glb, 8)))

        expect("scene_block 扁平", scene_block({"object_count": 3}) .get("object_count") == 3)
        expect("scene_block 嵌套", scene_block({"scene": {"object_count": 5}})["object_count"] == 5)
        report = {
            "object_count": 1, "mesh_count": 1, "total_tris": 12,
            "camera_count": 1, "light_count": 3, "dimensions": [1.0, 1.0, 1.0],
            "exports": {
                "blend": {"path": "exports/model.blend"},
                "glb": {"path": "exports/model.glb"},
            },
            "renders": [{"path": "renders/view-front.png", "std": 20.0, "black_ratio": 0.1}],
        }
        expect("export_paths", export_paths(report)["glb"] == "exports/model.glb")
        expect("render_entries", len(render_entries(report)) == 1)
        expect("resolve_out_path 相对路径",
               resolve_out_path(tmp, "renders/x.png") == os.path.join(tmp, "renders", "x.png"))
        expect("resolve_out_path 拒绝绝对路径",
               resolve_out_path(tmp, "C:/Users/x/renders/a.png") is None)
        expect("resolve_out_path 拒绝反斜杠绝对路径",
               resolve_out_path(tmp, "C:\\Users\\x\\a.png") is None)

        checker = Checker()
        checker.ok("x")
        expect("checker 不失败", not checker.failed)
        checker.error("y")
        expect("checker 失败", checker.failed)

        # 构造最小输出目录，验证 run_checks 的导出文件定位：规范名、模式 B 名、
        # 缺失、内容损坏（最后两种必须 ERROR，防止放宽文件名后出现假绿）。
        def build_out(name, export_files, exports_record):
            base = os.path.join(tmp, name)
            os.makedirs(os.path.join(base, "renders"))
            os.makedirs(os.path.join(base, "exports"))
            with open(os.path.join(base, "model.py"), "w", encoding="utf-8") as fh:
                fh.write('import os, sys\nsys.path.insert(0, os.environ["BLENDER_KIT_DIR"])\nimport blender_kit\n')
            with open(os.path.join(base, "brief.md"), "w", encoding="utf-8") as fh:
                fh.write("# brief\n")
            with open(os.path.join(base, "renders", "view-front.png"), "wb") as fh:
                fh.write(_png_header(512, 512) + b"\x00" * (16 * 1024))
            for rel, payload in export_files.items():
                path = os.path.join(base, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(payload)
            payload = dict(report)
            payload["exports"] = exports_record
            with open(os.path.join(base, "report.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            return base

        def expect_out(name, built):
            result = run_checks(built, min_views=1)
            expect(name, not result.failed)
            if result.failed:
                for level, message in result.items:
                    if level == "ERROR":
                        print("       ERROR: " + message)
            return result

        canonical_exports = {
            "blend": {"path": "exports/model.blend"},
            "glb": {"path": "exports/model.glb"},
        }
        out = build_out("out", {
            "exports/model.blend": BLEND_MAGIC + b"\x00" * 2048,
            "exports/model.glb": GLB_MAGIC + b"\x00" * 1024,
        }, canonical_exports)
        expect_out("最小合法输出目录 0 ERROR", out)

        # 模式 B（AGENTS 10.5）：report 记录 model-edited.*，规范名不存在
        mode_b_exports = {
            "blend": {"path": "exports/model-edited.blend"},
            "glb": {"path": "exports/model-edited.glb"},
        }
        mode_b = build_out("out-mode-b", {
            "exports/model-edited.blend": BLEND_MAGIC + b"\x00" * 2048,
            "exports/model-edited.glb": GLB_MAGIC + b"\x00" * 1024,
        }, mode_b_exports)
        expect_out("模式 B export（model-edited.*）0 ERROR", mode_b)

        # report 的 exports.bytes 与实际文件大小不一致：只 WARN，不阻断（旧版 report 可能陈旧）
        exact_exports = {
            "blend": {"path": "exports/model.blend",
                      "bytes": len(BLEND_MAGIC) + 2048},
            "glb": {"path": "exports/model.glb",
                    "bytes": len(GLB_MAGIC) + 1024},
        }
        exact = build_out("out-bytes-exact", {
            "exports/model.blend": BLEND_MAGIC + b"\x00" * 2048,
            "exports/model.glb": GLB_MAGIC + b"\x00" * 1024,
        }, exact_exports)
        exact_result = expect_out("bytes 与实际一致 0 WARN", exact)
        expect("bytes 一致不产生 WARN",
               not any(level == "WARN" for level, _ in exact_result.items))

        stale_exports = {
            "blend": {"path": "exports/model.blend", "bytes": 123},
            "glb": {"path": "exports/model.glb", "bytes": 456},
        }
        stale = build_out("out-bytes-stale", {
            "exports/model.blend": BLEND_MAGIC + b"\x00" * 2048,
            "exports/model.glb": GLB_MAGIC + b"\x00" * 1024,
        }, stale_exports)
        stale_result = expect_out("bytes 陈旧只 WARN 不阻断", stale)
        expect("bytes 陈旧产生 2 条 WARN",
               sum(1 for level, _ in stale_result.items if level == "WARN") >= 2)

        # 没有任何导出文件仍必须 ERROR（不能因为放宽文件名而假绿）
        empty_out = build_out("out-no-exports", {}, canonical_exports)
        missing = run_checks(empty_out, min_views=1)
        expect("缺导出文件仍报 ERROR", missing.failed)
        expect("缺导出文件报满 2 条 ERROR",
               sum(1 for level, _ in missing.items if level == "ERROR") >= 2)

        # report 记录的规范名存在但内容不是合法 blend：必须 ERROR，不许用扫描掩盖
        corrupt_out = build_out("out-corrupt", {
            "exports/model.blend": b"not-a-blend",
            "exports/model.glb": GLB_MAGIC + b"\x00" * 1024,
        }, canonical_exports)
        corrupt = run_checks(corrupt_out, min_views=1)
        expect("损坏的规范名导出仍报 ERROR", corrupt.failed)

        # 规范名 exports/model.* 不能被 exports/ 里排序更靠前的损坏文件遮蔽
        #（旧实现规范名候选拼成 exports/blend，扫描结果顶替了优先级位 → 假「魔数不对」）。
        shadowed = build_out("out-canonical-shadowed", {
            "exports/aaa_broken.blend": b"NOT-A-BLEND",
            "exports/aaa_broken.glb": b"NOT-A-GLTF0",
            "exports/model.blend": BLEND_MAGIC + b"\x00" * 2048,
            "exports/model.glb": GLB_MAGIC + b"\x00" * 1024,
        }, {})  # report 故意不带 exports 记录
        shadow = run_checks(shadowed, min_views=1)
        shadow_msgs = [message for _level, message in shadow.items]
        expect("规范名导出不被同目录损坏文件遮蔽",
               not any("魔数" in message for message in shadow_msgs))
        expect("缺 exports 记录时明确报缺少记录",
               any("缺少 blend 导出记录" in message for message in shadow_msgs))
        expect("缺 exports 记录不误报相对路径: None",
               not any("相对路径: None" in message for message in shadow_msgs))

        # 宽松匹配能力必须保留：非规范文件名（report 无记录）仍要用 exports/ 扫描兜住。
        loose = build_out("out-loose-name", {
            "exports/deliverable.blend": BLEND_MAGIC + b"\x00" * 2048,
            "exports/deliverable.glb": GLB_MAGIC + b"\x00" * 1024,
        }, {})
        loose_result = run_checks(loose, min_views=1)
        expect("非规范文件名仍能通过 exports 扫描定位",
               not any("缺少导出文件" in message or "魔数" in message
                       for _level, message in loose_result.items))

    if failures:
        print("\nSELFTEST FAILED: %d 项失败" % len(failures))
        return 1
    print("\nSELFTEST OK")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Blender 建模输出目录交付闸门")
    parser.add_argument("--out", default=None, help="待检查的输出目录")
    parser.add_argument("--min-views", type=int, default=3, help="至少需要的渲染图张数（默认 3）")
    parser.add_argument("--selftest", action="store_true", help="只运行纯函数自测")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.out:
        parser.error("必须提供 --out <输出目录>（或使用 --selftest）")
    if args.min_views < 1:
        parser.error("--min-views 必须 >= 1（至少要求 1 张渲染图）")

    out_dir = os.path.abspath(args.out)
    checker = run_checks(out_dir, min_views=args.min_views)
    counts = checker.summary()

    if args.json:
        payload = {
            "out": out_dir,
            "ok": not checker.failed,
            "counts": counts,
            "items": [{"level": level, "message": message} for level, message in checker.items],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=== check_output: %s ===" % out_dir)
        for level, message in checker.items:
            print("[%s] %s" % (level, message))
        print("\n=== 结果: %d PASS / %d ERROR / %d WARN ===" % (
            counts["PASS"], counts["ERROR"], counts["WARN"]))
        if checker.failed:
            print("交付闸门未通过：修复上面的 ERROR 后重跑 check_output.py")
        else:
            print("交付闸门通过（WARN 需人工确认不影响交付）。")
    return 1 if checker.failed else 0


if __name__ == "__main__":
    sys.exit(main())
