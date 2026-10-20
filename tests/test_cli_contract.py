# -*- coding: utf-8 -*-
"""CLI 契约测试：只依赖 Python 标准库，不需要 Blender / Pillow。

这些用例就是「外部调用方看到的接口」：命令能跑、退出码对、报错可读。
在仓库根目录运行：

    python -m unittest discover -s tests -v

GitHub Actions 的 ci.yml 也会跑这一套。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
PY = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def run(*args):
    """用当前 Python 跑一个技能脚本，返回 CompletedProcess（文本已按 UTF-8 解码）。"""
    return subprocess.run(
        [PY] + list(args),
        cwd=SKILL_DIR,
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


class CheckOutputCLI(unittest.TestCase):
    """交付闸门 check_output.py 的命令行契约。"""

    def test_selftest_passes(self):
        r = run(os.path.join(SCRIPTS, "check_output.py"), "--selftest")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SELFTEST OK", r.stdout)

    def test_missing_out_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(os.path.join(SCRIPTS, "check_output.py"),
                    "--out", os.path.join(tmp, "does-not-exist"))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("不存在", r.stdout)

    def test_empty_out_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(os.path.join(SCRIPTS, "check_output.py"), "--out", tmp)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("ERROR", r.stdout)

    def test_min_views_zero_rejected(self):
        """--min-views 0 会让「0 张渲染图」也通过，必须拒绝。"""
        with tempfile.TemporaryDirectory() as tmp:
            r = run(os.path.join(SCRIPTS, "check_output.py"), "--out", tmp, "--min-views", "0")
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("min-views", (r.stdout + r.stderr).lower())

    def test_json_output_is_pure_json(self):
        """--json 的 stdout 必须是一个可解析的 JSON 对象（不能混人读日志）。"""
        with tempfile.TemporaryDirectory() as tmp:
            r = run(os.path.join(SCRIPTS, "check_output.py"),
                    "--out", os.path.join(tmp, "nope"), "--json")
            self.assertEqual(r.returncode, 1, r.stdout)
            payload = json.loads(r.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("counts", payload)
            self.assertIsInstance(payload["items"], list)

    def test_help(self):
        r = run(os.path.join(SCRIPTS, "check_output.py"), "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage", r.stdout.lower())


class CiCheckCLI(unittest.TestCase):
    """仓库自检 ci_check.py：当前仓库必须是 0 ERROR。"""

    def test_repo_is_clean(self):
        r = run(os.path.join(SCRIPTS, "ci_check.py"))
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr[-2000:])
        self.assertIn("0 ERROR", r.stdout)


class RunBlenderCLI(unittest.TestCase):
    """执行层 run_blender.py 的参数校验。"""

    def test_missing_script_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(os.path.join(SCRIPTS, "run_blender.py"),
                    "--script", os.path.join(tmp, "nope.py"),
                    "--out", tmp)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("找不到", r.stdout + r.stderr)

    def test_non_positive_timeout_rejected(self):
        """--timeout 0/负数/nan 必须按参数错误拒绝（退出码 2），不能伪装成 TIMEOUT。"""
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "model.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write("print('noop')\n")
            for bad in ("0", "-5", "nan"):
                with self.subTest(timeout=bad):
                    r = run(os.path.join(SCRIPTS, "run_blender.py"),
                            "--script", script, "--out", tmp, "--timeout", bad)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("--timeout", r.stderr)
                    self.assertNotIn("TIMEOUT:", r.stdout)

    def test_help(self):
        r = run(os.path.join(SCRIPTS, "run_blender.py"), "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage", r.stdout.lower())


class DoctorCLI(unittest.TestCase):
    """doctor.py 的 --json 契约与目录检查。"""

    def test_json_output_is_pure_json(self):
        """--json 的 stdout 必须可解析为 JSON（修前是死标志，打的仍是人类文本）。"""
        r = run(os.path.join(SCRIPTS, "doctor.py"), "--json")
        payload = json.loads(r.stdout)  # 混入任何人类文本都会抛 ValueError
        self.assertIsInstance(payload, dict)
        self.assertIn("counts", payload)
        self.assertIn("items", payload)
        self.assertIsInstance(payload["ok"], bool)
        # 环境缺 Blender 的 CI 机器也可能 ok=False，这里只断言结构，退出码与 ok 一致
        self.assertEqual(r.returncode, 0 if payload["ok"] else 1)

    def test_layout_detects_missing_edit_template(self):
        """模式 B 必须的 templates/edit_model_template.py 缺失时 doctor 要报 FAIL。"""
        sys.path.insert(0, SCRIPTS)
        import bl_common
        import doctor
        old_template_dir = bl_common.TEMPLATE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            template_dir = os.path.join(tmp, "templates")
            os.makedirs(template_dir)
            with open(os.path.join(template_dir, "model_template.py"), "w", encoding="utf-8") as fh:
                fh.write("# placeholder\n")
            bl_common.TEMPLATE_DIR = template_dir
            doctor.RESULTS[:] = []
            try:
                doctor.check_layout()
            finally:
                bl_common.TEMPLATE_DIR = old_template_dir
            fails = [msg for level, msg in doctor.RESULTS if level == "FAIL"]
            self.assertTrue(any("edit_model_template.py" in msg for msg in fails),
                            "缺少 edit_model_template 未被检出: %r" % (fails,))


class OtherScriptsCLI(unittest.TestCase):
    """其余脚本至少要能 import / 打印帮助（不调用 Blender 的部分）。"""

    def test_help_flags(self):
        for name in ("doctor.py", "contact_sheet.py"):
            with self.subTest(script=name):
                r = run(os.path.join(SCRIPTS, name), "--help")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("usage", r.stdout.lower())

    def test_modules_import_without_blender(self):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import bl_common, check_output, ci_check\n"
            "print('IMPORT OK')" % SCRIPTS
        )
        r = subprocess.run([PY, "-c", code], env=ENV, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("IMPORT OK", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
