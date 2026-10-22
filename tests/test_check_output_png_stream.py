# -*- coding: utf-8 -*-
"""check_output.py 零依赖 PNG 像素流校验回归（R9 复核 B3）。

背景：check_output 在 Pillow 缺失时（如 py3.9 环境）曾只做 PNG 块结构/CRC 校验，
一份「块结构完全合法、CRC 正确、尺寸与体积都达标、但 IDAT 根本不是 zlib 流」的
伪造渲染图会被放行，而同产物在装了 Pillow 的环境被视觉闸门判 ERROR —— 同一坏产物
在不同平台结论矛盾。现在 vision_probe.pixel_stream_issues 提供零依赖像素流校验
（解压长度 / 流完整性 / 尾部多余字节），本文件锁定该行为。

在本机 py3.12（有 Pillow）与 py3.9（无 Pillow）都应通过。运行：

    python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import check_output  # noqa: E402
import vision_probe  # noqa: E402


def _write(path, payload):
    # 明确用二进制写：坏 PNG 不能被文本模式改写
    with open(path, "wb") as handle:
        handle.write(payload)


def _make_out(tmp, render_bytes):
    base = os.path.join(tmp, "out")
    renders = os.path.join(base, "renders")
    exports = os.path.join(base, "exports")
    os.makedirs(renders)
    os.makedirs(exports)
    with open(os.path.join(base, "model.py"), "w", encoding="utf-8") as handle:
        handle.write("import os, sys\n"
                     "sys.path.insert(0, os.environ['BLENDER_KIT_DIR'])\n"
                     "import blender_kit  # noqa: F401\n")
    with open(os.path.join(base, "brief.md"), "w", encoding="utf-8") as handle:
        handle.write("# brief\n")
    render_path = os.path.join(renders, "view-front.png")
    _write(render_path, render_bytes)
    stats = check_output._recompute_render_stats(render_path) or {
        "mean": 0.0, "std": 20.0, "black_ratio": 0.1}
    blend = check_output.BLEND_MAGIC + b"\x00" * 2048
    glb = check_output.GLB_MAGIC + b"\x00" * 1024
    _write(os.path.join(exports, "model.blend"), blend)
    _write(os.path.join(exports, "model.glb"), glb)
    report = {
        "object_count": 1,
        "mesh_count": 1,
        "total_tris": 12,
        "camera_count": 1,
        "light_count": 3,
        "dimensions": [1.0, 1.0, 1.0],
        "exports": {
            "blend": {"path": "exports/model.blend", "bytes": len(blend)},
            "glb": {"path": "exports/model.glb", "bytes": len(glb)},
        },
        "renders": [{
            "path": "renders/view-front.png",
            "mean": stats["mean"],
            "std": stats["std"],
            "black_ratio": stats["black_ratio"],
            "width": 128,
            "height": 128,
            "bytes": len(render_bytes),
        }],
    }
    with open(os.path.join(base, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    return base


class PngStreamHelpersTest(unittest.TestCase):
    def test_valid_png_passes_zero_dependency_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "valid.png")
            data = check_output._make_valid_png(96, 96)
            _write(path, data)
            self.assertGreater(len(data), 15 * 1024, "自测 PNG 必须撑过 15KB 体积闸门")
            self.assertEqual(check_output._png_structure_problems(path), [])
            self.assertEqual(vision_probe.structure_issues(data), [])

    def test_forged_idat_caught_without_pillow(self):
        data = check_output._png_forged_idat(128, 128)
        # 纯结构校验（块长度/CRC/IHDR/IDAT/IEND）必须全部通过 —— 这正是旧的绕过面
        self.assertEqual(vision_probe.structure_issues(data), [],
                         "伪造样本必须是结构合法的，否则测不到像素流校验")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "forged.png")
            _write(path, data)
            problems = check_output._png_structure_problems(path)
        self.assertTrue(problems, "伪造 IDAT 必须被零依赖校验拦下")
        self.assertTrue(any("无法解压" in problem for problem in problems), problems)

    def test_bad_filter_passes_structure_but_is_undecodable(self):
        # 行过滤类型非法：结构/长度校验发现不了，只有 Pillow 解码能判死。
        # 这里锁定「零依赖校验不能误报」的边界，视觉闸门用例负责判死。
        data = check_output._png_bad_filter(128, 128)
        self.assertEqual(vision_probe.structure_issues(data), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad-filter.png")
            _write(path, data)
            self.assertEqual(check_output._png_structure_problems(path), [])
        self.assertTrue(vision_probe.pixel_stream_issues(data) == [],
                        "像素流长度合法时像素流校验应放行（坏 filter 由 Pillow 判死）")


class ForgedRenderGateTest(unittest.TestCase):
    def test_forged_render_fails_full_gate_without_pillow(self):
        # 关闭视觉闸门（vision=False）也能拦住：证明不依赖 Pillow 的像素流校验
        # 已经在 check_renders 里生效。
        with tempfile.TemporaryDirectory() as tmp:
            forged = check_output._png_forged_idat(128, 128)
            out = _make_out(tmp, forged)
            result = check_output.run_checks(out, min_views=1, vision=False)
        errors = [message for level, message in result.items if level == "ERROR"]
        self.assertTrue(result.failed, errors)
        self.assertTrue(any("PNG 结构损坏" in message for message in errors), errors)
        self.assertTrue(any("无法解压" in message for message in errors), errors)

    def test_valid_render_passes_full_gate_without_pillow(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_out(tmp, check_output._make_valid_png(128, 128))
            result = check_output.run_checks(out, min_views=1, vision=False)
        errors = [message for level, message in result.items if level == "ERROR"]
        self.assertFalse(result.failed, errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
