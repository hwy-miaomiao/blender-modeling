# -*- coding: utf-8 -*-
"""ci_check.py 的健壮性测试：脏 report.json 不能把仓库检查弄崩（审计 M1/M2 回归）。

只依赖标准库。在仓库根目录运行：

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import ci_check  # noqa: E402


def _make_repo(tmp):
    """搭一个只有 examples/lowpoly-mug/report.json 的假仓库。"""
    example = os.path.join(tmp, "examples", "lowpoly-mug")
    os.makedirs(example)
    return example


def _write_report(example, payload):
    with open(os.path.join(example, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


class CheckExampleRobustness(unittest.TestCase):
    """check_example 遇到结构合法的 JSON 以外的东西必须报 ERROR，不能抛异常。"""

    def _run(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            example = _make_repo(tmp)
            _write_report(example, payload)
            checker = ci_check.Checker(tmp)
            # 关掉 Checker 的逐条打印，保持测试输出干净
            with contextlib.redirect_stdout(io.StringIO()):
                checker.check_example("lowpoly-mug")  # 不许抛异常
            return checker

    def test_top_level_array(self):
        checker = self._run([])
        self.assertGreater(checker.errors, 0)

    def test_string_stats(self):
        checker = self._run({
            "object_count": "3",
            "total_tris": "abc",
            "dimensions": ["1", None, True],
            "renders": [{"path": 5, "std": "x", "black_ratio": None}],
            "exports": {"blend": "not-a-dict", "glb": {"path": "C:/abs/model.glb"}},
        })
        self.assertGreater(checker.errors, 0)

    def test_bool_is_not_number(self):
        self.assertIsNone(ci_check._as_float(True))
        self.assertIsNone(ci_check._as_int(False))
        self.assertEqual(ci_check._as_int(3), 3)
        self.assertEqual(ci_check._as_float(2.5), 2.5)


class PathPatterns(unittest.TestCase):
    def test_abs_path_regex_both_slashes(self):
        self.assertIsNotNone(ci_check.ABS_PATH_RE.search("C:/Users/x/model.py"))
        self.assertIsNotNone(ci_check.ABS_PATH_RE.search("D:\\data\\model.py"))
        self.assertIsNone(ci_check.ABS_PATH_RE.search("renders/view-front.png"))
        self.assertIsNone(ci_check.ABS_PATH_RE.search("BLENDER_KIT_DIR"))

    def test_is_relative(self):
        checker = ci_check.Checker(SKILL_DIR)
        self.assertTrue(checker._is_relative("renders/a.png"))
        self.assertFalse(checker._is_relative("C:/x/a.png"))
        self.assertFalse(checker._is_relative("C:\\x\\a.png"))
        self.assertFalse(checker._is_relative("/abs/a.png"))
        self.assertFalse(checker._is_relative("\\\\server\\share\\a.png"))
        self.assertFalse(checker._is_relative(""))


class GlbAssetChecks(unittest.TestCase):
    def test_floor_names_rejected(self):
        names = ["Floor", "Mug.001", "mug_ceramic"]
        materials = ["FloorMat", "mug_ceramic"]
        bad = [
            n for n in names + materials
            if n in ci_check.FORBIDDEN_GLB_MATERIALS
            or n.endswith(ci_check.BAD_SUFFIX)
            or any(n.startswith(p) for p in ci_check.FORBIDDEN_GLB_NAME_PREFIXES)
        ]
        self.assertEqual(bad, ["Floor", "Mug.001", "FloorMat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
