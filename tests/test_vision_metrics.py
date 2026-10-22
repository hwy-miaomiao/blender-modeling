# -*- coding: utf-8 -*-
"""vision_metrics.py 的纯函数测试：分割、量化指标、阈值闸门。

只依赖标准库（Pillow 是可选依赖，这里不碰真实图片解码）。在仓库根目录运行：

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import vision_metrics as vm  # noqa: E402


def make_image(width, height, boxes):
    """灰色（128,128,128）背景 + 若干实心方块；boxes 元素为 (x0, y0, x1, y1, color)。"""
    pixels = [(128, 128, 128)] * (width * height)
    for x0, y0, x1, y1, color in boxes:
        for y in range(y0, y1):
            base = y * width
            for x in range(x0, x1):
                pixels[base + x] = color
    return pixels


WHITE = (240, 240, 240)


def codes_of(issues):
    return [item["code"] for item in issues]


class AnalyzePixelsTest(unittest.TestCase):
    def test_centered_subject_metrics(self):
        metrics = vm.analyze_pixels(200, 200, make_image(200, 200, [(60, 70, 140, 130, WHITE)]))
        self.assertGreater(metrics["subject_ratio"], vm.SUBJECT_RATIO_MIN)
        self.assertLess(metrics["subject_ratio"], vm.SUBJECT_RATIO_MAX)
        for side in ("left", "right", "top", "bottom"):
            self.assertGreater(metrics["margins"][side], vm.MARGIN_MIN)
        self.assertEqual(metrics["bottom_gap"], metrics["margins"]["bottom"])
        self.assertAlmostEqual(
            metrics["subject_ratio"] + metrics["background_ratio"], 1.0, places=6)
        for key in ("mean", "std", "p10", "p50", "p90"):
            self.assertIn(key, metrics["luminance"])
        self.assertEqual(vm.gate_view(metrics), [])

    def test_uniform_image_has_no_subject(self):
        metrics = vm.analyze_pixels(64, 64, [(128, 128, 128)] * (64 * 64))
        self.assertLess(metrics["subject_ratio"], vm.SUBJECT_RATIO_MIN)
        self.assertIn("VISION001", codes_of(vm.gate_view(metrics)))

    def test_bad_pixel_count_raises(self):
        with self.assertRaises(ValueError):
            vm.analyze_pixels(4, 4, [(0, 0, 0)])


class GateViewTest(unittest.TestCase):
    def _view(self, ratio=0.2, margins=None, bottom=None, mean=128.0, std=30.0):
        margins = dict(margins or {"left": 0.2, "right": 0.2, "top": 0.2, "bottom": 0.2})
        if bottom is not None:
            margins["bottom"] = bottom
        return {
            "subject_ratio": ratio,
            "margins": margins,
            "bottom_gap": margins["bottom"],
            "luminance": {"mean": mean, "std": std},
        }

    def test_clean_view_passes(self):
        self.assertEqual(vm.gate_view(self._view()), [])

    def test_too_small_subject(self):
        codes = codes_of(vm.gate_view(self._view(ratio=0.01)))
        self.assertIn("VISION001", codes)

    def test_too_large_subject(self):
        codes = codes_of(vm.gate_view(self._view(ratio=0.95)))
        self.assertIn("VISION002", codes)

    def test_clipped_margin(self):
        margins = {"left": 0.0, "right": 0.2, "top": 0.2, "bottom": 0.2}
        self.assertIn("VISION003", codes_of(vm.gate_view(self._view(margins=margins))))

    def test_bottom_gap_warn_and_error(self):
        warn = codes_of(vm.gate_view(self._view(bottom=0.50)))
        self.assertIn("VISION005", warn)
        self.assertNotIn("VISION004", warn)
        error = codes_of(vm.gate_view(self._view(bottom=0.70)))
        self.assertIn("VISION004", error)

    def test_dark_flat_image(self):
        codes = codes_of(vm.gate_view(self._view(ratio=0.0, mean=5.0, std=2.0)))
        self.assertIn("VISION006", codes)
        self.assertIn("VISION007", codes)


class AnalyzeOutTest(unittest.TestCase):
    def test_missing_renders_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = vm.analyze_out(tmp)
        self.assertFalse(result["ok"])
        self.assertIn("VISION000", codes_of(result["issues"]))
        self.assertEqual(result["totals"]["view_count"], 0)

    @unittest.skipUnless(vm.pillow_available(), "Pillow 未安装（可选依赖）")
    def test_undecodable_png_is_error_not_skip(self):
        # B1：全部渲染图无法解码时「无法判定」不能当成通过，必须 VISION008 ERROR。
        # 无 Pillow 时 analyze_out 本就无法解码任何图片，语义上只能 SKIP，因此整例跳过
        # （与 tests/README.md「Pillow 用例自动跳过」保持一致，R2-B1）。
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            with open(os.path.join(renders, "view-front.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
            result = vm.analyze_out(tmp)
        self.assertEqual(result["views"], [])
        self.assertIn("VISION008", codes_of(result["issues"]))
        self.assertFalse(result["ok"])
        self.assertIn("view-front.png", result.get("skipped", []))

    @unittest.skipUnless(vm.pillow_available(), "Pillow 未安装（可选依赖）")
    def test_partial_undecodable_png_is_skipped_and_reported(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            Image.new("RGB", (512, 512), (128, 128, 128)).save(
                os.path.join(renders, "view-front.png"))
            with open(os.path.join(renders, "view-bad.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
            result = vm.analyze_out(tmp)
        self.assertEqual(len(result["views"]), 1)
        self.assertIn("view-bad.png", result.get("skipped", []))
        self.assertNotIn("VISION008", codes_of(result["issues"]))
        # R9-B9：部分坏图时独立 CLI 的 ok 不能仍为 True（与 check_output 的
        # VISION009 ERROR 口径一致），必须给出 VISION009 并失败。
        self.assertIn("VISION009", codes_of(result["issues"]))
        self.assertFalse(result["ok"])

    def test_analyze_image_missing_file_returns_none(self):
        missing = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-render.png")
        self.assertIsNone(vm.analyze_image(missing))
        self.assertIsNone(vm.load_pixels(missing))

    @unittest.skipUnless(vm.pillow_available(), "Pillow 未安装（可选依赖）")
    def test_attach_to_report_writes_vision_field(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            Image.new("RGB", (512, 512), (128, 128, 128)).save(
                os.path.join(renders, "view-front.png"))
            report_path = os.path.join(tmp, "report.json")
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({"object_count": 1}, handle)
            attached = vm.attach_to_report(tmp, backfill=False)
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        self.assertTrue(attached["attached"])
        self.assertEqual(report["vision"]["version"], vm.VISION_VERSION)
        self.assertNotIn("backfill", report["vision"])

    @unittest.skipUnless(vm.pillow_available(), "Pillow 未安装（可选依赖）")
    def test_attach_to_report_backfill_marks_migration(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            Image.new("RGB", (512, 512), (128, 128, 128)).save(
                os.path.join(renders, "view-front.png"))
            report_path = os.path.join(tmp, "report.json")
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({"object_count": 1}, handle)
            vm.attach_to_report(tmp, backfill=True)
            with open(report_path, "r", encoding="utf-8") as handle:
                vision = json.load(handle)["vision"]
        self.assertIs(vision.get("backfill"), True)
        self.assertIn("backfilled_at", vision)


class AtomicWriteTest(unittest.TestCase):
    """B6：report.json 回写必须原子替换，失败时不能留下半截文件。"""

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_write_report_replaces_and_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"old": 1}')
            vm._write_report(path, {"new": 2})
            self.assertEqual(self._read(path), {"new": 2})
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_write_report_failure_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"old": 2}')
            with mock.patch.object(vm.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    vm._write_report(path, {"new": 3})
            self.assertEqual(self._read(path), {"old": 2})
            self.assertFalse(os.path.exists(path + ".tmp"))


class SelftestTest(unittest.TestCase):
    def test_selftest_passes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vm.selftest(), 0)


if __name__ == "__main__":
    unittest.main()
