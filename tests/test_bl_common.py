# -*- coding: utf-8 -*-
"""bl_common 单元测试：日志分类、Blender 探测等纯函数（不需要 Blender）。

运行（仓库根目录）：

    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import bl_common  # noqa: E402


class ClassifyLogTests(unittest.TestCase):
    """classify_log 决定「一次 Blender 调用到底算不算失败」，必须稳定。"""

    def test_clean_banner_is_clean(self):
        text = "Blender 4.0.2\nRead prefs: C:\\Users\\me\\AppData\\Roaming\\Blender Foundation\\Blender\\4.0\\config\\userpref.blend\n"
        errors, warnings = bl_common.classify_log(text)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_tbbmalloc_noise_is_ignored(self):
        # 这是 Blender 4.0.2 在 Windows 上每次启动都打的噪音，不能当错误
        text = ("TBBmalloc: skip allocation functions replacement in ucrtbase.dll: "
                "unknown prologue for function _msize\nBlender 4.0.2\n")
        errors, _warnings = bl_common.classify_log(text)
        self.assertEqual(errors, [])

    def test_traceback_and_exception_are_errors(self):
        text = (
            "Traceback (most recent call last):\n"
            "  File \"F:\\tmp\\model.py\", line 3, in <module>\n"
            "RuntimeError: boom\n"
            "Error: script failed, file: 'F:\\tmp\\model.py', exiting.\n"
        )
        errors, _warnings = bl_common.classify_log(text)
        self.assertTrue(any("Traceback" in e for e in errors), errors)
        self.assertTrue(any("RuntimeError: boom" in e for e in errors), errors)

    def test_warnings_are_captured_and_deduplicated(self):
        text = "Warning: something odd\nWarning: something odd\nWarning: other\n"
        errors, warnings = bl_common.classify_log(text)
        self.assertEqual(errors, [])
        self.assertTrue(any("something odd" in w for w in warnings), warnings)
        self.assertEqual(len(warnings), len(set(warnings)), warnings)

    def test_errors_are_capped(self):
        text = "\n".join("Error: failure %d" % i for i in range(120))
        errors, _warnings = bl_common.classify_log(text)
        self.assertLessEqual(len(errors), 25)

    def test_missing_module_is_error(self):
        text = "ModuleNotFoundError: No module named 'blender_kit'\n"
        errors, _warnings = bl_common.classify_log(text)
        self.assertTrue(any("ModuleNotFoundError" in e for e in errors), errors)


class FindBlenderTests(unittest.TestCase):
    def test_result_is_none_or_existing_file(self):
        exe = bl_common.find_blender()
        if exe is None:
            self.skipTest("本机没有 Blender（CI 环境正常）")
        self.assertTrue(os.path.isfile(exe), exe)

    def test_explicit_missing_path_returns_none(self):
        self.assertIsNone(bl_common.find_blender("Z:\\definitely\\not\\blender.exe"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
