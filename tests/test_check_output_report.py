# -*- coding: utf-8 -*-
"""check_output.py 补充回归：report.json 的 exports.*.bytes 与实际文件大小不一致。

按 AGENTS 口径：旧版 report 的 bytes 可能陈旧，只 WARN 不阻断交付；只有非数字才静默
放过（老 report 可能没有该字段）。这是 r7 审计中 r7-bl-kit 转来的补充检查项。
"""

import json
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import check_output  # noqa: E402

BLEND_PAYLOAD = check_output.BLEND_MAGIC + b"\x00" * 2048
GLB_PAYLOAD = check_output.GLB_MAGIC + b"\x00" * 1024


def _make_out(tmp, export_records):
    base = os.path.join(tmp, "out")
    os.makedirs(os.path.join(base, "renders"))
    os.makedirs(os.path.join(base, "exports"))
    with open(os.path.join(base, "model.py"), "w", encoding="utf-8") as fh:
        fh.write('import os, sys\nsys.path.insert(0, os.environ["BLENDER_KIT_DIR"])\n'
                 "import blender_kit\n")
    with open(os.path.join(base, "brief.md"), "w", encoding="utf-8") as fh:
        fh.write("# brief\n")
    render_path = os.path.join(base, "renders", "view-front.png")
    png = check_output._make_valid_png(128, 128)
    with open(render_path, "wb") as fh:
        fh.write(png)
    stats = check_output._recompute_render_stats(render_path)
    if stats is None:  # 无 Pillow：统计重算静默降级，用旧口径占位
        stats = {"mean": 0.0, "std": 20.0, "black_ratio": 0.1}
    with open(os.path.join(base, "exports", "model.blend"), "wb") as fh:
        fh.write(BLEND_PAYLOAD)
    with open(os.path.join(base, "exports", "model.glb"), "wb") as fh:
        fh.write(GLB_PAYLOAD)
    report = {
        "object_count": 1,
        "mesh_count": 1,
        "total_tris": 12,
        "camera_count": 1,
        "light_count": 3,
        "dimensions": [1.0, 1.0, 1.0],
        "exports": export_records,
        "renders": [{
            "path": "renders/view-front.png",
            "mean": stats["mean"],
            "std": stats["std"],
            "black_ratio": stats["black_ratio"],
            "width": 128,
            "height": 128,
            "bytes": len(png),
        }],
    }
    with open(os.path.join(base, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh)
    return base


def _records(blend_bytes, glb_bytes):
    return {
        "blend": {"path": "exports/model.blend", "bytes": blend_bytes},
        "glb": {"path": "exports/model.glb", "bytes": glb_bytes},
    }


class ReportBytesConsistencyTests(unittest.TestCase):
    def _run(self, records):
        # 这里的 PNG 只有头部（Pillow 无法解码），B1 之后视觉闸门会对「全部无法解码」
        # 判 ERROR；本文件只测 report 的 bytes 一致性，所以显式关掉视觉（vision=False）。
        # 视觉闸门本身由 tests/test_check_output_vision.py 用真实 PNG 覆盖。
        with tempfile.TemporaryDirectory(prefix="bm-check-bytes-") as tmp:
            return check_output.run_checks(_make_out(tmp, records), min_views=1, vision=False)

    def test_matching_bytes_pass_without_warn(self):
        result = self._run(_records(len(BLEND_PAYLOAD), len(GLB_PAYLOAD)))
        self.assertFalse(result.failed, [m for lv, m in result.items if lv == "ERROR"])
        self.assertEqual([m for lv, m in result.items if lv == "WARN"], [])

    def test_stale_bytes_warn_only(self):
        result = self._run(_records(123, 456))
        self.assertFalse(result.failed, "陈旧 bytes 不应阻断交付")
        warnings = [m for lv, m in result.items if lv == "WARN"]
        self.assertEqual(len(warnings), 2, warnings)
        self.assertTrue(all("bytes" in m for m in warnings), warnings)

    def test_missing_bytes_tolerated_string_bytes_rejected(self):
        # 缺 bytes 字段：容忍（旧产物兼容）；但「字符串冒充数字」必须 ERROR ——
        # R9-B2 之后闸门不允许非有限/非数值的 bytes 静默通过。
        missing = self._run({
            "blend": {"path": "exports/model.blend"},
            "glb": {"path": "exports/model.glb"},
        })
        self.assertFalse(missing.failed)
        self.assertEqual([m for lv, m in missing.items if lv == "WARN"], [])

        string_bytes = self._run({
            "blend": {"path": "exports/model.blend"},
            "glb": {"path": "exports/model.glb", "bytes": "456"},
        })
        self.assertTrue(string_bytes.failed)
        errors = [m for lv, m in string_bytes.items if lv == "ERROR"]
        self.assertTrue(any("有限数字" in message for message in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
