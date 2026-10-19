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

    def test_help(self):
        r = run(os.path.join(SCRIPTS, "run_blender.py"), "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage", r.stdout.lower())


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
