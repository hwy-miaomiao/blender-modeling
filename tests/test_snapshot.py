# -*- coding: utf-8 -*-
"""snapshot.py 的单元测试：迭代版本快照 / best 基线 / promote / rollback。

只依赖标准库（snapshot 本身不需要 Blender 与 Pillow）。在仓库根目录运行：

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

import snapshot  # noqa: E402


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = self._tmp.name
        snapshot._write_test_out(self.out)

    def tearDown(self):
        self._tmp.cleanup()

    def version_dir(self, version="v1"):
        return os.path.join(self.out, "history", version)

    # ---- create / best ----
    def test_create_snapshot_sets_best(self):
        result = quiet(snapshot.create_snapshot, self.out)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "v1")
        self.assertEqual(result["best"], "v1")
        self.assertEqual(result["stats"]["renders"], 1)
        for name in ("model.py", "brief.md", "report.json", "renders/view-front.png"):
            self.assertTrue(
                os.path.isfile(os.path.join(self.version_dir(), name)), name)
        best = read_json(os.path.join(self.out, snapshot.BEST_FILE))
        self.assertEqual(best["schema"], snapshot.SNAPSHOT_SCHEMA)
        self.assertEqual(best["version"], "v1")
        self.assertEqual(best["dir"], "history/v1")
        self.assertTrue(best["valid"])
        self.assertEqual(best["sha256"]["model.py"], snapshot._sha256(
            os.path.join(self.version_dir(), "model.py")))
        self.assertEqual(quiet(snapshot.validate_best, self.out), [])

    def test_second_snapshot_increments(self):
        quiet(snapshot.create_snapshot, self.out)
        result = quiet(snapshot.create_snapshot, self.out)
        self.assertEqual(result["version"], "v2")
        self.assertEqual(result["best"], "v2")
        rows = quiet(snapshot.list_versions, self.out)
        self.assertEqual([row["version"] for row in rows], ["v1", "v2"])
        self.assertTrue(rows[-1]["best"])

    def test_create_snapshot_requires_report(self):
        os.remove(os.path.join(self.out, "report.json"))
        result = quiet(snapshot.create_snapshot, self.out)
        self.assertFalse(result["ok"])
        self.assertIn("report.json", result["reason"])

    def test_create_snapshot_requires_renders(self):
        renders = os.path.join(self.out, "renders")
        for name in os.listdir(renders):
            os.remove(os.path.join(renders, name))
        result = quiet(snapshot.create_snapshot, self.out)
        self.assertFalse(result["ok"])
        self.assertIn("renders", result["reason"])

    # ---- promote / rollback ----
    def test_promote_missing_version_fails(self):
        quiet(snapshot.create_snapshot, self.out)
        self.assertEqual(quiet(snapshot.promote, self.out, "v9"), 1)
        self.assertEqual(quiet(snapshot.promote, self.out, "xx"), 1)

    def test_promote_older_version(self):
        quiet(snapshot.create_snapshot, self.out)
        quiet(snapshot.create_snapshot, self.out)
        self.assertEqual(quiet(snapshot.promote, self.out, "1"), 0)
        best = read_json(os.path.join(self.out, snapshot.BEST_FILE))
        self.assertEqual(best["version"], "v1")

    def test_rollback_restores_model_and_renders(self):
        quiet(snapshot.create_snapshot, self.out)
        model_path = os.path.join(self.out, "model.py")
        with open(model_path, "w", encoding="utf-8") as handle:
            handle.write("# 改坏的新版本\n")
        self.assertEqual(quiet(snapshot.rollback, self.out), 0)
        with open(model_path, "r", encoding="utf-8") as handle:
            self.assertIn("blender_kit", handle.read())
        self.assertTrue(os.path.isfile(
            os.path.join(self.out, "renders", "view-front.png")))

    def test_rollback_without_best_fails(self):
        self.assertEqual(quiet(snapshot.rollback, self.out), 1)

    # ---- validate_best 供 check_output 使用 ----
    def test_validate_best_detects_broken_version(self):
        quiet(snapshot.create_snapshot, self.out)
        os.remove(os.path.join(self.version_dir(), "model.py"))
        issues = quiet(snapshot.validate_best, self.out)
        self.assertIn("SNAP003", [item["code"] for item in issues])
        self.assertTrue(all(item["level"] == "WARN" for item in issues))

    def test_validate_best_missing_best_file(self):
        os.makedirs(os.path.join(self.out, snapshot.HISTORY_DIR))
        issues = quiet(snapshot.validate_best, self.out)
        self.assertIn("SNAP001", [item["code"] for item in issues])

    def test_validate_best_clean_dir(self):
        self.assertEqual(quiet(snapshot.validate_best, self.out), [])

    # ---- R9 回归：路径越界 / --rollback --json 版本号 ----
    def test_inside_rejects_escapes(self):
        self.assertTrue(snapshot._inside(self.out, "renders/view-front.png"))
        self.assertFalse(snapshot._inside(self.out, "../outside.png"))
        self.assertFalse(snapshot._inside(self.out, "renders/../../x.png"))
        self.assertFalse(snapshot._inside(self.out, "F:evil.png"))
        self.assertFalse(snapshot._inside(
            self.out, os.path.abspath("renders/view-front.png")))

    def test_validate_version_rejects_render_traversal(self):
        quiet(snapshot.create_snapshot, self.out)
        report_path = os.path.join(self.version_dir(), "report.json")
        report = read_json(report_path)
        report["renders"][0]["path"] = "../escape.png"
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False)
        issues, _stats = quiet(snapshot.validate_version, self.version_dir())
        self.assertTrue(any("越界" in issue for issue in issues), issues)
        self.assertEqual(quiet(snapshot.promote, self.out, "v1"), 1)

    def test_validate_version_rejects_export_traversal(self):
        quiet(snapshot.create_snapshot, self.out)
        report_path = os.path.join(self.version_dir(), "report.json")
        report = read_json(report_path)
        report["exports"]["blend"]["path"] = "../escape.blend"
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False)
        issues, _stats = quiet(snapshot.validate_version, self.version_dir())
        self.assertTrue(any("越界" in issue for issue in issues), issues)

    def test_rollback_json_reports_actual_version(self):
        quiet(snapshot.create_snapshot, self.out)
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture), \
                contextlib.redirect_stderr(io.StringIO()):
            code = snapshot.main(["--out", self.out, "--rollback", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(capture.getvalue())
        self.assertEqual(payload["action"], "rollback")
        self.assertEqual(payload["version"], "v1")
        self.assertEqual(payload["exit_code"], 0)


class VersionTest(unittest.TestCase):
    def test_canonical_version(self):
        self.assertEqual(snapshot.canonical_version("v2"), "v2")
        self.assertEqual(snapshot.canonical_version("2"), "v2")
        self.assertEqual(snapshot.canonical_version("history/v3"), "v3")
        self.assertIsNone(snapshot.canonical_version("vx"))
        self.assertIsNone(snapshot.canonical_version(""))

    def test_selftest_passes(self):
        self.assertEqual(quiet(snapshot.selftest), 0)


if __name__ == "__main__":
    unittest.main()
