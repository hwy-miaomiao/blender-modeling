# -*- coding: utf-8 -*-
"""vision_probe.py 的单元测试：纯标准库 PNG 解码 / 空白检测 / 联系表版式复算。

只依赖标准库（不碰 Pillow）。在仓库根目录运行：

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib

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


def _chunk(ctype, payload):
    return (struct.pack(">I", len(payload)) + ctype + payload
            + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF))


def png_with_idat(width, height, idat, depth=8, color_type=2):
    ihdr = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0)
    return (vp.PNG_MAGIC + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b""))


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


class PixelStreamTest(unittest.TestCase):
    """R9 加固：块结构合法但像素流伪造/截断/解压炸弹必须被识别。"""

    def test_valid_png_has_no_stream_issues(self):
        data = vp._encode_rgb_png(32, 32, vp._gradient_pixels(32, 32))
        self.assertEqual(vp.pixel_stream_issues(data), [])

    def test_garbage_idat_rejected(self):
        data = png_with_idat(32, 32, b"definitely-not-zlib" * 16)
        issues = vp.pixel_stream_issues(data)
        self.assertTrue(any("无法解压" in issue for issue in issues), issues)
        with self.assertRaises(vp.PngError):
            vp.decode_png(data)

    def test_truncated_pixel_stream_rejected(self):
        need = 32 * (32 * 3 + 1)
        stream = zlib.compress(b"\x00" * need, 9)
        data = png_with_idat(32, 32, stream[: len(stream) // 3])
        issues = vp.pixel_stream_issues(data)
        self.assertTrue(any("不完整" in issue or "无法解压" in issue
                            for issue in issues), issues)

    def test_decompression_bomb_rejected_fast(self):
        bomb = png_with_idat(
            64, 64, zlib.compress(b"\x00" * (8 * 1024 * 1024), 9))
        started = time.time()
        issues = vp.pixel_stream_issues(bomb)
        self.assertLess(time.time() - started, 2.0)
        self.assertTrue(any("超出声明尺寸" in issue for issue in issues), issues)
        with self.assertRaises(vp.PngError):
            vp.decode_png(bomb)

    def test_stream_length_mismatch_rejected(self):
        # 声明 32x32 RGB 需要 32*(96+1)=3104 字节，却只给一半（zlib 合法结尾）
        data = png_with_idat(32, 32, zlib.compress(b"\x00" * 1552, 9))
        issues = vp.pixel_stream_issues(data)
        self.assertTrue(any("长度与声明尺寸不符" in issue for issue in issues),
                        issues)

    def test_16bit_downgrades_without_false_positive(self):
        data = png_with_idat(8, 8, b"", depth=16)
        self.assertEqual(vp.pixel_stream_issues(data), [])


class CliTest(unittest.TestCase):
    def test_sheet_with_dir_is_argument_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            gradient_png(os.path.join(renders, "view-front.png"))
            sheet = os.path.join(tmp, "contact-sheet.png")
            gradient_png(sheet)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as caught:
                    vp.main(["--dir", renders, "--sheet", sheet])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--sheet", stderr.getvalue())


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

    def test_probe_out_respects_min_std(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = vp.probe_out(self._make_out(tmp), min_std=10 ** 6)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("对比度过低" in reason for reason in payload["reasons"]))

    def test_probe_out_full_respects_min_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            with open(os.path.join(renders, "view-front.png"), "wb") as handle:
                handle.write(vp._encode_rgb_png(
                    64, 64, vp._gradient_pixels(64, 64)))
            payload = vp.probe_out_full(tmp, min_unique=10 ** 6)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("颜色过少" in reason
                            for reason in payload["reasons"]))

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


def _paeth_predictor(left, up, up_left):
    """PNG filter 4（Paeth）的预测值，用于正向编码测试素材。"""
    p = left + up - up_left
    pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def filtered_png(width, height, pixels, filters=(1, 2, 3, 4)):
    """用真实 PNG 行过滤类型（1=Sub/2=Up/3=Average/4=Paeth）编码像素。

    `pixels` 是 RGB 扁平字节（长度 width*height*3）；按行轮换 `filters`。
    用于验证 vision_probe 的 _unfilter 能正确还原非 filter=0 的真实 PNG。
    """
    bpp, stride = 3, width * 3
    out = bytearray()
    prev = bytes(stride)
    for y in range(height):
        raw = pixels[y * stride:(y + 1) * stride]
        ftype = filters[y % len(filters)]
        out.append(ftype)
        for i in range(stride):
            left = raw[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if ftype == 0:
                value = raw[i]
            elif ftype == 1:
                value = raw[i] - left
            elif ftype == 2:
                value = raw[i] - up
            elif ftype == 3:
                value = raw[i] - ((left + up) // 2)
            elif ftype == 4:
                value = raw[i] - _paeth_predictor(left, up, up_left)
            else:
                raise ValueError("test encoder 只支持 filter 0-4")
            out.append(value & 0xFF)
        prev = raw
    return png_with_idat(width, height, zlib.compress(bytes(out), 6))


class FilterRoundtripTest(unittest.TestCase):
    """5 种 PNG 行过滤类型（0-4）都要能正确还原像素（不只是 filter=0）。"""

    def test_filter_types_1_to_4_roundtrip(self):
        for ftype in (1, 2, 3, 4):
            width, height = 24, 20
            flat = vp._gradient_pixels(width, height)
            decoded = vp.decode_png(filtered_png(width, height, flat, (ftype,)))
            self.assertEqual(bytes(decoded["pixels"]), bytes(flat),
                             "filter=%d 还原失败" % ftype)

    def test_mixed_filters_per_row_roundtrip(self):
        width, height = 24, 20
        flat = vp._gradient_pixels(width, height)
        data = filtered_png(width, height, flat, (0, 1, 2, 3, 4))
        self.assertEqual(bytes(vp.decode_png(data)["pixels"]), bytes(flat))

    def test_unknown_filter_type_rejected(self):
        width, height = 4, 4
        flat = vp._gradient_pixels(width, height)
        stride = width * 3
        raw = bytearray()
        for y in range(height):
            raw.append(9)  # 非法行过滤类型；像素流长度仍与声明尺寸一致
            raw += flat[y * stride:(y + 1) * stride]
        data = png_with_idat(width, height, zlib.compress(bytes(raw)))
        # 零依赖的像素流长度校验只看长度，非法 filter 由真正的解码器报错
        self.assertEqual(vp.pixel_stream_issues(data), [])
        with self.assertRaises(vp.PngError) as ctx:
            vp.decode_png(data)
        self.assertIn("行过滤类型非法", str(ctx.exception))


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
