# -*- coding: utf-8 -*-
"""vision_probe.py 的单元测试：纯标准库 PNG 解码 / 空白检测 / 联系表版式复算。

只依赖标准库（不碰 Pillow）。在仓库根目录运行：

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import vision_probe as vp  # noqa: E402


def gradient_png(path, width=96, height=96):
    with open(path, "wb") as handle:
        handle.write(vp._encode_rgb_png(
            width, height, vp._gradient_pixels(width, height)))


def solid_png(path, width=96, height=96, color=(90, 90, 90)):
    with open(path, "wb") as handle:
        handle.write(vp._encode_rgb_png(
            width, height, vp._solid_pixels(width, height, color)))


class DecodeTest(unittest.TestCase):
    def test_structure_issues_accepts_valid_png(self):
        data = vp._encode_rgb_png(8, 8, vp._solid_pixels(8, 8))
        self.assertEqual(vp.structure_issues(data), [])

    def test_structure_issues_rejects_truncated_png(self):
        data = vp._encode_rgb_png(8, 8, vp._solid_pixels(8, 8))
        issues = vp.structure_issues(data[: len(data) // 2])
        self.assertTrue(issues)

    def test_structure_issues_rejects_crc_corruption(self):
        data = bytearray(vp._encode_rgb_png(8, 8, vp._solid_pixels(8, 8)))
        data[30] ^= 0xFF  # 改 IHDR 数据但保留长度/CRC -> CRC 校验失败
        self.assertTrue(vp.structure_issues(bytes(data)))

    def test_decode_png_roundtrip(self):
        flat = vp._gradient_pixels(8, 8)
        decoded = vp.decode_png(vp._encode_rgb_png(8, 8, flat))
        self.assertEqual(decoded["width"], 8)
        self.assertEqual(decoded["height"], 8)
        self.assertEqual(len(decoded["pixels"]), 8 * 8 * 3)
        self.assertEqual(bytes(decoded["pixels"][:3]), flat[:3])

    def test_decode_png_rejects_non_png(self):
        with self.assertRaises(vp.PngError):
            vp.decode_png(b"not a png at all")

    def test_read_png_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view-front.png")
            gradient_png(path, 123, 45)
            self.assertEqual(vp.read_png_header(path), (123, 45))

    def test_image_stats_detects_blank(self):
        decoded = vp.decode_png(vp._encode_rgb_png(
            16, 16, vp._solid_pixels(16, 16)))
        stats = vp.image_stats(decoded)
        self.assertEqual(stats["unique_colors"], 1)
        self.assertLess(stats["luma_std"], 1.0)


class InspectTest(unittest.TestCase):
    def test_good_render_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view-front.png")
            gradient_png(path)
            result = vp.inspect_image(path, expect_size=(96, 96))
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["width"], 96)

    def test_blank_render_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view-front.png")
            solid_png(path)
            result = vp.inspect_image(path)
        self.assertFalse(result["ok"])
        self.assertTrue(any("空白" in reason for reason in result["reasons"]))

    def test_truncated_render_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view-front.png")
            gradient_png(path)
            with open(path, "r+b") as handle:
                data = handle.read()
                handle.seek(0)
                handle.truncate(len(data) // 2)
            result = vp.inspect_image(path)
        self.assertFalse(result["ok"])
        self.assertTrue(result["reasons"])

    def test_wrong_size_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view-front.png")
            gradient_png(path)
            result = vp.inspect_image(path, expect_size=(128, 128))
        self.assertFalse(result["ok"])
        self.assertTrue(any("尺寸" in reason for reason in result["reasons"]))

    def test_missing_file_fails(self):
        result = vp.inspect_image(os.path.join(tempfile.gettempdir(), "no-such.png"))
        self.assertFalse(result["ok"])


class ProbeOutTest(unittest.TestCase):
    def _make_out(self, tmp, declared=(96, 96), blank=False):
        renders = os.path.join(tmp, "renders")
        os.makedirs(renders)
        path = os.path.join(renders, "view-front.png")
        if blank:
            solid_png(path)
        else:
            gradient_png(path)
        report = {"renders": [{"path": "renders/view-front.png",
                               "width": declared[0], "height": declared[1]}]}
        import json
        with open(os.path.join(tmp, "report.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        return tmp

    def test_probe_out_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = vp.probe_out(self._make_out(tmp))
        self.assertTrue(payload["ok"], payload["reasons"])
        self.assertEqual(payload["mode"], "out")
        self.assertEqual(len(payload["files"]), 1)

    def test_probe_out_declared_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = vp.probe_out(self._make_out(tmp, declared=(128, 128)))
        self.assertFalse(payload["ok"])
        self.assertTrue(any("尺寸" in reason for reason in payload["reasons"]))

    def test_probe_out_blank_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = vp.probe_out(self._make_out(tmp, blank=True))
        self.assertFalse(payload["ok"])
        self.assertTrue(any("空白" in reason for reason in payload["reasons"]))

    def test_probe_renders_missing_dir(self):
        payload = vp.probe_renders(os.path.join(
            tempfile.gettempdir(), "definitely-missing-renders-r9"))
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["reasons"])

    def test_list_render_pngs_excludes_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            gradient_png(os.path.join(tmp, "view-front.png"))
            gradient_png(os.path.join(tmp, "contact-sheet.png"))
            names = [os.path.basename(path) for path in vp.list_render_pngs(tmp)]
        self.assertEqual(names, ["view-front.png"])


class SheetGeometryTest(unittest.TestCase):
    def test_geometry_matches_contact_sheet_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in ("view-front.png", "view-iso.png", "view-right.png"):
                path = os.path.join(tmp, name)
                gradient_png(path)
                paths.append(path)
            info = vp.expected_sheet_geometry(paths)
        self.assertTrue(info["ok"], info["reasons"])
        self.assertEqual(info["tiles"], 3)
        self.assertEqual(info["cols"], 2)
        self.assertEqual(info["rows"], 2)
        self.assertEqual(info["cell_width"], 480)
        self.assertEqual(info["width"], 2 * 480 + 3 * 10)
        self.assertEqual(info["height"], 2 * (480 + 24) + 3 * 10)

    def test_bad_params_fail(self):
        self.assertFalse(vp.expected_sheet_geometry([], cols=0)["ok"])
        self.assertFalse(vp.expected_sheet_geometry(
            [os.path.join(tempfile.gettempdir(), "no-such.png")])["ok"])

    def test_selftest_passes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vp.selftest(), 0)


if __name__ == "__main__":
    unittest.main()
