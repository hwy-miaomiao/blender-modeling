# -*- coding: utf-8 -*-
"""gate_bench.py 的单元测试：变异清单完整性 / 错误码分类 / 自测基准。

gate_bench 的 selftest 会在临时目录造一份合成合格产物，跑 17 个确定性变异并
断言全部被闸门拦截、且「无闸门变异」不会被误判为拦截（防止假绿）。
不依赖 Blender；Pillow 缺失时视觉闸门按 SKIP 处理，selftest 会自动放宽。

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import os
import sys
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import gate_bench  # noqa: E402


class MutationListTest(unittest.TestCase):
    def test_mutation_count_and_unique_ids(self):
        ids = [mutation["id"] for mutation in gate_bench.MUTATIONS]
        self.assertEqual(len(ids), 17, ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_mutation_has_apply_and_expectation(self):
        for mutation in gate_bench.MUTATIONS:
            self.assertEqual(set(mutation), {"id", "title", "apply", "expected"},
                             mutation)
            self.assertTrue(mutation["id"].startswith("M"), mutation["id"])
            self.assertTrue(mutation["title"], mutation["id"])
            self.assertTrue(callable(mutation["apply"]), mutation["id"])
            self.assertTrue(mutation["expected"], mutation["id"])


class ClassifyTest(unittest.TestCase):
    def test_maps_known_messages(self):
        cases = {
            "渲染图数量不足: 2 张 < 3 张": "CHECK_RENDERS",
            "渲染图 PNG 结构损坏（截断/伪造/CRC 失败）: view-front.png": "CHECK_RENDERS",
            "report.scene.dimensions 与 bbox_min/bbox_max 不一致（疑似尺寸被改）":
                "CHECK_REPORT_SCENE",
            "report.renders 记录的 width=1024 与实际 PNG 512x512 不符": "CHECK_REPORT_RENDERS",
            "report.renders 存在重复记录（同一文件被重复统计）": "CHECK_REPORT_RENDERS",
            "report 记录的 glb bytes 不是有限数字（NaN/inf/非数值）": "CHECK_REPORT_EXPORTS",
            "缺少导出文件: exports/model.glb": "CHECK_EXPORTS",
            "视觉闸门: [VISION009] - 部分渲染图无法解码": "VISION009",
            "视觉闸门: [VISION003] view-front.png 四周留白不足": "VISION003",
        }
        for message, expected in cases.items():
            self.assertEqual(gate_bench.classify_message(message), expected, message)

    def test_unknown_message_falls_back(self):
        self.assertEqual(gate_bench.classify_message("某种未归类的新错误"),
                         gate_bench.CODE_OTHER)


class SelftestTest(unittest.TestCase):
    def test_selftest_passes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate_bench.selftest(), 0)


if __name__ == "__main__":
    unittest.main()
