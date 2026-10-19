#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仓库静态检查：GitHub Actions 与本地提交前都跑它，必须 0 ERROR。

纯标准库，不需要 Blender、不需要 Pillow，也不渲染、不联网，几秒内跑完。

检查项：
1. SKILL.md frontmatter：name 为 kebab-case 且等于 blender-modeling，description 非空且 ≤500 字符
2. 核心文件齐全（规范、kit、模板、脚本、参考文档、测试、两个样例）
3. examples/ 两个样例完整：图片魔数与尺寸、.blend/.glb 魔数、report.json 统计与相对路径
4. examples 的 model.py：通过 BLENDER_KIT_DIR 导入 kit、无盘符绝对路径、可编译
5. 交付 GLB 只含几何体：不得出现摄影棚地台（Floor/FloorMat）、布尔 cutter、.001 重名
6. CI workflow 必须包含语法检查、自测、仓库检查、单元测试四类步骤
7. 领域技巧文档（建筑/人物/动物/植物）：10 节结构齐全、python 块可编译、无盘符绝对路径
8. 文档引用审计：规范/README/参考文档里提到的 references/*.md、lib|scripts|templates/*.py 必须真实存在
9. 仓库约定文件：LICENSE、.gitignore、.gitattributes、CI workflow 存在

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
    "references/export-and-integration.md",
    "references/architecture-modeling.md",
    "references/character-modeling.md",
    "references/animal-modeling.md",
    "references/plant-modeling.md",
    "templates/edit_model_template.py",
    "CHANGELOG.md",
    "tests/README.md",
    "tests/test_cli_contract.py",
    "tests/test_bl_common.py",
    "tests/test_contact_sheet.py",
    "tests/test_ci_check.py",
    "tests/kit_smoke.blender.py",
    "tests/kit_regression.blender.py",
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
    "CHANGELOG.md",
    "references/prompt-to-model.md",
    "references/render-and-check.md",
    "references/troubleshooting.md",
    "references/modeling-recipes.md",
    "references/bpy-cookbook.md",
    "references/export-and-integration.md",
    "references/architecture-modeling.md",
    "references/character-modeling.md",
    "references/animal-modeling.md",
    "references/plant-modeling.md",
]

# 四篇领域技巧文档：固定 10 节结构 + python 块可编译 + 无盘符绝对路径
DOMAIN_DOCS = [
    "references/architecture-modeling.md",
    "references/character-modeling.md",
    "references/animal-modeling.md",
    "references/plant-modeling.md",
]
DOMAIN_SECTIONS = [
    ("适用范围", re.compile(r"适用范围")),
    ("结构拆解", re.compile(r"结构拆解")),
    ("比例与尺寸", re.compile(r"比例.{0,4}(?:与|和)?\s*尺寸|尺寸.{0,4}参考")),
    ("技巧库", re.compile(r"技巧库|技巧集合|核心技巧")),
    ("配方骨架", re.compile(r"配方")),
    ("材质与配色", re.compile(r"材质.{0,4}配色|材质与颜色|配色")),
    ("灯光与相机", re.compile(r"灯光|相机|构图")),
    ("常见错误", re.compile(r"常见(?:错误|问题|坑)")),
    ("验收自检", re.compile(r"验收|自检|检查清单")),
    ("实测记录", re.compile(r"实测记录|实测数据")),
]
DOMAIN_MIN_LINES = 250
DOMAIN_MIN_BLOCKS = 6
PY_BLOCK_RE = re.compile(r"```python[ \t]*\n(.*?)```", re.S)

REF_MD_RE = re.compile(r"(?<![\w/.\\-])(references/[A-Za-z0-9_.-]+\.md)")
REF_PY_RE = re.compile(r"(?<![\w/.\\-])((?:lib|scripts|templates)/[A-Za-z0-9_.-]+\.py)")
ABS_PATH_RE = re.compile(r"(?<![\w/])[A-Za-z]:[\\/]")

# 交付资产（.glb）里绝不该出现的名字：摄影棚地台、布尔 cutter、Blender 自动重名后缀
FORBIDDEN_GLB_MATERIALS = ("FloorMat",)
FORBIDDEN_GLB_NAME_PREFIXES = ("Floor",)
BAD_SUFFIX = ".001"


def _as_int(value):
    """把 report 里的值转 int；bool/字符串/列表等非法类型返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _as_float(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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
        has_name = re.search(r"(?m)^name:\s*\S+\s*$", fm) is not None
        has_desc = re.search(r"(?m)^description:\s*\S+", fm) is not None
        if not has_name and not has_desc:
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

    def _check_glb_asset(self, rel: str) -> None:
        """校验交付 GLB 只含几何体：不得有摄影棚地台、布尔 cutter、.001 重名。"""
        if not self.exists(rel):
            return
        with open(self.path(rel), "rb") as fh:
            data = fh.read()
        if len(data) < 20 or data[:4] != b"glTF":
            return
        offset = 12
        doc = None
        while offset + 8 <= len(data):
            clen = struct.unpack("<I", data[offset:offset + 4])[0]
            ctype = data[offset + 4:offset + 8]
            body = data[offset + 8:offset + 8 + clen]
            if ctype == b"JSON":
                try:
                    doc = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    self.error(f"{rel} 的 JSON chunk 无法解析")
                    return
                break
            offset += 8 + clen
        if not isinstance(doc, dict):
            return
        names = []
        for key in ("nodes", "meshes"):
            for item in doc.get(key) or []:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
        materials = []
        for item in doc.get("materials") or []:
            if isinstance(item, dict) and item.get("name"):
                materials.append(str(item["name"]))
        bad = 0
        for name in names + materials:
            if name in FORBIDDEN_GLB_MATERIALS or name.endswith(BAD_SUFFIX) or any(
                name.startswith(prefix) for prefix in FORBIDDEN_GLB_NAME_PREFIXES
            ):
                bad += 1
                self.error(
                    f"{rel} 含不该交付的对象/材质 {name!r}"
                    "（应排除摄影棚地台、布尔 cutter 与 .001 重名，见 kit 1.1.0+）"
                )
        if bad == 0:
            self.ok(f"{rel} 仅含几何体（nodes={len(names)} materials={len(materials)}）")

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
        self._check_glb_asset(f"{base}/exports/model.glb")

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
        if not isinstance(report, dict):
            self.error(f"{report_rel} 顶层必须是 JSON 对象，实际是 {type(report).__name__}")
            return
        scene = report.get("scene") if isinstance(report.get("scene"), dict) else report
        dims = scene.get("dimensions")
        dim_vals = None
        if isinstance(dims, (list, tuple)) and len(dims) == 3:
            vals = [_as_float(v) for v in dims]
            if all(v is not None and v > 0 for v in vals):
                dim_vals = vals
        if dim_vals is None:
            self.error(f"{report_rel} dimensions 应为三轴正数：{dims!r}")
        else:
            self.ok(f"{report_rel} dimensions = {[round(v, 4) for v in dim_vals]}")
        object_count = _as_int(scene.get("object_count"))
        if object_count is None or object_count < 1:
            self.error(f"{report_rel} object_count 缺失/非数字/小于 1：{scene.get('object_count')!r}")
        total_tris = _as_int(scene.get("total_tris"))
        if total_tris is None or total_tris < 8:
            self.error(f"{report_rel} total_tris 缺失/非数字/小于 8（近似空模型）：{scene.get('total_tris')!r}")
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
                std = _as_float(item.get("std"))
                if std is None or std <= 4.0:
                    self.error(f"{report_rel} {rel} 的 std 缺失/非数字/≤4.0（疑似全黑或空白）")
                    bad += 1
                black_ratio = _as_float(item.get("black_ratio"))
                if black_ratio is None or black_ratio >= 0.98:
                    self.error(f"{report_rel} {rel} 的 black_ratio 缺失/非数字/≥0.98（疑似全黑）")
                    bad += 1
            if bad == 0:
                self.ok(f"{report_rel} renders {len(renders)} 条统计与路径正常")
        exports = report.get("exports")
        if not isinstance(exports, dict):
            self.error(f"{report_rel} exports 不是对象")
        else:
            bad = 0
            for kind in ("blend", "glb"):
                rec = exports.get(kind)
                if not isinstance(rec, dict):
                    self.error(f"{report_rel} exports 缺少 {kind} 记录")
                    bad += 1
                    continue
                rel = rec.get("path", "")
                if not self._is_relative(rel):
                    self.error(f"{report_rel} exports.{kind}.path 不是相对路径：{rel!r}")
                    bad += 1
                elif not self.exists(f"{base}/{rel}"):
                    self.error(f"{report_rel} 引用的导出文件不存在：{rel!r}")
                    bad += 1
            if bad == 0:
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
                try:
                    self.check_example(slug)
                except Exception as exc:  # 单个样例的脏数据不能拖垮整个检查
                    self.error(f"examples/{slug} 检查过程中抛异常：{exc!r}")

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

    # ---- 5. CI workflow ----
    def check_ci_workflow(self) -> None:
        rel = ".github/workflows/ci.yml"
        if not self.exists(rel):
            return
        text = self.read_text(rel)
        required = ("compileall", "check_output.py --selftest", "ci_check.py", "unittest")
        missing = [token for token in required if token not in text]
        if missing:
            self.error(f"{rel} 缺少步骤关键字：{missing}")
        else:
            self.ok(f"{rel} 含语法/自测/仓库检查/单元测试步骤")

    # ---- 6. 领域技巧文档 ----
    def check_domain_docs(self) -> None:
        for rel in DOMAIN_DOCS:
            if not self.exists(rel):
                self.error(f"缺少领域技巧文档：{rel}")
                continue
            text = self.read_text(rel)
            problems = []
            lines = text.count("\n") + 1
            if lines < DOMAIN_MIN_LINES:
                problems.append(f"行数偏少（{lines} < {DOMAIN_MIN_LINES}）")
            missing = [name for name, pattern in DOMAIN_SECTIONS if not pattern.search(text)]
            if missing:
                problems.append("缺章节：" + ", ".join(missing))
            blocks = PY_BLOCK_RE.findall(text)
            if len(blocks) < DOMAIN_MIN_BLOCKS:
                problems.append(f"python 代码块过少（{len(blocks)} < {DOMAIN_MIN_BLOCKS}）")
            for index, block in enumerate(blocks, 1):
                try:
                    compile(block, f"{rel}#block{index}", "exec")
                except SyntaxError as exc:
                    problems.append(f"python 块 #{index} 语法错误：{exc.msg}（第 {exc.lineno} 行）")
            abs_hits = ABS_PATH_RE.findall(text)
            if abs_hits:
                problems.append(f"出现盘符绝对路径（{len(abs_hits)} 处），应使用 BLENDER_KIT_DIR 等环境变量")
            if problems:
                for problem in problems:
                    self.error(f"{rel}：{problem}")
            else:
                self.ok(f"{rel} 结构完整（{lines} 行 / {len(blocks)} 个 python 块 / 10 节齐全）")

    # ---- 7. 文档引用 ----
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
        self.check_ci_workflow()
        self.check_domain_docs()
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
