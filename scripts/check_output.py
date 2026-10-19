# -*- coding: utf-8 -*-
"""交付闸门：检查 blender-models 输出目录是否达到可交付标准。

用法：
    python scripts/check_output.py --out <输出目录>
    python scripts/check_output.py --out <输出目录> --min-views 4
    python scripts/check_output.py --selftest      # 纯函数自测，不需要真实输出

检查内容：
- 必需文件：model.py / brief.md / report.json / exports/model.blend / exports/model.glb
- 文件魔数与尺寸：.blend 以 BLENDER（或 gzip）开头，.glb 以 glTF 开头，非空
- renders/ 至少有 --min-views 张 PNG，每张有真实内容（>15 KB），并校验 PNG 头部合法
- report.json 场景统计：物体/网格/三角面/尺寸/相机/灯光/导出记录
- report.json 渲染统计：std>4.0 且 black_ratio<0.98（防止交付全黑图）
- model.py 通过 BLENDER_KIT_DIR 导入 kit（防止交付跑不起来的脚本）

通过条件：0 ERROR。WARN 需人工判断。退出码：通过 0，失败 1。
"""

from __future__ import annotations

import argparse
import json
import os
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
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(out_dir, path.replace("/", os.sep))


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

    blend = os.path.join(out_dir, "exports", "model.blend")
    glb = os.path.join(out_dir, "exports", "model.glb")
    for label, path, min_size, magic_ok in (
        ("model.blend", blend, MIN_BLEND_BYTES, is_blend_bytes),
        ("model.glb", glb, MIN_GLB_BYTES, is_glb_bytes),
    ):
        if not os.path.isfile(path):
            checker.error("缺少导出文件: %s" % path)
            continue
        size = file_size(path)
        head = read_head(path, 8)
        if not magic_ok(head):
            checker.error("导出文件魔数不对（可能损坏）: %s head=%r" % (path, head))
        elif size < min_size:
            checker.error("导出文件过小: %s (%.1f KB)" % (path, size / 1024.0))
        else:
            checker.ok("导出文件: %s (%.1f KB)" % (label, size / 1024.0))

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
        if size < MIN_PNG_BYTES:
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
        if not isinstance(value, (int, float)):
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
            positive = all(float(d) > 1e-6 for d in dims)
        except (TypeError, ValueError):
            positive = False
        if positive:
            checker.ok("模型尺寸: %.3f x %.3f x %.3f 米" % tuple(float(d) for d in dims))
        else:
            checker.error("模型尺寸存在非正数: %r" % (dims,))

    exports = export_paths(report)
    for key in ("blend", "glb"):
        path = resolve_out_path(out_dir, exports.get(key))
        if path and os.path.isfile(path):
            checker.ok("report 记录导出 %s" % key)
        else:
            checker.error("report 缺少 %s 导出记录或文件不存在: %r" % (key, exports.get(key)))

    entries = render_entries(report)
    if not entries:
        checker.error("report.renders 为空：缺少渲染统计，无法判定是否全黑")
        return
    for entry in entries:
        Path = entry.get("path") or entry.get("file")
        std = entry.get("std")
        black_ratio = entry.get("black_ratio")
        label = os.path.basename(Path) if Path else "?"
        if not isinstance(std, (int, float)):
            checker.error("渲染统计缺少 std（%s）" % label)
        elif float(std) <= MIN_STD:
            checker.error("渲染图疑似纯色/全黑（std=%.2f <= %.1f）: %s" % (float(std), MIN_STD, label))
        else:
            checker.ok("渲染统计正常: %s std=%.1f" % (label, float(std)))
        if not isinstance(black_ratio, (int, float)):
            checker.error("渲染统计缺少 black_ratio（%s）" % label)
        elif float(black_ratio) >= MAX_BLACK_RATIO:
            checker.error("渲染图黑像素占比过高（%.3f）: %s" % (float(black_ratio), label))
        resolved = resolve_out_path(out_dir, Path)
        if resolved and not os.path.isfile(resolved):
            checker.warn("渲染统计记录的文件不存在: %s" % resolved)


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

        checker = Checker()
        checker.ok("x")
        expect("checker 不失败", not checker.failed)
        checker.error("y")
        expect("checker 失败", checker.failed)

        # 构造一个合法的最小输出目录，验证 run_checks 能给出 0 ERROR
        out = os.path.join(tmp, "out")
        os.makedirs(os.path.join(out, "renders"))
        os.makedirs(os.path.join(out, "exports"))
        with open(os.path.join(out, "model.py"), "w", encoding="utf-8") as fh:
            fh.write('import os, sys\nsys.path.insert(0, os.environ["BLENDER_KIT_DIR"])\nimport blender_kit\n')
        with open(os.path.join(out, "brief.md"), "w", encoding="utf-8") as fh:
            fh.write("# brief\n")
        big_png = os.path.join(out, "renders", "view-front.png")
        with open(big_png, "wb") as fh:
            fh.write(_TINY_PNG + b"\x00" * (16 * 1024))
        with open(os.path.join(out, "exports", "model.blend"), "wb") as fh:
            fh.write(BLEND_MAGIC + b"\x00" * 2048)
        with open(os.path.join(out, "exports", "model.glb"), "wb") as fh:
            fh.write(GLB_MAGIC + b"\x00" * 1024)
        with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh)
        valid = run_checks(out, min_views=1)
        expect("最小合法输出目录 0 ERROR", not valid.failed)
        if valid.failed:
            for level, message in valid.items:
                if level == "ERROR":
                    print("       ERROR: " + message)

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

    out_dir = os.path.abspath(args.out)
    print("=== check_output: %s ===" % out_dir)
    checker = run_checks(out_dir, min_views=args.min_views)

    if args.json:
        print(json.dumps([{"level": lv, "message": msg} for lv, msg in checker.items],
                         ensure_ascii=False, indent=2))
    else:
        for level, message in checker.items:
            print("[%s] %s" % (level, message))

    counts = checker.summary()
    print("\n=== 结果: %d PASS / %d ERROR / %d WARN ===" % (
        counts["PASS"], counts["ERROR"], counts["WARN"]))
    if checker.failed:
        print("交付闸门未通过：修复上面的 ERROR 后重跑 check_output.py")
        return 1
    print("交付闸门通过（WARN 需人工确认不影响交付）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
