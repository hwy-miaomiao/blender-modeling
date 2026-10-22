# -*- coding: utf-8 -*-
"""check_output.py 的视觉闸门集成测试（B1/B2/B9/B10/R3-B1 回归）。

用 Pillow 生成「灰底噪声 + 白色主体」的真实渲染图（能够被解码、指标稳定），
覆盖：无法解码必须 ERROR、部分无法解码必须 ERROR（不得只 WARN）、backfill 存量迁移、
空迭代表必须 ERROR、report.vision 逐字段对照与 ok 一致性、
report.renders 统计重算对照（B10 残留）。

Pillow 是可选依赖：未安装时整组用例 skip。在仓库根目录运行：

    python -m unittest discover -s tests -v
"""

import contextlib
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import check_output  # noqa: E402
import vision_metrics  # noqa: E402


def _pillow_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


# 256x256 工作画布上的主体矩形（缩放到 512x512 保存）
VIEW_BOXES = {
    "view-front.png": (80, 50, 176, 200),
    "view-right.png": (75, 60, 180, 195),
    "view-iso.png": (70, 55, 185, 198),
}
ITERATION_TABLE = (
    "| 轮次 | 看了哪张图（read_image 证据） | 问题（证据） | 改了什么 | 重跑结果（量化值） |\n"
    "| --- | --- | --- | --- | --- |\n"
)
NEW_STYLE_ROW = (
    "| 1 | renders/view-front.png | 杯柄偏细（front 视角） | handle.radius 0.05 | "
    "mean=164、std=62、主体=19.9% |\n"
)
LEGACY_ROW = "| 1 | right 视角杯柄只剩一条竖线 | handle.radius 0.05 | mean=153-178 |\n"


_PNG_CACHE = {}


def _render_png_bytes(name, box):
    """生成可解码、指标稳定的 512x512 渲染图（平滑噪声背景 + 白色主体）。"""
    from PIL import Image, ImageDraw
    width = height = 256
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    data = bytearray()
    index = 0
    for y in range(height):
        for x in range(width):
            base = 128 + 15 * math.sin(x / 23.0) + 10 * math.cos(y / 17.0) \
                + 8 * math.sin((x + y) / 31.0)
            dither = (digest[index % 32] % 7) - 3
            index += 1
            value = max(0, min(255, int(base) + dither))
            data.extend((value, value, value))
    image = Image.frombytes("RGB", (width, height), bytes(data))
    image = image.resize((512, 512), Image.NEAREST)
    draw = ImageDraw.Draw(image)
    draw.rectangle([box[0] * 2, box[1] * 2, box[2] * 2 - 1, box[3] * 2 - 1],
                   fill=(240, 240, 240))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_out(tmp, iteration_body=NEW_STYLE_ROW, boxes=None):
    """构造一个结构完整的产物目录（3 视角 + 导出 + report）。"""
    out = os.path.join(tmp, "out")
    renders = os.path.join(out, "renders")
    exports = os.path.join(out, "exports")
    os.makedirs(renders)
    os.makedirs(exports)
    with open(os.path.join(out, "model.py"), "w", encoding="utf-8") as handle:
        handle.write("import os\nimport sys\n"
                     "sys.path.insert(0, os.environ['BLENDER_KIT_DIR'])\n"
                     "import blender_kit  # noqa: F401\n")
    brief = "# brief\n\n## 迭代记录\n\n" + ITERATION_TABLE + (iteration_body or "")
    with open(os.path.join(out, "brief.md"), "w", encoding="utf-8") as handle:
        handle.write(brief)
    blend_path = os.path.join(exports, "model.blend")
    glb_path = os.path.join(exports, "model.glb")
    with open(blend_path, "wb") as handle:
        handle.write(b"BLENDER-v300" + b"\x00" * 2048)
    with open(glb_path, "wb") as handle:
        handle.write(b"glTF" + b"\x00" * 512)
    render_entries = []
    active_boxes = boxes or VIEW_BOXES
    for name, box in active_boxes.items():
        path = os.path.join(renders, name)
        if name not in _PNG_CACHE:
            _PNG_CACHE[name] = _render_png_bytes(name, box)
        with open(path, "wb") as handle:
            handle.write(_PNG_CACHE[name])
        stats = check_output._recompute_render_stats(path) or {
            "mean": 140.0, "std": 20.0, "black_ratio": 0.0}
        render_entries.append({
            "path": "renders/" + name, "width": 512, "height": 512,
            "bytes": os.path.getsize(path),
            "mean": round(stats["mean"], 4), "std": round(stats["std"], 4),
            "black_ratio": round(stats["black_ratio"], 4),
            "label": name.split(".")[0], "seconds": 1.0,
        })
    report = {
        "object_count": 1, "mesh_count": 1, "camera_count": 1, "light_count": 3,
        "total_verts": 8, "total_tris": 12, "dimensions": [1.0, 1.0, 1.0],
        "renders": render_entries,
        "exports": {
            "blend": {"path": "exports/model.blend", "bytes": os.path.getsize(blend_path)},
            "glb": {"path": "exports/model.glb", "bytes": os.path.getsize(glb_path)},
        },
        "warnings": [],
    }
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return out


