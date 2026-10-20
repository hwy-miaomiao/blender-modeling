# -*- coding: utf-8 -*-
"""contact_sheet 单元测试：有 Pillow 时验证拼图逻辑，没有时整类跳过（CI 无 Pillow 也不会红）。

运行（仓库根目录）：

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import contact_sheet  # noqa: E402

try:
    from PIL import Image
except ImportError:  # 可选依赖
    Image = None


@unittest.skipIf(Image is None, "需要 Pillow（pip install pillow）")
class BuildSheetTests(unittest.TestCase):
    def _make_renders(self, tmp, labels=("front", "right", "iso", "top")):
        renders = os.path.join(tmp, "renders")
        os.makedirs(renders, exist_ok=True)
        for index, label in enumerate(labels):
            color = (60 + index * 40, 120, 200 - index * 30)
            Image.new("RGB", (64, 48 - index * 4 if index < 4 else 48), color).save(
                os.path.join(renders, "view-%s.png" % label))
        return renders

    def test_collect_images_prefers_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            renders = self._make_renders(tmp)
            names = [os.path.basename(p) for p in contact_sheet.collect_images(renders)]
            self.assertEqual(names[0], "view-front.png")
            self.assertIn("view-iso.png", names)

    def test_collect_images_prefers_views_over_final(self):
        # 修前 final-front 排在 view-front 前，默认 --max 4 会挤掉 iso 视角
        with tempfile.TemporaryDirectory() as tmp:
            renders = self._make_renders(tmp)
            for index, label in enumerate(("front", "right", "iso")):
                Image.new("RGB", (64, 48), (30, 30 + index * 30, 90)).save(
                    os.path.join(renders, "final-%s.png" % label))
            names = [os.path.basename(p) for p in contact_sheet.collect_images(renders)]
            self.assertEqual(names[:3], ["view-front.png", "view-right.png", "view-iso.png"])
            self.assertEqual(names[4:7], ["final-front.png", "final-right.png", "final-iso.png"])

    def test_collect_images_skips_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            renders = self._make_renders(tmp)
            Image.new("RGB", (10, 10), (0, 0, 0)).save(
                os.path.join(renders, "contact-sheet.png"))
            names = [os.path.basename(p) for p in contact_sheet.collect_images(renders)]
            self.assertNotIn("contact-sheet.png", names)

    def test_build_sheet_creates_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_renders(tmp)
            path = contact_sheet.build_sheet(tmp, cols=2, tile_height=64, max_images=4)
            self.assertIsNotNone(path)
            self.assertTrue(os.path.isfile(path))
            with Image.open(path) as sheet:
                self.assertEqual(sheet.format, "PNG")
                self.assertGreater(sheet.width, 64)
                self.assertGreater(sheet.height, 64)

    def test_build_sheet_returns_none_without_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "renders"))
            self.assertIsNone(contact_sheet.build_sheet(tmp))

    def test_empty_dir_main_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "renders"))
            self.assertEqual(contact_sheet.main(["--out", tmp]), 1)

    def test_missing_dir_main_returns_error(self):
        self.assertEqual(contact_sheet.main(["--out", os.path.join(
            tempfile.gettempdir(), "blender-modeling-no-such-dir")]), 1)


class CliValidationTests(unittest.TestCase):
    """参数校验不依赖 Pillow（在导入/渲染检查之前），CI 无 Pillow 也能回归。"""

    def _assert_parser_error(self, argv):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "renders"))
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    contact_sheet.main(["--out", tmp] + argv)
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("必须", stderr.getvalue())

    def test_invalid_height_rejected(self):
        # 修前 --height 0/-5 会进 Image.resize 抛 ValueError traceback
        for value in ("0", "-5"):
            self._assert_parser_error(["--height", value])

    def test_invalid_cols_and_max_rejected(self):
        self._assert_parser_error(["--cols", "0"])
        self._assert_parser_error(["--max", "0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
