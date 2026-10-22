# -*- coding: utf-8 -*-
"""doctor.py --vision / --json 的回归测试。

覆盖 R9 两个 bug：
- B10：Blender 版本非 4.0（WARN 分支）时，--json 的 stdout 被一行人类日志污染，
  json.loads 直接失败；
- B11：smoke 失败时「冒烟目录保留用于排查」同样未受 QUIET 保护，--json --smoke
  的 stdout 会被人类日志污染；
- 新增 --vision：纯标准库证明渲染图真的可解码、尺寸符合 report 声明且非空白，
  坏图必须 exit 1（对应 Amagine3D 的 doctor --vision 机制）。

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import doctor  # noqa: E402
import vision_probe as vp  # noqa: E402


def run_doctor(args, cwd=SKILL_DIR):
    return subprocess.run(
        [sys.executable, os.path.join(SKILL_DIR, "scripts", "doctor.py")] + args,
        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")


class DoctorVisionCliTest(unittest.TestCase):
    def test_vision_json_on_examples(self):
        proc = run_doctor(["--vision", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)  # 纯 JSON：B10 回归哨兵
        self.assertTrue(payload["ok"])
        self.assertIsNotNone(payload["vision"])
        self.assertTrue(payload["vision"]["ok"])
        self.assertGreaterEqual(len(payload["vision"]["targets"]), 2)
        for target in payload["vision"]["targets"]:
            self.assertGreaterEqual(target["files"], 3)

    def test_vision_flags_bad_render_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            with open(os.path.join(renders, "view-front.png"), "wb") as handle:
                handle.write(vp._encode_rgb_png(96, 96, vp._solid_pixels(96, 96)))
            proc = run_doctor(["--vision", "--vision-dir", renders, "--json"])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["vision"]["ok"])
        self.assertGreaterEqual(payload["counts"]["error"], 1)
        messages = " ".join(item["message"] for item in payload["items"])
        self.assertIn("空白", messages)

    def test_vision_missing_target_fails(self):
        missing = os.path.join(tempfile.gettempdir(), "no-such-out-r9")
        proc = run_doctor(["--vision", "--vision-out", missing, "--json"])
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["vision"]["ok"])


class JsonPurityTest(unittest.TestCase):
    def test_json_output_is_pure_with_non_40_blender(self):
        """B10：4.2 的 WARN 分支不能再往 stdout 打人类日志。"""
        fake_exe = r"C:\fake\blender.exe"
        fake_version = {"ok": True, "version": "4.2.0", "tuple": (4, 2, 0)}
        capture = io.StringIO()
        doctor.RESULTS = []
        doctor.QUIET = False
        try:
            with mock.patch.object(doctor.bl_common, "find_blender",
                                   return_value=fake_exe), \
                    mock.patch.object(doctor.bl_common, "blender_version",
                                      return_value=fake_version), \
                    contextlib.redirect_stdout(capture):
                code = doctor.main(["--json"])
        finally:
            doctor.RESULTS = []
            doctor.QUIET = False
        payload = json.loads(capture.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(any("非实测目标" in item["message"]
                            for item in payload["items"]))
        self.assertTrue(capture.getvalue().lstrip().startswith("{"))


class SmokeJsonPurityTest(unittest.TestCase):
    """B11 回归：--smoke 失败时「冒烟目录保留」不能污染 --json 的 stdout。"""

    @staticmethod
    def _fake_execute(ok):
        return {
            "ok": ok,
            "renders": [{"path": "renders/view-front.png"}] if ok else [],
            "exports": ([{"path": os.path.join("exports", "smoke.glb")},
                         {"path": os.path.join("exports", "smoke.blend")}]
                        if ok else []),
            "errors": [] if ok else ["fake render failure"],
            "duration_s": 1.0,
        }

    def _run_smoke(self, ok):
        tmp_root = tempfile.mkdtemp(prefix="bm-doctor-smoke-test-")
        self.addCleanup(shutil.rmtree, tmp_root, True)
        os.makedirs(os.path.join(tmp_root, "out"))
        doctor.RESULTS = []
        doctor.QUIET = True
        capture = io.StringIO()
        try:
            with mock.patch.object(doctor.tempfile, "mkdtemp",
                                   return_value=tmp_root), \
                    mock.patch.object(doctor.bl_common, "execute",
                                      return_value=self._fake_execute(ok)), \
                    contextlib.redirect_stdout(capture):
                doctor.check_smoke(r"C:\fake\blender.exe")
        finally:
            results = list(doctor.RESULTS)
            doctor.RESULTS = []
            doctor.QUIET = False
        return capture.getvalue(), results

    def test_failed_smoke_does_not_pollute_json_stdout(self):
        stdout, results = self._run_smoke(False)
        self.assertEqual(stdout, "")
        self.assertTrue(any(level == "FAIL" for level, _ in results))

    def test_successful_smoke_prints_nothing_in_quiet_mode(self):
        stdout, results = self._run_smoke(True)
        self.assertEqual(stdout, "")
        self.assertTrue(any(level == "PASS" for level, _ in results))


if __name__ == "__main__":
    unittest.main()
