# -*- coding: utf-8 -*-
"""blender-modeling 技能公共工具（系统 Python，仅标准库）。

职责：
- 定位 Blender 可执行文件（Windows / macOS / Linux）
- 以 headless 方式执行建模脚本，统一超时、日志、错误提取
- 解析 Blender 输出里的错误/警告（过滤 TBBmalloc 之类平台噪音）

本模块不导入 bpy，可在 Blender 外部运行。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time


def _enable_utf8_console():
    """让脚本在 Windows 上以 UTF-8 输出中文（避免 GBK 控制台把中文写成乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_enable_utf8_console()

# <技能目录>：本文件位于 <技能目录>/scripts/bl_common.py
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT_DIR = os.path.join(SKILL_DIR, "lib")
TEMPLATE_DIR = os.path.join(SKILL_DIR, "templates")
REFERENCES_DIR = os.path.join(SKILL_DIR, "references")

# Windows 下 Blender 启动时会往 stderr 打的无害噪音
_NOISE_MARKERS = (
    "TBBmalloc",
    "skip allocation functions replacement",
    "unknown prologue for function",
)

_ERROR_RE = (
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"^\s*[A-Za-z_][\w.]*(?:Error|Exception):\s"),
    re.compile(r"^\s*Error:\s"),
    re.compile(r"^\s*ERROR:\s"),
    re.compile(r"Segmentation fault", re.IGNORECASE),
    re.compile(r"core dumped"),
    re.compile(r"cannot open file", re.IGNORECASE),
    re.compile(r"failed to (?:load|read|open|write|export|render)", re.IGNORECASE),
    re.compile(r"ModuleNotFoundError"),
)

_WARN_RE = (
    re.compile(r"^\s*Warning:\s"),
    re.compile(r"^\s*WARN(?:ING)?:\s"),
)

_VERSION_RE = re.compile(r"Blender\s+(\d+)\.(\d+)\.(\d+)")

_WINDOWS_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# 定位 Blender
# ---------------------------------------------------------------------------

def no_window_flags():
    """Windows 下隐藏子进程控制台窗口；其它平台返回 0。"""
    return _WINDOWS_NO_WINDOW if os.name == "nt" else 0


def _windows_candidates():
    roots = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            roots.append(os.path.join(base, "Blender Foundation"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Programs", "Blender Foundation"))

    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root), reverse=True)
        except OSError:
            continue
        for name in names:
            candidate = os.path.join(root, name, "blender.exe")
            if os.path.isfile(candidate):
                out.append(candidate)

    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            steam = os.path.join(base, "Steam", "steamapps", "common", "Blender", "blender.exe")
            if os.path.isfile(steam):
                out.append(steam)
    return out


def _posix_candidates():
    if sys.platform == "darwin":
        return [
            "/Applications/Blender.app/Contents/MacOS/Blender",
            os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
        ]
    return [
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
        "/opt/blender/blender",
    ]


