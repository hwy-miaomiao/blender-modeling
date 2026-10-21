# -*- coding: utf-8 -*-
"""safe_check.py 的单元测试：SAFE_MODE 静态审查的正例与各类危险构造。

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

import safe_check  # noqa: E402


def audit(source):
    return safe_check.audit_source(source, "model.py")


def codes_of(source):
    return [item["code"] for item in audit(source)]


class DenyRulesTest(unittest.TestCase):
    def test_clean_model_has_no_issues(self):
        source = (
            "import os\n"
            "import sys\n"
            "sys.path.insert(0, os.environ['BLENDER_KIT_DIR'])\n"
            "import blender_kit\n"
            "PARAMS = {'size': 1.0}\n"
            "print('build')\n"
        )
        self.assertEqual(safe_check.summarize(audit(source)), (0, 0))

    def test_denied_imports(self):
        for statement in (
            "import subprocess",
            "import socket",
            "import ctypes",
            "import importlib",
            "import requests",
            "from subprocess import run",
            "from urllib import request",
        ):
            with self.subTest(statement=statement):
                self.assertIn("SAFE001", codes_of(statement))

    def test_dangerous_calls(self):
        for statement in (
            "eval('1')",
            "exec('x = 1')",
            "compile('x', 'f', 'exec')",
            "__import__('os')",
            "import os\nos.system('echo hi')",
            "import os\nos.popen('echo hi')",
        ):
            with self.subTest(statement=statement):
                self.assertIn("SAFE002", codes_of(statement))

    def test_dynamic_attribute_escape(self):
        self.assertIn("SAFE002", codes_of("import os\ngetattr(os, 'system')\n"))

    def test_file_extension_attribute_denied(self):
        self.assertIn("SAFE009", codes_of("f = open\ng = f.__globals__\n"))


class WritePathRulesTest(unittest.TestCase):
    def test_absolute_write_path_is_error(self):
        self.assertIn("SAFE003", codes_of("open('C:/tmp/x.txt', 'w')\n"))

    def test_parent_escape_is_error(self):
        self.assertIn("SAFE004", codes_of("open('../x.txt', 'w')\n"))

    def test_unknown_relative_path_is_only_warn(self):
        issues = audit("open('secret.txt', 'w')\n")
        self.assertEqual(safe_check.summarize(issues), (0, 1))
        self.assertIn("SAFE005", [item["code"] for item in issues])

    def test_allowed_artifact_paths(self):
        for statement in (
            "open('renders/preview.txt', 'w')\n",
            "open('exports/notes.txt', 'w')\n",
            "open('report.json', 'w')\n",
            "open('model.py', 'r')\n",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(safe_check.summarize(audit(statement)), (0, 0))

    def test_dynamic_write_path_is_error(self):
        # B3：变量路径无法证明安全，必须 ERROR（不能只 WARN）
        issues = audit("name = 'x.txt'\nopen(name, 'w')\n")
        self.assertEqual(safe_check.summarize(issues), (1, 0))
        self.assertIn("SAFE006", [item["code"] for item in issues])

    def test_pathlib_absolute_write_text(self):
        self.assertIn(
            "SAFE003", codes_of("from pathlib import Path\nPath('C:/tmp/x.txt').write_text('a')\n"))


class WritePathHardeningTest(unittest.TestCase):
    """B3：验证员 A1-A8 八类绕过手法的回归测试。"""

    def _codes(self, source):
        return [item["code"] for item in audit(source)]

    def test_a1_variable_absolute_path_is_error(self):
        issues = audit("p = 'C:/evil/x.txt'\nopen(p, 'w')\n")
        self.assertEqual(safe_check.summarize(issues), (1, 0))
        self.assertIn("SAFE006", [item["code"] for item in issues])

    def test_a2_pathlib_open_absolute_is_error(self):
        # Path('C:/evil/x.txt').open('w') 的路径在 receiver，之前完全漏检
        issues = audit("from pathlib import Path\n"
                       "Path('C:/evil/x.txt').open('w').write('x')\n")
        self.assertEqual(safe_check.summarize(issues)[0], 1)
        self.assertIn("SAFE003", [item["code"] for item in issues])

    def test_a3_drive_relative_path_is_error(self):
        self.assertIn("SAFE003", self._codes("open('C:evil.txt', 'w')\n"))

    def test_a4_basename_whitelist_bypass_is_warn(self):
        issues = audit("open('data/report.json', 'w')\n")
        self.assertEqual(safe_check.summarize(issues), (0, 1))
        self.assertIn("SAFE005", [item["code"] for item in issues])

    def test_a5_shutil_copy_is_error(self):
        for statement in (
            "import shutil\nshutil.copyfile('renders/a.png', 'b.png')\n",
            "import shutil\nshutil.copy('renders/a.png', 'b.png')\n",
            "import shutil\nshutil.copytree('renders', 'backup')\n",
        ):
            with self.subTest(statement=statement):
                self.assertIn("SAFE002", self._codes(statement))

    def test_a6_variable_pathlib_write_is_error(self):
        issues = audit("from pathlib import Path\np = 'C:/evil/x.txt'\n"
                       "Path(p).write_text('x')\n")
        self.assertEqual(safe_check.summarize(issues)[0], 1)
        self.assertIn("SAFE006", [item["code"] for item in issues])

    def test_a7_temp_redirect_is_tolerated(self):
        for statement in (
            "import os\nopen(os.path.join(os.environ['TEMP'], 'a.bin'), 'wb')\n",
            "import tempfile, os\n"
            "open(os.path.join(tempfile.gettempdir(), 'a.bin'), 'w')\n",
            "import os\n"
            "open(os.path.join(os.environ.get('BLENDER_OUT_DIR', 'out'), 'a.bin'), 'wb')\n",
            "import os\n"
            "open(os.path.join(os.environ['BLENDER_OUT_DIR'], 'renders', 'a.png'), 'wb')\n",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(safe_check.summarize(audit(statement)), (0, 0))

    def test_a8_readonly_pathlib_open_is_clean(self):
        for statement in (
            "from pathlib import Path\nPath('README.md').open('r').read()\n",
            "from pathlib import Path\nPath('model.py').read_text()\n",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(safe_check.summarize(audit(statement)), (0, 0))

    def test_pathlib_variable_open_mode_is_warn(self):
        codes = self._codes("from pathlib import Path\nm = 'w'\n"
                            "Path('renders/a.txt').open(m)\n")
        self.assertIn("SAFE007", codes)


class AuditApiTest(unittest.TestCase):
    def test_audit_file_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "model.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import subprocess\nsubprocess.run(['ls'])\n")
            issues = safe_check.audit_file(path)
        self.assertTrue(issues)
        self.assertEqual(issues[0]["path"], path)
        self.assertIn("[ERROR]", safe_check.format_issue(issues[0]))

    def test_audit_file_missing_returns_safe008(self):
        missing = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-model.py")
        self.assertIn("SAFE008", [item["code"] for item in safe_check.audit_file(missing)])

    def test_syntax_error_is_safe008(self):
        self.assertIn("SAFE008", codes_of("def broken(:\n"))

    def test_default_targets_covers_repo(self):
        targets = safe_check.default_targets(SKILL_DIR)
        self.assertGreaterEqual(len(targets), 4)
        rels = [os.path.relpath(path, SKILL_DIR).replace(os.sep, "/") for path in targets]
        self.assertIn("templates/model_template.py", rels)
        self.assertIn("examples/lowpoly-mug/model.py", rels)
        for path in targets:
            self.assertTrue(os.path.isfile(path), path)
            self.assertEqual(safe_check.summarize(safe_check.audit_file(path)), (0, 0), path)

    def test_selftest_passes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(safe_check.selftest(), 0)

    def test_json_mode_stdout_is_pure_json(self):
        # B5：--json 时人类可读日志必须走 stderr，stdout 只能有 JSON
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "model.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import os\nprint('ok')\n")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = safe_check.main(["--json", path])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["files"], [path])
        self.assertIn("PASS", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
