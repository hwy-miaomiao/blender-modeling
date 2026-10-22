# -*- coding: utf-8 -*-
"""产物版本快照：history/vN/ + best.json（只读写输出目录，不碰 git）。

背景（竞品融合）：Amagine3D 用「commit gate + 可回滚」保证只交付通过检查的版本。
本工具给无头建模流水线提供同样能力：每轮迭代后把 model.py / renders/ / report.json
存成 history/vN/，结构自检通过才更新 best.json（当前最佳交付版本），支持回滚。

用法：
    python scripts/snapshot.py --out <输出目录>                 # 新建快照 vN
    python scripts/snapshot.py --out <输出目录> --list          # 列出所有版本
    python scripts/snapshot.py --out <输出目录> --promote v2    # 把 v2 设为 best
    python scripts/snapshot.py --out <输出目录> --rollback      # 回滚到 best 版本
    python scripts/snapshot.py --out <输出目录> --rollback v1   # 回滚到指定版本
    python scripts/snapshot.py --selftest

结构约定（check_output.py 会按此校验）：
    <out>/history/vN/model.py
    <out>/history/vN/brief.md       （存在则复制）
    <out>/history/vN/report.json
    <out>/history/vN/renders/*.png
    <out>/best.json                 {schema, version, dir, created_at, promoted_at,
                                     renders, objects, tris, valid, issues, sha256}
只复制上述文件（不复制 exports/，避免 .blend/.glb 体积膨胀）；rollback 不还原
exports/，导出文件以当前目录为准。

仅标准库；Python 3.9+。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile

SNAPSHOT_SCHEMA = 1
HISTORY_DIR = "history"
BEST_FILE = "best.json"
MODEL_FILE = "model.py"
BRIEF_FILE = "brief.md"
REPORT_FILE = "report.json"
RENDERS_DIR = "renders"
CONTACT_SHEET_NAME = "contact-sheet.png"
COPY_FILES = (MODEL_FILE, BRIEF_FILE, REPORT_FILE)
VERSION_RE = re.compile(r"^v(\d+)$")


def _enable_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _list_pngs(directory):
    if not os.path.isdir(directory):
        return []
    return [name for name in sorted(os.listdir(directory))
            if name.lower().endswith(".png") and name != CONTACT_SHEET_NAME]


def version_dirs(out_dir):
    """返回 [(数字版本, 'vN', 目录绝对路径)]，按版本号升序。"""
    history = os.path.join(out_dir, HISTORY_DIR)
    rows = []
    if not os.path.isdir(history):
        return rows
    for name in os.listdir(history):
        match = VERSION_RE.match(name)
        path = os.path.join(history, name)
        if match and os.path.isdir(path):
            rows.append((int(match.group(1)), name, path))
    rows.sort(key=lambda row: row[0])
    return rows


def canonical_version(value):
    """把 'v2' / '2' / 'history/v2' 归一化成 'v2'；非法返回 None。"""
    if value is None:
        return None
    text = str(value).strip().replace("\\", "/").rstrip("/")
    if "/" in text:
        text = text.split("/")[-1]
    match = VERSION_RE.match(text)
    if match:
        return "v%d" % int(match.group(1))
    if text.isdigit():
        return "v%d" % int(text)
    return None


def snapshot_path(out_dir, version):
    return os.path.join(out_dir, HISTORY_DIR, canonical_version(version) or "")


def _inside(base, rel):
    """相对路径解析后是否仍位于 base 内（拦绝对路径/盘符/'..' 越界）。

    R9-B12：旧实现只判 os.path.isabs，'../outside.png' 会把校验指向版本目录
    之外的文件；错误导出的 report 也能借 '..' 绕过结构自检。
    """
    if not isinstance(rel, str) or not rel.strip():
        return False
    normalized = rel.replace("\\", "/")
    if os.path.isabs(rel) or re.match(r"^[A-Za-z]:", normalized):
        return False
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, normalized))
    try:
        return os.path.commonpath([base_abs, target]) == base_abs
    except ValueError:  # 不同盘符
        return False


def validate_version(version_dir):
    """校验单个版本目录的结构一致性，返回 (issues, stats)。"""
    issues = []
    stats = {"renders": 0, "objects": 0, "tris": 0}
    if not os.path.isdir(version_dir):
        return ["版本目录不存在: %s" % version_dir], stats
    model_path = os.path.join(version_dir, MODEL_FILE)
    report_path = os.path.join(version_dir, REPORT_FILE)
    if not os.path.isfile(model_path):
        issues.append("缺少 model.py")
    elif os.path.getsize(model_path) == 0:
        issues.append("model.py 为空")
    else:
        try:
            with open(model_path, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
            compile(source, model_path, "exec")
        except SyntaxError as exc:
            issues.append("model.py 语法错误: line %s: %s" % (exc.lineno, exc.msg))
        else:
            if "blender_kit" not in source and "BLENDER_KIT_DIR" not in source:
                issues.append("model.py 未引用 blender_kit / BLENDER_KIT_DIR")
    report = _read_json(report_path)
    if report is None:
        issues.append("缺少或无法解析 report.json")
        return issues, stats
    if not isinstance(report, dict):
        return issues + ["report.json 顶层不是对象"], stats
    renders = report.get("renders")
    if not isinstance(renders, list) or not renders:
        issues.append("report.renders 为空")
        renders = []
    stats["renders"] = len(renders)
    objects = report.get("object_count")
    if isinstance(objects, int):
        stats["objects"] = objects
    tris = report.get("total_tris")
    if isinstance(tris, int):
        stats["tris"] = tris
    for entry in renders:
        rel = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(rel, str) or not rel:
            issues.append("report.renders 条目缺少 path")
            continue
        normalized = rel.replace("\\", "/")
        if not _inside(version_dir, normalized):
            issues.append("report.renders 的 path 必须是版本目录内的相对路径"
                          "（禁止绝对路径/盘符/.. 越界）: %r" % rel)
            continue
        if not os.path.isfile(os.path.join(version_dir, normalized)):
            issues.append("渲染统计记录的文件不存在: %r" % rel)
    pngs = _list_pngs(os.path.join(version_dir, RENDERS_DIR))
    if renders and len(pngs) != len(renders):
        issues.append("renders/ 图片数(%d) 与 report.renders(%d) 不一致"
                      % (len(pngs), len(renders)))
    exports = report.get("exports")
    if not isinstance(exports, dict):
        issues.append("report 缺少 exports 记录")
    else:
        for key in ("blend", "glb"):
            entry = exports.get(key)
            rel = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(rel, str) or not rel:
                issues.append("report.exports 缺少 %s 记录" % key)
            elif not _inside(version_dir, rel):
                issues.append("report.exports.%s 的 path 必须是相对路径"
                              "（禁止绝对路径/盘符/.. 越界）: %r" % (key, rel))
    return issues, stats


def _version_number(version):
    match = VERSION_RE.match(version or "")
    return int(match.group(1)) if match else -1


def _best_payload(version, version_dir, stats, issues, out_dir, created):
    return {
        "schema": SNAPSHOT_SCHEMA,
        "version": version,
        "dir": "%s/%s" % (HISTORY_DIR, version),
        "created_at": created,
        "promoted_at": _utc_now(),
        "renders": stats["renders"],
        "objects": stats["objects"],
        "tris": stats["tris"],
        "valid": not issues,
        "issues": issues,
        "sha256": {
            MODEL_FILE: _sha256(os.path.join(version_dir, MODEL_FILE))
            if os.path.isfile(os.path.join(version_dir, MODEL_FILE)) else "",
        },
    }


def create_snapshot(out_dir):
    """对当前产物目录新建 history/vN；结构自检通过才更新 best.json。"""
    out_dir = os.path.abspath(out_dir)
    missing = [name for name in (MODEL_FILE, REPORT_FILE)
               if not os.path.isfile(os.path.join(out_dir, name))]
    if missing:
        print("[ERROR] 产物目录缺少必需文件: %s" % ", ".join(missing))
        return {"ok": False, "reason": "缺少 %s" % ", ".join(missing)}
    if not _list_pngs(os.path.join(out_dir, RENDERS_DIR)):
        print("[ERROR] 产物目录 renders/ 下没有 PNG")
        return {"ok": False, "reason": "renders/ 为空"}
    rows = version_dirs(out_dir)
    number = (rows[-1][0] + 1) if rows else 1
    version = "v%d" % number
    target = os.path.join(out_dir, HISTORY_DIR, version)
    os.makedirs(os.path.join(target, RENDERS_DIR), exist_ok=True)
    for name in COPY_FILES:
        source = os.path.join(out_dir, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(target, name))
    for name in _list_pngs(os.path.join(out_dir, RENDERS_DIR)):
        shutil.copy2(os.path.join(out_dir, RENDERS_DIR, name),
                     os.path.join(target, RENDERS_DIR, name))
    issues, stats = validate_version(target)
    created = _utc_now()
    if issues:
        print("[WARN] %s 结构自检未通过（不更新 best）:" % version)
        for issue in issues:
            print("    - " + issue)
    best = _read_json(os.path.join(out_dir, BEST_FILE))
    best_version = best.get("version") if isinstance(best, dict) else None
    best_valid = bool(best.get("valid")) if isinstance(best, dict) else False
    update_best = not issues and (
        not isinstance(best, dict) or not best_valid
        or _version_number(version) >= _version_number(best_version))
    if update_best:
        payload = _best_payload(version, target, stats, issues, out_dir, created)
        _write_json(os.path.join(out_dir, BEST_FILE), payload)
    print("[snapshot] %s -> %s/%s（renders=%d objects=%d tris=%d 结构=%s best=%s）"
          % (version, HISTORY_DIR, version, stats["renders"], stats["objects"],
             stats["tris"], "OK" if not issues else "FAIL",
             version if update_best else (best_version or "-")))
    return {
        "ok": not issues, "version": version, "dir": target, "issues": issues,
        "stats": stats, "best": version if update_best else best_version,
    }


def list_versions(out_dir):
    """打印版本表，返回行数据。"""
    out_dir = os.path.abspath(out_dir)
    best = _read_json(os.path.join(out_dir, BEST_FILE))
    best_version = best.get("version") if isinstance(best, dict) else None
    rows = []
    print("=== snapshot: %s ===" % out_dir)
    print("%-6s %-8s %-7s %-8s %-8s %s" % ("版本", "渲染图", "对象数", "三角面", "结构", "best"))
    for number, name, path in version_dirs(out_dir):
        issues, stats = validate_version(path)
        rows.append({"version": name, "renders": stats["renders"],
                     "objects": stats["objects"], "tris": stats["tris"],
                     "valid": not issues, "best": name == best_version,
                     "issues": issues})
        print("%-8s %-10d %-9d %-10d %-10s %s"
              % (name, stats["renders"], stats["objects"], stats["tris"],
                 "OK" if not issues else "FAIL",
                 "<= best" if name == best_version else ""))
        for issue in issues:
            print("        ! " + issue)
    if not rows:
        print("（还没有历史版本，运行 snapshot.py --out <目录> 创建 v1）")
    if isinstance(best, dict):
        print("[best] %s（promoted_at=%s）" % (best.get("version", "?"),
                                              best.get("promoted_at", "?")))
    return rows


def promote(out_dir, version):
    """把指定版本设为 best（必须结构自检通过）。"""
    out_dir = os.path.abspath(out_dir)
    name = canonical_version(version)
    if name is None:
        print("[ERROR] 非法版本号: %r（示例: v2）" % (version,))
        return 1
    target = snapshot_path(out_dir, name)
    issues, stats = validate_version(target)
    if issues:
        print("[ERROR] %s 结构自检未通过，拒绝 promote:" % name)
        for issue in issues:
            print("    - " + issue)
        return 1
    report = _read_json(os.path.join(target, REPORT_FILE)) or {}
    created = report.get("generated_at") or _utc_now()
    payload = _best_payload(name, target, stats, issues, out_dir, created)
    _write_json(os.path.join(out_dir, BEST_FILE), payload)
    print("[promote] best = %s（renders=%d objects=%d tris=%d）"
          % (name, stats["renders"], stats["objects"], stats["tris"]))
    return 0


def rollback(out_dir, version=None):
    """把 best（或指定版本）的 model.py / renders/ / report.json 还原到产物目录。

    注意：只还原可重新生成的中间产物，不还原 exports/（历史导出包可能已过期）；
    回滚后应重跑 --stage full 重新导出。
    """
    out_dir = os.path.abspath(out_dir)
    best = _read_json(os.path.join(out_dir, BEST_FILE))
    if version is None:
        if not isinstance(best, dict) or not best.get("version"):
            print("[ERROR] 没有 best.json，无法确定回滚目标；用 --rollback vN 指定版本")
            return 1
        name = canonical_version(best.get("version"))
    else:
        name = canonical_version(version)
    if name is None:
        print("[ERROR] 非法版本号: %r" % (version,))
        return 1
    target = snapshot_path(out_dir, name)
    issues, stats = validate_version(target)
    if issues:
        print("[ERROR] %s 结构自检未通过，拒绝回滚:" % name)
        for issue in issues:
            print("    - " + issue)
        return 1
    out_renders = os.path.join(out_dir, RENDERS_DIR)
    os.makedirs(out_renders, exist_ok=True)
    for name_png in _list_pngs(out_renders):
        os.remove(os.path.join(out_renders, name_png))
    for name_file in COPY_FILES:
        source = os.path.join(target, name_file)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(out_dir, name_file))
    for name_png in _list_pngs(os.path.join(target, RENDERS_DIR)):
        shutil.copy2(os.path.join(target, RENDERS_DIR, name_png),
                     os.path.join(out_renders, name_png))
    if isinstance(best, dict) and canonical_version(best.get("version")) == name:
        pass
    else:
        report = _read_json(os.path.join(target, REPORT_FILE)) or {}
        payload = _best_payload(name, target, stats, issues, out_dir,
                                report.get("generated_at") or _utc_now())
        _write_json(os.path.join(out_dir, BEST_FILE), payload)
    print("[rollback] %s <- %s/%s（model.py / renders / report.json 已还原；"
          "exports/ 不还原，回滚后需重跑 --stage full 重新导出）"
          % (out_dir, HISTORY_DIR, name))
    return 0


def validate_best(out_dir):
    """给 check_output.py 的结构一致性检查：返回 issues [{level, code, message}]。"""
    out_dir = os.path.abspath(out_dir)
    best_path = os.path.join(out_dir, BEST_FILE)
    history = os.path.join(out_dir, HISTORY_DIR)
    if not os.path.isfile(best_path):
        if os.path.isdir(history):
            return [{"level": "WARN", "code": "SNAP001",
                     "message": "存在 history/ 但缺少 best.json（快照结构不完整）"}]
        return []
    best = _read_json(best_path)
    if not isinstance(best, dict):
        return [{"level": "WARN", "code": "SNAP001",
                 "message": "best.json 无法解析"}]
    issues = []
    if best.get("schema") != SNAPSHOT_SCHEMA:
        issues.append({"level": "WARN", "code": "SNAP002",
                       "message": "best.json schema 版本不是 %d" % SNAPSHOT_SCHEMA})
    name = canonical_version(best.get("version"))
    if name is None:
        return issues + [{"level": "WARN", "code": "SNAP001",
                          "message": "best.json 缺少合法 version"}]
    target = snapshot_path(out_dir, name)
    dir_issues, stats = validate_version(target)
    for message in dir_issues:
        issues.append({"level": "WARN", "code": "SNAP003",
                       "message": "best 版本 %s: %s" % (name, message)})
    if best.get("dir") != "%s/%s" % (HISTORY_DIR, name):
        issues.append({"level": "WARN", "code": "SNAP002",
                       "message": "best.json 的 dir 与 version 不一致"})
    if isinstance(best.get("renders"), int) and best["renders"] != stats["renders"]:
        issues.append({"level": "WARN", "code": "SNAP004",
                       "message": "best.json 记录 renders=%d 与版本目录实际 %d 不一致"
                                  % (best["renders"], stats["renders"])})
    if not best.get("valid", False):
        issues.append({"level": "WARN", "code": "SNAP005",
                       "message": "best.json 标记 valid=false（当前最佳版本未通过自检）"})
    return issues


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

_GOOD_MODEL = (
    "# -*- coding: utf-8 -*-\n"
    "import os\nimport sys\n"
    "sys.path.insert(0, os.environ['BLENDER_KIT_DIR'])\n"
    "import blender_kit\n"
    "print('model')\n"
)


def _write_test_out(root):
    os.makedirs(os.path.join(root, RENDERS_DIR), exist_ok=True)
    with open(os.path.join(root, MODEL_FILE), "w", encoding="utf-8") as handle:
        handle.write(_GOOD_MODEL)
    with open(os.path.join(root, BRIEF_FILE), "w", encoding="utf-8") as handle:
        handle.write("# brief\n\n## 迭代记录\n")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with open(os.path.join(root, RENDERS_DIR, "view-front.png"), "wb") as handle:
        handle.write(png)
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "object_count": 2,
        "total_tris": 42,
        "renders": [{"path": "renders/view-front.png", "std": 20.0,
                     "black_ratio": 0.0, "mean": 120.0}],
        "exports": {"blend": {"path": "exports/model.blend", "bytes": 1024},
                    "glb": {"path": "exports/model.glb", "bytes": 256}},
    }
    with open(os.path.join(root, REPORT_FILE), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


def selftest():
    failures = []

    def expect(name, condition):
        if condition:
            print("[PASS] selftest: " + name)
        else:
            print("[FAIL] selftest: " + name)
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="bm-snapshot-selftest-") as tmp:
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        _write_test_out(out)

        first = create_snapshot(out)
        expect("v1 创建成功", first["ok"] and first["version"] == "v1")
        best = _read_json(os.path.join(out, BEST_FILE))
        expect("v1 自动成为 best", isinstance(best, dict) and best["version"] == "v1")
        expect("best.json 记录 renders=1", best.get("renders") == 1)

        # 修改 model.py 后创建 v2 -> best 前进到 v2
        with open(os.path.join(out, MODEL_FILE), "a", encoding="utf-8") as handle:
            handle.write("# iteration 2\n")
        second = create_snapshot(out)
        expect("v2 创建成功", second["ok"] and second["version"] == "v2")
        best = _read_json(os.path.join(out, BEST_FILE))
        expect("v2 成为新 best", best["version"] == "v2")
        expect("history 下有两个版本", len(version_dirs(out)) == 2)

        # promote v1 -> best 回到 v1
        expect("promote v1 成功", promote(out, "v1") == 0)
        best = _read_json(os.path.join(out, BEST_FILE))
        expect("promote 后 best=v1", best["version"] == "v1")

        # rollback -> out 的 model.py 还原成 v1 内容（无 "# iteration 2"）
        with open(os.path.join(out, MODEL_FILE), encoding="utf-8") as handle:
            before = handle.read()
        if rollback(out, None) == 0:
            with open(os.path.join(out, MODEL_FILE), encoding="utf-8") as handle:
                restored = handle.read()
            expect("rollback 还原 model.py", "# iteration 2" not in restored)
            expect("rollback 前内容确实不同", before != restored)
        else:
            expect("rollback 返回 0", False)

        # 破坏 v2 的 report.renders 数量 -> promote 必须失败
        broken_dir = os.path.join(out, HISTORY_DIR, "v2")
        broken_report = _read_json(os.path.join(broken_dir, REPORT_FILE))
        broken_report["renders"] = broken_report["renders"] * 2
        with open(os.path.join(broken_dir, REPORT_FILE), "w", encoding="utf-8") as handle:
            json.dump(broken_report, handle, ensure_ascii=False, indent=2)
        expect("结构损坏版本 promote 失败", promote(out, "v2") == 1)

        # check_output 侧结构校验：破坏 best 记录后应报 WARN
        best = _read_json(os.path.join(out, BEST_FILE))
        best["renders"] = 99
        _write_json(os.path.join(out, BEST_FILE), best)
        snap_issues = validate_best(out)
        expect("validate_best 能发现 renders 不一致",
               any(issue["code"] == "SNAP004" for issue in snap_issues))

        # R9-B12：路径越界必须被结构自检拦截（绝对路径/盘符/'..'）
        expect("_inside 接受版本目录内相对路径",
               _inside(out, "renders/view-front.png"))
        expect("_inside 拦截 '..' 越界", not _inside(out, "../outside.png"))
        expect("_inside 拦截盘符相对路径", not _inside(out, "F:evil.png"))
        expect("_inside 拦截绝对路径",
               not _inside(out, os.path.abspath("renders/view-front.png")))
        trav = os.path.join(tmp, "trav")
        os.makedirs(trav)
        _write_test_out(trav)
        expect("遍历用例 v1 创建成功", create_snapshot(trav)["ok"])
        trav_report_path = os.path.join(trav, HISTORY_DIR, "v1", REPORT_FILE)
        trav_report = _read_json(trav_report_path)
        trav_report["renders"][0]["path"] = "../escape.png"
        with open(trav_report_path, "w", encoding="utf-8") as handle:
            json.dump(trav_report, handle, ensure_ascii=False, indent=2)
        expect("validate_version 拦截 renders 的 '..' 越界",
               any("越界" in issue for issue in
                   validate_version(os.path.join(trav, HISTORY_DIR, "v1"))[0]))
        trav_report["renders"][0]["path"] = "renders/view-front.png"
        trav_report["exports"]["blend"]["path"] = "../escape.blend"
        with open(trav_report_path, "w", encoding="utf-8") as handle:
            json.dump(trav_report, handle, ensure_ascii=False, indent=2)
        expect("validate_version 拦截 exports 的 '..' 越界",
               any("越界" in issue for issue in
                   validate_version(os.path.join(trav, HISTORY_DIR, "v1"))[0]))

        # R9-B11：--rollback --json 的 version 必须是实际回滚到的版本
        rollback_stdout = io.StringIO()
        with contextlib.redirect_stdout(rollback_stdout), \
                contextlib.redirect_stderr(io.StringIO()):
            rollback_code = main(["--out", out, "--rollback", "--json"])
        try:
            rollback_payload = json.loads(rollback_stdout.getvalue())
        except ValueError:
            rollback_payload = None
        expect("--rollback --json 输出纯 JSON 且 version=v1",
               rollback_code == 0 and isinstance(rollback_payload, dict)
               and rollback_payload.get("version") == "v1")

        # list 行数据
        rows = list_versions(out)
        expect("list 返回两个版本", len(rows) == 2)

        # --json 时 stdout 必须是纯 JSON（人类可读日志走 stderr）
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture), \
                contextlib.redirect_stderr(io.StringIO()):
            code = main(["--out", out, "--list", "--json"])
        try:
            payload = json.loads(stdout_capture.getvalue())
        except ValueError:
            payload = None
        expect("--list --json stdout 是纯 JSON",
               code == 0 and isinstance(payload, list) and len(payload) == 2)
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture), \
                contextlib.redirect_stderr(io.StringIO()):
            code = main(["--out", out, "--json"])
        try:
            payload = json.loads(stdout_capture.getvalue())
        except ValueError:
            payload = None
        expect("--json 创建快照 stdout 是纯 JSON",
               code == 0 and isinstance(payload, dict) and payload.get("ok") is True)

    if failures:
        print("\nSELFTEST FAILED: %d 项失败" % len(failures))
        return 1
    print("\nSELFTEST OK")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    _enable_utf8_console()
    parser = argparse.ArgumentParser(
        description="产物版本快照 history/vN + best.json（只读写输出目录，不碰 git）")
    parser.add_argument("--out", default=None, help="输出目录（含 model.py / renders / report.json）")
    parser.add_argument("--list", action="store_true", help="列出所有历史版本")
    parser.add_argument("--promote", default=None, metavar="VERSION",
                        help="把指定版本设为 best（如 v2）")
    parser.add_argument("--rollback", nargs="?", const="best", default=None,
                        metavar="VERSION",
                        help="回滚到 best 或指定版本（只还原 model.py/renders/report.json，"
                             "不还原 exports，回滚后需重跑 --stage full）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--selftest", action="store_true", help="只运行自测")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.out:
        parser.error("必须提供 --out <输出目录>（或使用 --selftest）")
    out_dir = os.path.abspath(args.out)

    # --json 时 stdout 必须是纯 JSON：人类可读日志一律走 stderr。
    real_stdout = sys.stdout
    if args.json:
        sys.stdout = sys.stderr
    try:
        if args.list:
            rows = list_versions(out_dir)
            payload, code = rows, 0
        elif args.promote is not None:
            code = promote(out_dir, args.promote)
            payload = {"ok": code == 0, "action": "promote",
                       "version": canonical_version(args.promote),
                       "exit_code": code}
        elif args.rollback is not None:
            version = None if args.rollback == "best" else args.rollback
            # R9-B11：--rollback --json 的 version 必须是实际回滚到的版本，
            # 旧实现用 canonical_version("best") 得到 None，成功却报 version:null。
            if version is None:
                best = _read_json(os.path.join(out_dir, BEST_FILE))
                reported = (canonical_version(best.get("version"))
                            if isinstance(best, dict) else None)
            else:
                reported = canonical_version(version)
            code = rollback(out_dir, version)
            payload = {"ok": code == 0, "action": "rollback",
                       "version": reported,
                       "exit_code": code}
        else:
            result = create_snapshot(out_dir)
            code = 0 if result.get("ok") else 1
            payload = result
    finally:
        sys.stdout = real_stdout
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