def find_blender(explicit=None):
    """按优先级定位 Blender，返回可执行文件绝对路径；找不到返回 None。

    优先级：显式参数 > 环境变量 BLENDER_EXE > PATH > 常见安装路径。
    """
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_exe = os.environ.get("BLENDER_EXE")
    if env_exe:
        candidates.append(env_exe)
    for name in ("blender", "blender.exe", "Blender"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    candidates.extend(_windows_candidates() if os.name == "nt" else _posix_candidates())

    seen = set()
    for cand in candidates:
        try:
            cand = os.path.abspath(os.path.expanduser(cand))
        except (TypeError, ValueError):
            continue
        if cand in seen:
            continue
        seen.add(cand)
        if os.path.isfile(cand):
            return cand
    return None


def blender_version(exe, timeout=30):
    """运行 `blender --version` 并解析版本。

    返回 {"ok": bool, "version": "4.0.2" | None, "tuple": (4,0,2) | None, "error": str | None}
    """
    if not exe:
        return {"ok": False, "version": None, "tuple": None, "error": "没有 Blender 可执行文件"}
    try:
        proc = subprocess.run(
            [exe, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=no_window_flags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "version": None, "tuple": None, "error": str(exc)}

    text = (proc.stdout or b"").decode("utf-8", "replace")
    match = _VERSION_RE.search(text)
    if not match:
        return {"ok": False, "version": None, "tuple": None, "error": "无法解析版本输出: " + text[:200]}
    ver = tuple(int(x) for x in match.groups())
    return {"ok": True, "version": "%d.%d.%d" % ver, "tuple": ver, "error": None}


# ---------------------------------------------------------------------------
# 日志解析
# ---------------------------------------------------------------------------

def _uniq(seq, cap=25):
    out, seen = [], set()
    for item in seq:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= cap:
            break
    return out


def classify_log(text):
    """从 Blender 日志中提取错误行与警告行（去重、过滤已知噪音）。"""
    errors, warnings = [], []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if any(marker in line for marker in _NOISE_MARKERS):
            continue
        stripped = line.strip()
        if any(rx.search(stripped) for rx in _ERROR_RE):
            errors.append(stripped)
        elif any(rx.search(stripped) for rx in _WARN_RE):
            warnings.append(stripped)
    return _uniq(errors), _uniq(warnings)


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

def _list_artifacts(out_dir):
    """列出输出目录中 renders/ 与 exports/ 下的文件（相对 out_dir）。"""
    found = {"renders": [], "exports": []}
    for sub in ("renders", "exports"):
        folder = os.path.join(out_dir, sub)
        if not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                rel = os.path.relpath(path, out_dir).replace("\\", "/")
                found[sub].append({"path": rel, "bytes": size})
    return found


def execute(script, out_dir, stage="full", timeout=600, label=None,
            extra_args=None, blender=None, quiet=False):
    """以 headless 方式执行一个建模脚本。

    参数：
        script     建模脚本路径（必需）
        out_dir    输出目录（必需；会创建 <out_dir>/logs）
        stage      "build" | "render" | "full"（通过 BLENDER_STAGE 注入）
        timeout    秒；超时会杀掉 Blender 并判失败
        label      日志文件名前缀，缺省用 stage
        extra_args 追加到 `--` 之后的参数
        blender    显式指定 Blender 可执行文件

    返回 dict：ok/exit_code/stage/script/out/blender/blender_version/log/
               duration_s/errors/warnings/renders/exports
    """
    script = os.path.abspath(script)
    out_dir = os.path.abspath(out_dir)
    stage = stage or "full"
    result = {
        "ok": False,
        "exit_code": None,
        "stage": stage,
        "script": script,
        "out": out_dir,
        "blender": None,
        "blender_version": None,
        "log": None,
        "duration_s": 0.0,
        "errors": [],
        "warnings": [],
        "renders": [],
        "exports": [],
    }

    if not os.path.isfile(script):
        result["errors"] = ["找不到建模脚本: " + script]
        _print_result(result, quiet)
        return result

    exe = blender or find_blender()
    if not exe:
        result["errors"] = [
            "找不到 Blender：请安装 Blender 4.x，或设置环境变量 BLENDER_EXE/--blender 指向 blender.exe"
        ]
        _print_result(result, quiet)
        return result
    result["blender"] = exe
    result["blender_version"] = blender_version(exe).get("version")

    try:
        os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)
    except OSError as exc:
        result["errors"] = ["无法创建输出目录: %s (%s)" % (out_dir, exc)]
        _print_result(result, quiet)
        return result

    log_name = "%s-%s.log" % (label or stage, time.strftime("%Y%m%d-%H%M%S"))
    log_path = os.path.join(out_dir, "logs", log_name)
    result["log"] = log_path

    cmd = [exe, "-b", "--factory-startup", "-noaudio",
           "--python-exit-code", "1", "--python", script]
    if extra_args:
        cmd += ["--"] + [str(a) for a in extra_args]

    env = os.environ.copy()
    env["BLENDER_KIT_DIR"] = KIT_DIR
    env["BLENDER_SKILL_DIR"] = SKILL_DIR
    env["BLENDER_OUT_DIR"] = out_dir
    env["BLENDER_STAGE"] = stage
    env.setdefault("PYTHONIOENCODING", "utf-8")

    started = time.time()
    timed_out = False
    output = ""
    exit_code = None
    try:
        proc = subprocess.run(
            cmd,
            cwd=out_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=no_window_flags(),
        )
        output = (proc.stdout or b"").decode("utf-8", "replace")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        raw = exc.stdout or b""
        output = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        output += "\n[TIMEOUT] Blender 超过 %ss 未结束，已终止\n" % timeout
        exit_code = -1
    except OSError as exc:
        result["errors"] = ["启动 Blender 失败: %s" % exc]
        _print_result(result, quiet)
        return result

    duration = round(time.time() - started, 2)

    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(output)
    except OSError as exc:
        result["warnings"].append("写日志失败: %s" % exc)

    errors, warnings = classify_log(output)
    if timed_out:
        errors.insert(0, "TIMEOUT: 超过 %ss 未结束" % timeout)
    if exit_code != 0 and not timed_out and not errors:
        errors.insert(0, "Blender 退出码 %s（日志无明确错误行，检查日志尾部）" % exit_code)

    artifacts = _list_artifacts(out_dir)
    result.update({
        "ok": (not timed_out) and exit_code == 0 and not errors,
        "exit_code": exit_code,
        "duration_s": duration,
        "errors": errors,
        "warnings": warnings,
        "renders": artifacts["renders"],
        "exports": artifacts["exports"],
    })
    _print_result(result, quiet)
    return result


def _print_result(result, quiet=False):
    if quiet:
        print("BM_RESULT " + json.dumps(result, ensure_ascii=False))
        return
    print("[run_blender] Blender: %s (%s)" % (result.get("blender"), result.get("blender_version")))
    print("[run_blender] stage=%s script=%s" % (result.get("stage"), result.get("script")))
    print("[run_blender] out=%s" % result.get("out"))
    for item in result.get("renders") or []:
        print("[run_blender] render: %s (%.1f KB)" % (item["path"], item["bytes"] / 1024.0))
    for item in result.get("exports") or []:
        print("[run_blender] export: %s (%.1f KB)" % (item["path"], item["bytes"] / 1024.0))
    for item in result.get("warnings") or []:
        print("[run_blender] WARN: " + item)
    for item in result.get("errors") or []:
        print("[run_blender] ERROR: " + item)
    state = "OK" if result.get("ok") else "FAILED"
    print("[run_blender] %s exit=%s duration=%.2fs log=%s" % (
        state, result.get("exit_code"), result.get("duration_s") or 0.0, result.get("log")))
    print("BM_RESULT " + json.dumps(result, ensure_ascii=False))
