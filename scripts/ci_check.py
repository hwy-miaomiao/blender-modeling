#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仓库静态检查：GitHub Actions 与本地提交前都跑它，必须 0 ERROR。

纯标准库，不需要 Blender、不需要 Pillow，也不渲染、不联网，几秒内跑完。

检查项：
1. SKILL.md frontmatter：name 为 kebab-case 且等于 blender-modeling，description 非空且 ≤500 字符
2. 核心文件齐全（规范、kit、模板、脚本、参考文档、两个样例）
3. examples/ 两个样例完整：图片魔数与尺寸、.blend/.glb 魔数、report.json 统计与相对路径
4. examples 的 model.py：通过 BLENDER_KIT_DIR 导入 kit、无盘符绝对路径、可编译
5. 文档引用审计：规范/README/参考文档里提到的 references/*.md、lib|scripts|templates/*.py 必须真实存在
6. 仓库约定文件：LICENSE、.gitignore、.gitattributes、CI workflow 存在

用法：
    python scripts/ci_check.py [--root <仓库根目录>]

退出码：0 = 无 ERROR；1 = 至少一个 ERROR。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys

SKILL_NAME = "blender-modeling"
DESCRIPTION_MAX = 500

REQUIRED_FILES = [
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "LICENSE",
    ".gitignore",
    ".gitattributes",
    ".github/workflows/ci.yml",
    "lib/blender_kit.py",
    "templates/model_template.py",
    "scripts/run_blender.py",
    "scripts/doctor.py",
    "scripts/check_output.py",
    "scripts/contact_sheet.py",
    "scripts/ci_check.py",
    "references/prompt-to-model.md",
    "references/render-and-check.md",
    "references/troubleshooting.md",
    "references/modeling-recipes.md",
    "references/bpy-cookbook.md",
]

EXAMPLE_SLUGS = ["lowpoly-mug", "office-chair"]
EXAMPLE_REQUIRED = [
    "brief.md",
    "model.py",
    "README.md",
    "report.json",
    "renders/view-front.png",
    "renders/view-right.png",
    "renders/view-iso.png",
    "exports/model.blend",
    "exports/model.glb",
]

DOC_FILES = [
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "CLAUDE.md",
    "references/prompt-to-model.md",
    "references/render-and-check.md",
    "references/troubleshooting.md",
    "references/modeling-recipes.md",
    "references/bpy-cookbook.md",
]

REF_MD_RE = re.compile(r"(?<![\w/.\\-])(references/[A-Za-z0-9_.-]+\.md)")
REF_PY_RE = re.compile(r"(?<![\w/.\\-])((?:lib|scripts|templates)/[A-Za-z0-9_.-]+\.py)")
ABS_PATH_RE = re.compile(r"(?<![\w/])[A-Za-z]:\\")


def _enable_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


class Checker:
    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.errors = 0
        self.warns = 0
        self.passes = 0

    # ---- 记录 ----
    def ok(self, msg: str) -> None:
        self.passes += 1
        print(f"[PASS] {msg}")

    def error(self, msg: str) -> None:
        self.errors += 1
        print(f"[ERROR] {msg}")

    def warn(self, msg: str) -> None:
        self.warns += 1
        print(f"[WARN] {msg}")

    # ---- 工具 ----
    def path(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    def exists(self, rel: str) -> bool:
        return os.path.isfile(self.path(rel))

    def read_text(self, rel: str) -> str:
        with open(self.path(rel), "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def read_head(self, rel: str, n: int) -> bytes:
        with open(self.path(rel), "rb") as fh:
            return fh.read(n)

    # ---- 1. SKILL.md ----
    def check_skill_md(self) -> None:
        if not self.exists("SKILL.md"):
            self.error("缺少 SKILL.md")
            return
        text = self.read_text("SKILL.md")
        if not text.startswith("---"):
            self.error("SKILL.md 没有以 YAML frontmatter（---）开头")
            return
        lines = text.splitlines()
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            self.error("SKILL.md frontmatter 没有结束的 ---")
            return
        fm = "\n".join(lines[1:end])

        m = re.search(r"(?m)^name:\s*(\S+)\s*$", fm)
        if not m:
            self.error("SKILL.md frontmatter 缺少 name")
        else:
            name = m.group(1).strip().strip("\"'")
            if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
                self.error(f"SKILL.md name 不是 kebab-case：{name!r}")
            elif name != SKILL_NAME:
                self.error(f"SKILL.md name 应为 {SKILL_NAME}，实际 {name!r}")
            else:
                self.ok(f"SKILL.md frontmatter name={name}（kebab-case）")

        m = re.search(r"(?m)^description:\s*(.+?)\s*$", fm)
        if not m:
            self.error("SKILL.md frontmatter 缺少 description")
        else:
            desc = m.group(1).strip().strip("\"'")
            if len(desc) < 10:
                self.error("SKILL.md description 过短（<10 字符）")
            elif len(desc) > DESCRIPTION_MAX:
                self.error(
                    f"SKILL.md description 超过 {DESCRIPTION_MAX} 字符（实际 {len(desc)}）"
                )
            else:
                self.ok(f"SKILL.md description {len(desc)} 字符（上限 {DESCRIPTION_MAX}）")
        if "name:" not in fm or "description:" not in fm:
            self.error("SKILL.md frontmatter 必须同时有 name 与 description")

    # ---- 2. 核心文件 ----
    def check_required_files(self) -> None:
        missing = [rel for rel in REQUIRED_FILES if not self.exists(rel)]
        if missing:
            self.error("缺少核心文件：" + ", ".join(missing))
        else:
            self.ok(f"核心文件齐全（{len(REQUIRED_FILES)} 个）")

    # ---- 3. examples ----
    @staticmethod
    def _png_size(head: bytes):
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        if len(head) < 24 or head[12:16] != b"IHDR":
            return None
        return struct.unpack(">II", head[16:24])

    def _check_png(self, rel: str, min_bytes: int = 15 * 1024, want: int = 512) -> bool:
        if not self.exists(rel):
            return False
        size = os.path.getsize(self.path(rel))
        head = self.read_head(rel, 32)
        dims = self._png_size(head)
        if dims is None:
            self.error(f"{rel} 不是合法 PNG")
            return False
        if size < min_bytes:
            self.error(f"{rel} 只有 {size} B（要求 ≥{min_bytes}）")
            return False
        if want and dims != (want, want):
            self.error(f"{rel} 尺寸 {dims[0]}x{dims[1]}（要求 {want}x{want}）")
            return False
        self.ok(f"{rel} {dims[0]}x{dims[1]} {size / 1024:.0f} KB")
        return True

    def _check_magic(self, rel: str, magic: bytes, label: str, min_bytes: int = 1024) -> bool:
        if not self.exists(rel):
            return False
        size = os.path.getsize(self.path(rel))
        head = self.read_head(rel, len(magic))
        if head != magic:
            self.error(f"{rel} 不是合法 {label}（开头应为 {magic!r}）")
            return False
        if size < min_bytes:
            self.error(f"{rel} 只有 {size} B（要求 ≥{min_bytes}）")
            return False
        self.ok(f"{rel} {label} {size / 1024:.0f} KB")
        return True

    @staticmethod
    def _is_relative(path_str: str) -> bool:
        if not isinstance(path_str, str) or not path_str:
            return False
        if os.path.isabs(path_str) or re.match(r"^[A-Za-z]:", path_str):
            return False
        if path_str.startswith("/") or path_str.startswith("\\"):
            return False
        return True

    def check_example(self, slug: str) -> None:
        base = f"examples/{slug}"
        missing = [rel for rel in EXAMPLE_REQUIRED if not self.exists(f"{base}/{rel}")]
        if missing:
            self.error(f"{base} 缺少文件：" + ", ".join(missing))
        else:
            self.ok(f"{base} 文件齐全（{len(EXAMPLE_REQUIRED)} 个）")

        for name in ("view-front", "view-right", "view-iso"):
            self._check_png(f"{base}/renders/{name}.png")
        self._check_magic(f"{base}/exports/model.blend", b"BLENDER", "blend", min_bytes=10 * 1024)
        self._check_magic(f"{base}/exports/model.glb", b"glTF", "glb", min_bytes=1024)

        model_py = f"{base}/model.py"
        if self.exists(model_py):
            text = self.read_text(model_py)
            try:
                compile(text, model_py, "exec")
                self.ok(f"{model_py} 可编译")
            except SyntaxError as exc:
                self.error(f"{model_py} 语法错误：{exc}")
            if "BLENDER_KIT_DIR" not in text and "blender_kit" not in text:
                self.error(f"{model_py} 未通过 BLENDER_KIT_DIR / blender_kit 导入 kit")
            if ABS_PATH_RE.search(text):
                self.error(f"{model_py} 含盘符绝对路径（生成脚本必须用相对路径/环境变量）")

        report_rel = f"{base}/report.json"
        if not self.exists(report_rel):
            return
        try:
            with open(self.path(report_rel), "r", encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError) as exc:
            self.error(f"{report_rel} 不是合法 JSON：{exc}")
            return
        scene = report.get("scene") if isinstance(report.get("scene"), dict) else report
        dims = scene.get("dimensions")
        if not (isinstance(dims, (list, tuple)) and len(dims) == 3 and all(
            isinstance(v, (int, float)) and v > 0 for v in dims
        )):
            self.error(f"{report_rel} dimensions 应为三轴正数：{dims!r}")
        else:
            self.ok(f"{report_rel} dimensions = {[round(float(v), 4) for v in dims]}")
        if int(scene.get("object_count") or 0) < 1:
            self.error(f"{report_rel} object_count < 1")
        if int(scene.get("total_tris") or 0) < 8:
            self.error(f"{report_rel} total_tris < 8（近似空模型）")
        renders = report.get("renders")
        if not isinstance(renders, list) or not renders:
            self.error(f"{report_rel} renders 为空或不是列表")
        else:
            bad = 0
            for item in renders:
                if not isinstance(item, dict):
                    bad += 1
                    continue
                rel = item.get("path", "")
                if not self._is_relative(rel):
                    self.error(f"{report_rel} renders 路径不是相对路径：{rel!r}")
                    bad += 1
                elif not self.exists(f"{base}/{rel}"):
                    self.error(f"{report_rel} 引用的渲染图不存在：{rel!r}")
                    bad += 1
                if float(item.get("std") or 0) <= 4.0:
                    self.error(f"{report_rel} {rel} 的 std={item.get('std')} 过低（疑似全黑/空白）")
                    bad += 1
                if float(item.get("black_ratio") or 0) >= 0.98:
                    self.error(f"{report_rel} {rel} 的 black_ratio ≥0.98（疑似全黑）")
                    bad += 1
            if bad == 0:
                self.ok(f"{report_rel} renders {len(renders)} 条统计与路径正常")
        exports = report.get("exports")
        if not isinstance(exports, dict):
            self.error(f"{report_rel} exports 不是对象")
        else:
            for kind in ("blend", "glb"):
                rec = exports.get(kind)
                if not isinstance(rec, dict):
                    self.error(f"{report_rel} exports 缺少 {kind} 记录")
                    continue
                rel = rec.get("path", "")
                if not self._is_relative(rel):
                    self.error(f"{report_rel} exports.{kind}.path 不是相对路径：{rel!r}")
                elif not self.exists(f"{base}/{rel}"):
                    self.error(f"{report_rel} 引用的导出文件不存在：{rel!r}")
            self.ok(f"{report_rel} exports 记录正常")

    def check_examples(self) -> None:
        ex_dir = self.path("examples")
        if not os.path.isdir(ex_dir):
            self.error("缺少 examples/ 目录")
            return
        found = sorted(
            name for name in os.listdir(ex_dir) if os.path.isdir(os.path.join(ex_dir, name))
        )
        for slug in EXAMPLE_SLUGS:
            if slug not in found:
                self.error(f"缺少示例 examples/{slug}/")
        for slug in EXAMPLE_SLUGS:
            if slug in found:
                self.check_example(slug)

    # ---- 4. Python 语法 ----
    def check_python_syntax(self) -> None:
        count = 0
        failed = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames if d not in (".git", "__pycache__", "blender-models", "outputs")
            ]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), self.root).replace(os.sep, "/")
                count += 1
                try:
                    compile(self.read_text(rel), rel, "exec")
                except SyntaxError as exc:
                    failed += 1
                    self.error(f"{rel} 语法错误：{exc}")
        if failed == 0:
            self.ok(f"全部 {count} 个 .py 文件语法通过")

    # ---- 5. 文档引用 ----
    def check_doc_references(self) -> None:
        missing = set()
        checked = 0
        for rel in DOC_FILES:
            if not self.exists(rel):
                continue
            text = self.read_text(rel)
            for pattern, kind in ((REF_MD_RE, "md"), (REF_PY_RE, "py")):
                for target in pattern.findall(text):
                    target = target.strip()
                    # 规范里用 `scripts/xxx.py` 作为「脚本路径」的占位示例，不是真实引用
                    if target.rsplit("/", 1)[-1] == "xxx.py":
                        continue
                    checked += 1
                    if not self.exists(target):
                        missing.add(f"{rel} -> {target}")
        if missing:
            for item in sorted(missing):
                self.error(f"文档引用了不存在的文件：{item}")
        else:
            self.ok(f"文档引用审计通过（{checked} 处引用均存在）")

    # ---- 运行 ----
    def run(self) -> int:
        print(f"仓库根目录：{self.root}")
        self.check_skill_md()
        self.check_required_files()
        self.check_examples()
        self.check_python_syntax()
        self.check_doc_references()
        print(f"=== 结果: {self.passes} PASS / {self.errors} ERROR / {self.warns} WARN ===")
        if self.errors:
            print("FAIL：存在 ERROR，仓库不可发布/不可提交。")
            return 1
        print("PASS：仓库静态检查通过。")
        return 0


def main(argv=None) -> int:
    _enable_utf8_console()
    parser = argparse.ArgumentParser(description="blender-modeling 仓库静态检查（无 Blender 依赖）")
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="仓库根目录（默认本脚本的上级目录）",
    )
    args = parser.parse_args(argv)
    return Checker(args.root).run()


if __name__ == "__main__":
    sys.exit(main())
