# -*- coding: utf-8 -*-
"""SAFE_MODE：对 model.py / 模板做 AST 静态安全审查（不执行代码）。

用途：交付物是「由 AI 生成的 bpy 脚本」，执行前应能证明它没有越权行为。
本工具只做静态分析，给出 file:line 级 ERROR / WARN，供 ci_check.py 接入：

    python scripts/safe_check.py examples/lowpoly-mug/model.py
    python scripts/safe_check.py                      # 默认扫描 templates/*.py + examples/*/model.py
    python scripts/safe_check.py --json
    python scripts/safe_check.py --selftest

ERROR（必须为 0，否则脚本不应执行/入库）：
    SAFE001 导入危险模块（subprocess / socket / ctypes / importlib / 网络库等）
    SAFE002 调用危险函数（os.system / os.popen / eval / exec / compile / __import__ /
            shutil.copyfile / shutil.copy / shutil.copytree / shutil.move 等文件拷贝移动）
    SAFE003 写文件的路径是绝对路径（含盘符 / 盘符相对路径 C:evil.txt / UNC）
    SAFE004 写文件的路径包含 ".." 路径穿越
    SAFE006 写文件路径无法静态确定（变量路径）——无法证明安全，按不安全处理
    SAFE008 语法错误（无法审查）
    SAFE009 访问沙箱逃逸相关魔术属性（__globals__ / __subclasses__ / __builtins__ 等）

WARN（需要人工确认，不阻塞）：
    SAFE005 写入目录不在白名单（renders/ exports/ logs/ tmp/ 与 report.json 等）
    SAFE007 动态属性访问 / open 的 mode 无法静态确定

设计原则：白名单可写目录 + 危险调用黑名单；只读 open() 与正常 import 不受影响。
写文件路径必须「以白名单目录开头」（如 renders/a.png），仅当路径是单段文件名时
才按 report.json / brief.md 白名单放行；临时目录 / 输出目录环境变量表达式放行。
Python 3.9+，仅标准库。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tempfile

AUDIT_VERSION = 1

DENY_IMPORTS = {
    "subprocess", "socket", "ctypes", "importlib", "multiprocessing",
    "http", "urllib", "requests", "ftplib", "smtplib", "telnetlib",
    "xmlrpc", "webbrowser", "asyncio", "concurrent", "pty",
}
DENY_CALLS = {
    "eval", "exec", "compile", "__import__", "globals", "locals",
    "os.system", "os.popen", "os.fork", "os.forkpty", "os.execv", "os.execve",
    "os.execl", "os.execle", "os.execlp", "os.execlpe", "os.execvp",
    "os.execvpe", "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe", "os.posix_spawn",
    "os.startfile", "os.kill", "os.killpg", "os.abort",
    "shutil.rmtree", "shutil.move", "shutil.copyfile", "shutil.copy",
    "shutil.copy2", "shutil.copytree",
}
WARN_CALLS = {
    "os.remove", "os.unlink", "os.rmdir", "os.rename", "os.replace",
    "os.chdir", "os.mkdir", "os.makedirs", "getattr", "setattr", "delattr",
}
DENY_ATTRS = {
    "__globals__", "__subclasses__", "__builtins__", "__code__",
    "__closure__", "__reduce__", "__reduce_ex__", "__getattribute__",
}
ALLOWED_WRITE_DIRS = {"renders", "exports", "logs", "tmp", "temp", "history"}
ALLOWED_WRITE_FILES = {"report.json", "brief.md", "log.txt", "notes.txt"}
WRITE_MODES = set("wax+")
ABS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")
DRIVE_REL_RE = re.compile(r"^[A-Za-z]:(?![\\/])")  # C:evil.txt 盘符相对路径
TEMP_ENV_NAMES = {"TEMP", "TMP", "TMPDIR", "BLENDER_OUT_DIR", "OUT_DIR"}
MODE_READ_ONLY = {"r", "rb", "rt", "r+b"}




def _enable_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _issue(level, code, path, line, message, col=0):
    return {
        "level": level, "code": code, "path": str(path),
        "line": int(line), "col": int(col), "message": message,
    }


def _dotted(node):
    """把 ast.Attribute / ast.Name 链还原成 "os.path.join" 这样的字符串。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _literal_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _write_path_issues(path_value, filename, line):
    """检查一个字符串写入路径是否越权/穿越/不在白名单。"""
    issues = []
    normalized = path_value.replace("\\", "/")
    if ABS_PATH_RE.match(normalized) or os.path.isabs(path_value):
        issues.append(_issue("ERROR", "SAFE003", filename, line,
                             "写文件的路径是绝对路径（禁止）: %r" % path_value))
        return issues
    if DRIVE_REL_RE.match(normalized):
        issues.append(_issue("ERROR", "SAFE003", filename, line,
                             "写文件的路径是盘符相对路径（禁止）: %r" % path_value))
        return issues
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if ".." in parts:
        issues.append(_issue("ERROR", "SAFE004", filename, line,
                             "写文件的路径包含 '..' 路径穿越（禁止）: %r" % path_value))
        return issues
    if not parts:
        return issues
    first = parts[0]
    if first in ALLOWED_WRITE_DIRS:
        return issues
    # 只有「单段文件名」才走 artifact 文件白名单；data/report.json 这类
    # 借 basename 绕过目录白名单的写法不再放行。
    if len(parts) == 1 and first in ALLOWED_WRITE_FILES:
        return issues
    issues.append(_issue("WARN", "SAFE005", filename, line,
                         "写入目录不在白名单（renders/exports/logs/tmp）: %r" % path_value))
    return issues


