# -*- coding: utf-8 -*-
"""bl_common 单元测试：日志分类、Blender 探测等纯函数（不需要 Blender）。

运行（仓库根目录）：

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import bl_common  # noqa: E402


def _pillow_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


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


class SafeLabelTests(unittest.TestCase):
    """--label 会被拼进日志文件名，必须挡住 Windows 保留名（含带扩展名写法）。"""

    def test_reserved_names_get_prefix(self):
        for name in ("CON", "con", "NUL", "COM1", "CON.txt", "NUL.log", "COM1.dat"):
            with self.subTest(label=name):
                cleaned = bl_common._safe_label(name)
                self.assertTrue(cleaned.lower().startswith("run_"), (name, cleaned))

    def test_normal_label_is_cleaned_not_prefixed(self):
        self.assertEqual(bl_common._safe_label("view front"), "view_front")
        self.assertEqual(bl_common._safe_label("final"), "final")

    def test_empty_label_falls_back(self):
        self.assertEqual(bl_common._safe_label(""), "run")


class FindBlenderTests(unittest.TestCase):
    def test_result_is_none_or_existing_file(self):
        exe = bl_common.find_blender()
        if exe is None:
            self.skipTest("本机没有 Blender（CI 环境正常）")
        self.assertTrue(os.path.isfile(exe), exe)

    def test_explicit_missing_path_returns_none(self):
        self.assertIsNone(bl_common.find_blender("Z:\\definitely\\not\\blender.exe"))


class ExecuteWarningsTests(unittest.TestCase):
    """execute() 里执行前记录的警告不能被最终 result.update 覆盖丢掉。"""

    def test_label_clean_warning_is_preserved(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=b"Blender 4.0.2\n")
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "model.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write("print('noop')\n")
            out_dir = os.path.join(tmp, "out")
            with mock.patch.object(
                    bl_common, "blender_version",
                    return_value={"ok": True, "version": "4.0.2", "tuple": (4, 0, 2)}
            ), mock.patch.object(bl_common.subprocess, "run", return_value=fake):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bl_common.execute(
                        script, out_dir, stage="build", timeout=5,
                        label="bad label/../x", blender=sys.executable, quiet=True)
            self.assertTrue(result["ok"], result["errors"])
            self.assertTrue(any("label" in w for w in result["warnings"]),
                            result["warnings"])
            log_name = os.path.basename(result["log"])
            self.assertNotIn(" ", log_name)
            self.assertNotIn("/", log_name)
            self.assertNotIn("\\", log_name)


class ExecuteTempIsolationTests(unittest.TestCase):
    """execute() 必须给 Blender 子进程隔离 TMP/TEMP/TMPDIR。

    背景：Blender 4.0.2 在 session 临时子目录创建失败时会把 session 目录退化成
    基目录并在退出时递归清空它（上游 #139585 / commit 87c4f47）。若不隔离，
    基目录可能就是系统 %TEMP%，会被直接清空。
    """

    def _make_script(self, tmp):
        script = os.path.join(tmp, "model.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("print('noop')\n")
        return script

    def _patched_version(self):
        return mock.patch.object(
            bl_common, "blender_version",
            return_value={"ok": True, "version": "4.0.2", "tuple": (4, 0, 2)})

    def test_child_env_isolates_temp_dir_and_cleans_up(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            env = kwargs.get("env") or {}
            captured["env"] = dict(env)
            captured["temp_dir"] = env.get("TEMP")
            captured["exists_during_run"] = os.path.isdir(env.get("TEMP") or "")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"Blender 4.0.2\n")

        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)
            out_dir = os.path.join(tmp, "out")
            with self._patched_version(), mock.patch.object(
                    bl_common.subprocess, "run", side_effect=fake_run):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bl_common.execute(
                        script, out_dir, stage="build", timeout=5,
                        label="temp iso", blender=sys.executable, quiet=True)

        self.assertTrue(result["ok"], result["errors"])
        env = captured["env"]
        self.assertTrue(captured["exists_during_run"],
                        "隔离临时目录在运行期间必须存在: %r" % (captured,))
        self.assertEqual(env.get("TMP"), captured["temp_dir"])
        self.assertEqual(env.get("TMPDIR"), captured["temp_dir"])
        self.assertNotEqual(env.get("TEMP"), os.environ.get("TEMP"),
                            "子进程 TEMP 不能等于宿主 TEMP")
        self.assertEqual(os.path.dirname(captured["temp_dir"]),
                         os.path.join(out_dir, "logs"))
        self.assertFalse(os.path.exists(captured["temp_dir"]),
                         "隔离临时目录应在执行结束后清理")

    def test_mkdtemp_failure_degrades_with_warning(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=b"Blender 4.0.2\n")
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)
            with self._patched_version(), mock.patch.object(
                    bl_common.tempfile, "mkdtemp", side_effect=OSError("boom")), \
                    mock.patch.object(bl_common.subprocess, "run", return_value=fake):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bl_common.execute(
                        script, os.path.join(tmp, "out"), stage="build",
                        timeout=5, blender=sys.executable, quiet=True)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(any("临时目录" in w for w in result["warnings"]),
                        result["warnings"])


class VisionAttachTests(unittest.TestCase):
    """B4：vision 指标回写链路的单元测试（失败不能静默吞掉）。"""

    def _make_out(self, tmp, with_png=False):
        out = os.path.join(tmp, "out")
        os.makedirs(os.path.join(out, "renders"))
        os.makedirs(os.path.join(out, "exports"))
        with open(os.path.join(out, "model.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport blender_kit  # noqa\n")
        with open(os.path.join(out, "brief.md"), "w", encoding="utf-8") as fh:
            fh.write("# brief\n")
        report = {
            "object_count": 1, "mesh_count": 1, "camera_count": 1,
            "light_count": 1, "total_tris": 12, "dimensions": [1.0, 1.0, 1.0],
            "renders": [], "exports": {},
        }
        if with_png:
            from PIL import Image  # 延迟导入，只有 skipUnless 通过的用例才会走到
            image = Image.new("RGB", (512, 512), (128, 128, 128))
            for x in range(180, 330):
                for y in range(150, 400):
                    image.putpixel((x, y), (240, 240, 240))
            image.save(os.path.join(out, "renders", "view-front.png"))
            report["renders"] = [{"path": "renders/view-front.png"}]
        with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh)
        return out

    def _load_report(self, out):
        with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_without_vision_module_warns_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._make_out(tmp)
            warnings = []
            with mock.patch.object(bl_common, "_load_vision_metrics",
                                   return_value=None):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bl_common._attach_vision_metrics(
                        out, warnings, quiet=True)
            self.assertFalse(result["attached"])
            self.assertTrue(any("视觉指标" in w for w in warnings), warnings)
            self.assertNotIn("vision", self._load_report(out))

    def test_without_pillow_warns_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._make_out(tmp)
            warnings = []
            module = bl_common._load_vision_metrics()
            self.assertIsNotNone(module)
            with mock.patch.object(module, "pillow_available", return_value=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bl_common._attach_vision_metrics(
                        out, warnings, quiet=True)
            self.assertFalse(result["attached"])
            self.assertTrue(any("视觉指标" in w for w in warnings), warnings)
            self.assertNotIn("vision", self._load_report(out))

    @unittest.skipUnless(_pillow_available(), "需要 Pillow 生成真实 PNG")
    def test_attach_writes_vision_into_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._make_out(tmp, with_png=True)
            warnings = []
            with contextlib.redirect_stdout(io.StringIO()):
                result = bl_common._attach_vision_metrics(out, warnings, quiet=True)
            self.assertTrue(result["attached"], result)
            self.assertEqual(result["views"], 1)
            self.assertEqual(warnings, [])
            report = self._load_report(out)
            self.assertIsInstance(report.get("vision"), dict)
            self.assertNotIn("backfill", report["vision"],
                             "新产物自动回写不应标记 backfill")


class ExecuteVisionTests(unittest.TestCase):
    """B4：execute() 的 vision 分支：仅在 full 成功后调用一次。"""

    def _fake_run(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=b"Blender 4.0.2\n")
        version = {"ok": True, "version": "4.0.2", "tuple": (4, 0, 2)}
        return mock.patch.object(bl_common, "blender_version", return_value=version), \
            mock.patch.object(bl_common.subprocess, "run", return_value=fake)

    def _prepare_full_artifacts(self, out_dir):
        """full 阶段闸门要求真的有 renders/ 与 exports/ 产物。"""
        os.makedirs(os.path.join(out_dir, "renders"), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "exports"), exist_ok=True)
        with open(os.path.join(out_dir, "renders", "view-front.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        with open(os.path.join(out_dir, "exports", "model.glb"), "wb") as fh:
            fh.write(b"glTF" + b"\x00" * 32)

    def test_full_success_attaches_vision(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "model.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write("print('noop')\n")
            out_dir = os.path.join(tmp, "out")
            self._prepare_full_artifacts(out_dir)
            version_patch, run_patch = self._fake_run()
            with version_patch, run_patch, mock.patch.object(
                    bl_common, "_attach_vision_metrics",
                    return_value={"attached": True, "views": 3}) as attach:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bl_common.execute(
                        script, out_dir, stage="full",
                        timeout=5, blender=sys.executable, quiet=True, vision=True)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["vision"], {"attached": True, "views": 3})
            attach.assert_called_once()

    def test_build_stage_and_disabled_do_not_attach(self):
        for stage, vision in (("build", True), ("full", False)):
            with tempfile.TemporaryDirectory() as tmp:
                script = os.path.join(tmp, "model.py")
                with open(script, "w", encoding="utf-8") as fh:
                    fh.write("print('noop')\n")
                out_dir = os.path.join(tmp, "out")
                if stage == "full":
                    self._prepare_full_artifacts(out_dir)
                version_patch, run_patch = self._fake_run()
                with version_patch, run_patch, mock.patch.object(
                        bl_common, "_attach_vision_metrics") as attach:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = bl_common.execute(
                            script, out_dir, stage=stage,
                            timeout=5, blender=sys.executable, quiet=True,
                            vision=vision)
                self.assertTrue(result["ok"], result["errors"])
                self.assertIsNone(result["vision"])
                attach.assert_not_called()


class RunBlenderVisionFlagTests(unittest.TestCase):
    """B4：run_blender.py --no-vision 必须把 vision=False 透传下去。"""

    def test_default_passes_vision_true_and_flag_disables(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import run_blender
        captured = []

        def fake_execute(**kwargs):
            captured.append(kwargs)
            return {"ok": True}

        with mock.patch.object(run_blender.bl_common, "execute",
                               side_effect=fake_execute):
            self.assertEqual(run_blender.main(
                ["--script", "model.py", "--out", "out"]), 0)
            self.assertEqual(run_blender.main(
                ["--script", "model.py", "--out", "out", "--no-vision"]), 0)
        self.assertTrue(captured[0]["vision"])
        self.assertFalse(captured[1]["vision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
