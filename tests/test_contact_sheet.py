# -*- coding: utf-8 -*-
"""contact_sheet 单元测试：有 Pillow 时验证拼图逻辑，没有时整类跳过（CI 无 Pillow 也不会红）。

运行（仓库根目录）：

    python -m unittest discover -s tests -v
"""

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