def attach_vision(out, backfill):
    with contextlib.redirect_stdout(io.StringIO()):
        return vision_metrics.attach_to_report(out, backfill=backfill)


def run_checks(out):
    with contextlib.redirect_stdout(io.StringIO()):
        return check_output.run_checks(out, min_views=3)


def messages(result, level):
    return [message for item_level, message in result.items if item_level == level]


def read_report(out):
    with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
        return json.load(handle)


def write_report(out, report):
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


@unittest.skipUnless(_pillow_available(), "需要 Pillow 生成真实渲染图")
class VisionGateIntegrationTest(unittest.TestCase):
    def test_clean_new_artifact_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp)
            self.assertTrue(attach_vision(out, backfill=False)["attached"])
            result = run_checks(out)
        self.assertFalse(result.failed, messages(result, "ERROR"))

    def test_tampered_render_stats_is_error(self):
        # B10 残留：report.renders 的 mean/std/black_ratio 必须与 PNG 重算值一致。
        for field, delta in (("std", 5.0), ("black_ratio", 0.5)):
            with tempfile.TemporaryDirectory() as tmp:
                out = build_out(tmp)
                attach_vision(out, backfill=False)
                report = read_report(out)
                report["renders"][0][field] = report["renders"][0][field] + delta
                write_report(out, report)
                result = run_checks(out)
            self.assertTrue(result.failed, messages(result, "ERROR"))
            self.assertTrue(any("report.renders 统计与渲染图不符" in message
                                for message in messages(result, "ERROR")),
                            messages(result, "ERROR"))

    def test_tampered_margins_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp)
            attach_vision(out, backfill=False)
            report = read_report(out)
            report["vision"]["views"][0]["margins"]["left"] += 0.2
            write_report(out, report)
            result = run_checks(out)
        self.assertTrue(result.failed)
        self.assertTrue(any("report.vision 与实测不一致" in message
                            for message in messages(result, "ERROR")),
                        messages(result, "ERROR"))

    def test_vision_ok_mismatch_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp)
            attach_vision(out, backfill=False)
            report = read_report(out)
            report["vision"]["ok"] = False
            write_report(out, report)
            result = run_checks(out)
        self.assertFalse(result.failed, messages(result, "ERROR"))
        self.assertTrue(any("report.vision.ok 与实测不一致" in message
                            for message in messages(result, "WARN")),
                        messages(result, "WARN"))

    def test_all_undecodable_pngs_is_error(self):
        # 坏图 = 块结构与像素流长度都合法、但行过滤类型非法：check_output 的
        # 零依赖结构校验放行，只有 Pillow 解码能判死 → 必须由视觉闸门 ERROR。
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp)
            for name in VIEW_BOXES:
                path = os.path.join(out, "renders", name)
                with open(path, "wb") as handle:
                    handle.write(check_output._png_bad_filter(512, 512))
            result = run_checks(out)
        self.assertTrue(result.failed)
        self.assertTrue(any("全部无法解码" in message
                            for message in messages(result, "ERROR")),
                        messages(result, "ERROR"))

    def test_partial_undecodable_pngs_is_error(self):
        # R3-B1：好图 + 坏图混合时视觉指标覆盖不到全部视角，必须 ERROR（旧行为是 WARN）。
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp)
            attach_vision(out, backfill=False)
            bad_path = os.path.join(out, "renders", "view-right.png")
            with open(bad_path, "wb") as handle:
                handle.write(check_output._png_bad_filter(512, 512))
            result = run_checks(out)
        self.assertTrue(result.failed, messages(result, "ERROR"))
        errors = messages(result, "ERROR")
        self.assertTrue(any("部分渲染图无法解码" in message for message in errors), errors)
        self.assertTrue(any("view-right.png" in message for message in errors), errors)
        self.assertFalse(any("渲染图无法解码已跳过" in message
                             for message in messages(result, "WARN")),
                         messages(result, "WARN"))

    def test_empty_iteration_table_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp, iteration_body="")
            attach_vision(out, backfill=False)
            result = run_checks(out)
        self.assertTrue(result.failed)
        self.assertTrue(any("没有任何数据行" in message
                            for message in messages(result, "ERROR")),
                        messages(result, "ERROR"))

    def test_backfill_migration_allows_legacy_brief(self):
        # B2：存量项目用 vision_metrics --write 补写 vision 后，旧 4 列迭代记录
        # 只校验图片引用，不强制新量化表格式。
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(tmp, iteration_body=LEGACY_ROW)
            self.assertTrue(attach_vision(out, backfill=True)["attached"])
            report = read_report(out)
            self.assertTrue(report["vision"].get("backfill"))
            result = run_checks(out)
        self.assertFalse(result.failed, messages(result, "ERROR"))
        self.assertTrue(any("backfill" in message for item_level, message in result.items
                            if item_level == "PASS"), result.items)

    def test_backfill_still_checks_missing_image_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_out(
                tmp, iteration_body="| 1 | renders/view-missing.png | x | y | z |\n")
            attach_vision(out, backfill=True)
            result = run_checks(out)
        self.assertTrue(result.failed)
        self.assertTrue(any("引用的渲染图不存在" in message
                            for message in messages(result, "ERROR")),
                        messages(result, "ERROR"))


if __name__ == "__main__":
    unittest.main()