class _Auditor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.issues = []

    def _add(self, level, code, node, message):
        self.issues.append(_issue(level, code, self.filename,
                                  getattr(node, "lineno", 0),
                                  message, getattr(node, "col_offset", 0)))

    # -- imports ---------------------------------------------------------
    def visit_Import(self, node):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in DENY_IMPORTS:
                self._add("ERROR", "SAFE001", node,
                          "禁止导入危险模块: %s" % alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        root = module.split(".")[0]
        if root in DENY_IMPORTS:
            self._add("ERROR", "SAFE001", node,
                      "禁止导入危险模块: from %s import ..." % module)
        self.generic_visit(node)

    # -- attributes ------------------------------------------------------
    def visit_Attribute(self, node):
        if node.attr in DENY_ATTRS:
            self._add("ERROR", "SAFE009", node,
                      "禁止访问沙箱逃逸相关属性: .%s" % node.attr)
        self.generic_visit(node)

    # -- calls -----------------------------------------------------------
    def visit_Call(self, node):
        func = node.func
        name = _dotted(func)
        if isinstance(func, ast.Attribute):
            short = func.attr
        else:
            short = name.rsplit(".", 1)[-1] if name else ""
        root = name.split(".")[0] if name else ""
        if (name in DENY_CALLS or short in ("eval", "exec", "compile", "__import__")
                or root in DENY_IMPORTS):
            self._add("ERROR", "SAFE002", node, "禁止调用危险函数: %s" % (name or short))
        elif name in WARN_CALLS:
            self._add("WARN", "SAFE007", node, "调用需人工确认: %s" % name)

        if short == "open" and isinstance(func, ast.Attribute) and name not in (
                "io.open", "codecs.open"):
            # pathlib.Path("...").open("w")：路径在 receiver（func.value），
            # 第一个参数是 mode 而不是路径。
            self._check_path_open(node, func.value)
        elif short == "open" or name in ("io.open", "codecs.open"):
            self._check_open(node)
        if short in ("write_text", "write_bytes"):
            # pathlib.Path("...").write_text("...")：路径在 func.value
            target = func.value
            literal = _literal_str(target)
            if literal is None and isinstance(target, ast.Call) and target.args:
                literal = _literal_str(target.args[0])
            if literal is not None:
                for issue in _write_path_issues(literal, self.filename,
                                                getattr(target, "lineno", node.lineno)):
                    self.issues.append(issue)
            elif not _is_tmp_or_out_dir_expression(target):
                self._add("ERROR", "SAFE006", node,
                          "写文件路径无法静态确定（%s，变量路径）" % name)
        elif short == "getattr" and len(node.args) >= 2:
            attr_value = _literal_str(node.args[1])
            if attr_value in DENY_ATTRS or attr_value in ("system", "popen"):
                self._add("ERROR", "SAFE002", node,
                          "通过 getattr 绕过限制: %r" % attr_value)
        self.generic_visit(node)

    def _check_open(self, node):
        if not node.args:
            return
        target = node.args[0]
        mode = None
        if len(node.args) >= 2:
            mode = _literal_str(node.args[1])
        else:
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode = _literal_str(keyword.value)
        if mode is None:
            if mode_given(node):
                self._add("WARN", "SAFE007", node, "open 的 mode 无法静态确定")
            return
        if mode in MODE_READ_ONLY:
            return
        if not (WRITE_MODES & set(mode)):
            return
        literal = _literal_str(target)
        if literal is not None:
            for issue in _write_path_issues(literal, self.filename,
                                            getattr(target, "lineno", node.lineno)):
                self.issues.append(issue)
        elif _is_tmp_or_out_dir_expression(target):
            return
        else:
            self._add("ERROR", "SAFE006", node,
                      "写文件路径无法静态确定（open 第一个参数不是字符串字面量，变量路径）")

    def _check_path_open(self, node, receiver):
        """Path(...).open(...)：receiver 是路径，node.args[0] 是 mode（默认 r）。"""
        has_mode_arg = bool(node.args) or any(
            keyword.arg == "mode" for keyword in node.keywords)
        mode = None
        if node.args:
            mode = _literal_str(node.args[0])
        else:
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode = _literal_str(keyword.value)
        if mode is None:
            if has_mode_arg:
                self._add("WARN", "SAFE007", node, "Path.open 的 mode 无法静态确定")
                return
            mode = "r"  # Path.open() 默认只读
        if mode in MODE_READ_ONLY or not (WRITE_MODES & set(mode)):
            return
        literal = None
        if isinstance(receiver, ast.Call) and receiver.args:
            literal = _literal_str(receiver.args[0])
        if literal is not None:
            for issue in _write_path_issues(literal, self.filename,
                                            getattr(receiver, "lineno", node.lineno)):
                self.issues.append(issue)
        elif _is_tmp_or_out_dir_expression(receiver):
            return
        else:
            self._add("ERROR", "SAFE006", node,
                      "Path.open 写文件路径无法静态确定（变量路径）")


def mode_given(node):
    """open 调用是否显式给了 mode（第二个位置参数或 mode= 关键字）。"""
    return len(node.args) >= 2 or any(kw.arg == "mode" for kw in node.keywords)


def _is_tmp_or_out_dir_expression(node):
    """输出目录/临时目录表达式放行（如 os.path.join(OUT_DIR, "a.bin")、%TEMP% 重定向）。

    识别：os.path.join/abspath/realpath/expanduser、tempfile.mkdtemp/mkstemp/gettempdir、
    os.environ / os.getenv 访问，以及表达式中出现 TEMP/TMP/TMPDIR/BLENDER_OUT_DIR/OUT_DIR
    字面量（如 os.environ["TEMP"]、os.path.join(os.getenv("TEMP"), "x")）。
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and "environ" in _dotted(child.value):
            return True
        if isinstance(child, ast.Call):
            full = _dotted(child.func)
            if full in ("os.path.join", "os.path.abspath", "os.path.realpath",
                        "os.path.expanduser", "tempfile.mkdtemp", "tempfile.mkstemp",
                        "tempfile.gettempdir"):
                return True
            if full.startswith("os.environ") or full.startswith("os.getenv"):
                return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value.upper() in TEMP_ENV_NAMES:
                return True
    return False


def audit_source(source, filename="model.py"):
    """静态审查一段 Python 源码，返回 issues 列表（ERROR/WARN）。"""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [_issue("ERROR", "SAFE008", filename, exc.lineno or 0,
                       "语法错误，无法审查: %s" % (exc.msg,), exc.offset or 0)]
    auditor = _Auditor(filename)
    auditor.visit(tree)
    return auditor.issues


def audit_file(path):
    """静态审查一个 .py 文件；读不到文件时返回 SAFE008 ERROR。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError as exc:
        return [_issue("ERROR", "SAFE008", path, 0, "无法读取文件: %r" % (exc,))]
    return audit_source(source, path)


def default_targets(root):
    """默认审查对象：templates/*.py 与 examples/*/model.py。"""
    targets = []
    templates_dir = os.path.join(root, "templates")
    if os.path.isdir(templates_dir):
        targets.extend(os.path.join(templates_dir, name)
                       for name in sorted(os.listdir(templates_dir))
                       if name.endswith(".py"))
    examples_dir = os.path.join(root, "examples")
    if os.path.isdir(examples_dir):
        for name in sorted(os.listdir(examples_dir)):
            candidate = os.path.join(examples_dir, name, "model.py")
            if os.path.isfile(candidate):
                targets.append(candidate)
    return targets


def format_issue(issue):
    level = issue["level"]
    return "[%s] %s:%s %s %s" % (level, issue["path"], issue["line"],
                                 issue["code"], issue["message"])


def summarize(issues):
    errors = sum(1 for item in issues if item["level"] == "ERROR")
    warns = sum(1 for item in issues if item["level"] == "WARN")
    return errors, warns


def selftest():
    failures = []
    cases = []

    def check(name, source, want_codes, want_errors=None):
        issues = audit_source(source)
        codes = [item["code"] for item in issues]
        missing = [code for code in want_codes if code not in codes]
        errors, _warns = summarize(issues)
        ok = not missing and (want_errors is None or errors == want_errors)
        cases.append((name, ok, missing, codes))

    check("干净脚本", "import os\nimport math\nx = 1 + 2\nprint(x)\n", [])
    check("subprocess 导入",
          "import subprocess\nsubprocess.run(['ls'])\n", ["SAFE001", "SAFE002"])
    check("os.system 调用",
          "import os\nos.system('echo hi')\n", ["SAFE002"])
    check("eval / exec / compile / __import__",
          "eval('1')\nexec('2')\ncompile('3', 'f', 'exec')\n"
          "__import__('os')\n", ["SAFE002"])
    check("socket / urllib 导入",
          "import socket\nfrom urllib import request\n", ["SAFE001"])
    check("绝对路径写文件",
          "open('C:/tmp/x.txt', 'w')\n", ["SAFE003"])
    check("路径穿越写文件",
          "open('../evil.txt', 'w')\n", ["SAFE004"])
    check("白名单外目录写文件（WARN）",
          "open('data/x.txt', 'w')\n", ["SAFE005"], 0)
    check("变量路径写文件（ERROR）",
          "dst = 'a.bin'\nopen(dst, 'wb')\n", ["SAFE006"], 1)
    check("输出目录环境变量直接传参放行",
          "import os\nopen(os.path.join(os.environ['BLENDER_OUT_DIR'], 'a.bin'), 'wb')\n",
          [], 0)
    check("临时目录表达式放行（%TEMP% 重定向）",
          "import os, tempfile\n"
          "open(os.path.join(os.environ['TEMP'], 'a.bin'), 'wb')\n"
          "open(os.path.join(tempfile.gettempdir(), 'b.bin'), 'w')\n", [], 0)
    check("只读 open 不告警",
          "open('README.md', 'r').read()\n", [], 0)
    check("pathlib 写文件检查",
          "from pathlib import Path\nPath('C:/tmp/a.txt').write_text('x')\n",
          ["SAFE003"])
    check("pathlib Path.open 绝对路径（ERROR）",
          "from pathlib import Path\nPath('C:/tmp/a.txt').open('w').write('x')\n",
          ["SAFE003"], 1)
    check("pathlib Path.open 变量路径（ERROR）",
          "from pathlib import Path\np = 'a.txt'\nPath(p).open('w').write('x')\n",
          ["SAFE006"], 1)
    check("只读 Path.open 不告警",
          "from pathlib import Path\nPath('README.md').open('r').read()\n", [], 0)
    check("盘符相对路径（ERROR）",
          "open('C:evil.txt', 'w')\n", ["SAFE003"], 1)
    check("借 basename 绕过目录白名单（WARN）",
          "open('data/report.json', 'w')\n", ["SAFE005"], 0)
    check("shutil 拷贝文件（ERROR）",
          "import shutil\nshutil.copyfile('renders/a.png', 'b.png')\n", ["SAFE002"])
    check("沙箱逃逸属性",
          "f = (lambda: 0).__globals__\n", ["SAFE009"])
    check("语法错误",
          "def broken(:\n", ["SAFE008"])

    for name, ok, missing, codes in cases:
        if ok:
            print("[PASS] selftest: " + name)
        else:
            print("[FAIL] selftest: %s（缺少 %s，实际 %s）"
                  % (name, ", ".join(missing) or "-", ", ".join(codes) or "-"))
            failures.append(name)

    # 真实文件往返（临时目录，不碰仓库）
    with tempfile.TemporaryDirectory(prefix="bm-safe-selftest-") as tmp:
        good_path = os.path.join(tmp, "good.py")
        with open(good_path, "w", encoding="utf-8") as handle:
            handle.write("import os\nvalue = os.path.join('a', 'b')\nprint(value)\n")
        issues = audit_file(good_path)
        if not issues:
            print("[PASS] selftest: audit_file 干净文件 0 issue")
        else:
            print("[FAIL] selftest: audit_file 干净文件出现 issue: %s"
                  % json.dumps(issues, ensure_ascii=False))
            failures.append("audit_file 干净文件")

    if failures:
        print("\nSELFTEST FAILED: %d 项失败" % len(failures))
        return 1
    print("\nSELFTEST OK")
    return 0


def main(argv=None):
    _enable_utf8_console()
    parser = argparse.ArgumentParser(
        description="SAFE_MODE：model.py 的 AST 静态安全审查（不执行代码）")
    parser.add_argument("paths", nargs="*", help="要审查的 .py 文件或目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--selftest", action="store_true", help="只运行自测")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    targets = list(args.paths)
    if not targets:
        targets = default_targets(root)
    files = []
    for target in targets:
        if os.path.isdir(target):
            for name in sorted(os.listdir(target)):
                if name.endswith(".py"):
                    files.append(os.path.join(target, name))
        else:
            files.append(target)
    # --json 时 stdout 必须是纯 JSON：人类可读日志一律走 stderr。
    log = sys.stderr if args.json else sys.stdout
    if not files:
        print("[SKIP] 没有可审查的 .py 文件。", file=log)
        if args.json:
            print(json.dumps({"version": AUDIT_VERSION, "files": [],
                              "errors": 0, "warns": 0, "issues": []},
                             ensure_ascii=False, indent=2))
        return 0

    all_issues = []
    for path in files:
        issues = audit_file(path)
        # 展示用相对路径
        display = path
        try:
            display = os.path.relpath(path, root).replace("\\", "/")
        except ValueError:
            pass
        for issue in issues:
            issue = dict(issue)
            issue["display"] = display
            all_issues.append(issue)
        errors, warns = summarize(issues)
        if errors == 0:
            print("[PASS] %s: 0 ERROR / %d WARN" % (display, warns), file=log)
        else:
            print("[ERROR] %s: %d ERROR / %d WARN" % (display, errors, warns), file=log)
        for issue in issues:
            print("    " + format_issue(dict(issue, path=display)), file=log)

    errors, warns = summarize(all_issues)
    if args.json:
        print(json.dumps({"version": AUDIT_VERSION, "files": files,
                          "errors": errors, "warns": warns,
                          "issues": all_issues}, ensure_ascii=False, indent=2))
    print("=== 结果: %d 文件 / %d ERROR / %d WARN ===" % (len(files), errors, warns),
          file=log)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
