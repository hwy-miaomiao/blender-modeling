# -*- coding: utf-8 -*-
"""视觉指标：从 renders/*.png 计算可量化构图指标（Pillow 为可选依赖）。

用法：
    python scripts/vision_metrics.py --out <输出目录>
    python scripts/vision_metrics.py --out <输出目录> --write    # 回写 report.json 的 vision 字段
    python scripts/vision_metrics.py --out <输出目录> --json
    python scripts/vision_metrics.py --selftest                  # 无需 Pillow 也能跑

每个视角的指标：
- subject_ratio    前景主体像素占比
- margins          主体外接框到画面四边的留白（占边长比例 0-1，left/right/top/bottom）
- bottom_gap       主体底部到画面底边的留白（着地间隙的图像代理指标）
- background_ratio 背景像素占比
- luminance        亮度分布 mean / std / p10 / p50 / p90

算法（纯标准库实现，见 analyze_pixels）：缩小到 WORK_SIZE，从画面的四个角块
做「梯度受限 flood fill」——背景是平滑渐变（局部色差小、梯度低），主体边缘是
陡峭跳变（梯度高），因此 flood 不会跨过主体轮廓；未被 flood 到的最大连通域即主体。
阴影/地面渐变会被当作背景，避免「深色阴影把主体占比算大」。

阈值常量（check_output.py 视觉闸门与 AGENTS 第 11 / 14 节使用，修改必须同步文档）：
- SUBJECT_RATIO_MIN / SUBJECT_RATIO_MAX：主体像素占比合理区间（默认 3% ~ 90%）
- MARGIN_MIN：四边留白下限（默认 1%，低于即疑似主体被裁切）
- BOTTOM_GAP_WARN / BOTTOM_GAP_MAX：底部留白上限（默认 45% WARN / 55% ERROR，疑似悬空）
- MEAN_MIN / MEAN_MAX / STD_MIN：亮度合理性（默认 20~235、std ≥ 8，仅 WARN）

Pillow 缺失时所有计算函数返回 None，调用方应 SKIP 而不是报错（与 contact_sheet.py
的可选依赖约定一致）。退出码：0 = 无 ERROR 级视觉问题（或 SKIP），1 = 有 ERROR。

「无法判定」不等于「通过」：renders/ 下明明有 PNG、Pillow 也可用，却一张都解不出来
时记 VISION008 ERROR（文件损坏 / 伪造），闸门不能默认放行。

--write 用「临时文件 + os.replace」原子覆盖 report.json（进程中断不会留下半个文件）。
手工给存量项目补写时 vision 会带 backfill=true / backfilled_at 标记，check_output.py
据此识别「存量迁移」，只校验图片引用、不强制新 5 列迭代记录。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile

VISION_VERSION = 1

# ---- 分析参数 -------------------------------------------------------------
WORK_SIZE = 256          # 分析前把图缩到的最长边（越小越快，256 足够判断构图）
FLOOD_MAX_GRAD = 18      # flood 只穿过「局部梯度 <= 该值」的像素（L1 色差）
FLOOD_MAX_DIFF = 48      # flood 相邻像素色差上限（L1），防止跨过柔和但色差大的边界
SEED_DIVISOR = 16        # 四角种子块边长 = max(4, min(w, h) // SEED_DIVISOR)

# ---- 视觉阈值（AGENTS 第 11 节闸门表/第 14 节清单） ------------------------
SUBJECT_RATIO_MIN = 0.03
SUBJECT_RATIO_MAX = 0.90
MARGIN_MIN = 0.01
BOTTOM_GAP_WARN = 0.45
BOTTOM_GAP_MAX = 0.55
MEAN_MIN = 20.0
MEAN_MAX = 235.0
STD_MIN = 8.0

CONTACT_SHEET_NAME = "contact-sheet.png"


def _enable_utf8_console():
    """让脚本在 Windows 上以 UTF-8 输出中文（避免 GBK 控制台把中文写成乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_PIL_STATE = []  # 缓存 Pillow 探测结果，避免重复 import 开销


def pillow_available():
    """Pillow 是否可用（可选依赖）。"""
    if _PIL_STATE:
        return _PIL_STATE[0]
    try:
        from PIL import Image  # noqa: F401
        _PIL_STATE.append(True)
    except Exception:
        _PIL_STATE.append(False)
    return _PIL_STATE[0]


# ---------------------------------------------------------------------------
# 纯函数：像素列表 -> 指标（自测与单测直接调它，不需要 Pillow）
# ---------------------------------------------------------------------------

def _luminance(pixel):
    r, g, b = pixel[0], pixel[1], pixel[2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _color_dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def gradient_map(width, height, pixels):
    """每像素到右/下邻居的最大 L1 色差（局部梯度）。"""
    grad = [0] * (width * height)
    for y in range(height):
        row = y * width
        for x in range(width):
            idx = row + x
            here = pixels[idx]
            best = 0
            if x + 1 < width:
                d = _color_dist(here, pixels[idx + 1])
                if d > best:
                    best = d
            if y + 1 < height:
                d = _color_dist(here, pixels[idx + width])
                if d > best:
                    best = d
            grad[idx] = best
    return grad


def flood_background(width, height, pixels, grad=None):
    """从四角种子块出发 flood 背景，返回 bytearray(1=背景)。"""
    if grad is None:
        grad = gradient_map(width, height, pixels)
    bg = bytearray(width * height)
    block = max(4, min(width, height) // SEED_DIVISOR)
    stack = []
    for ox, oy in ((0, 0), (width - block, 0), (0, height - block),
                   (width - block, height - block)):
        for y in range(oy, oy + block):
            for x in range(ox, ox + block):
                idx = y * width + x
                if not bg[idx]:
                    bg[idx] = 1
                    stack.append(idx)
    while stack:
        cur = stack.pop()
        x = cur % width
        y = cur // width
        here = pixels[cur]
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                nidx = ny * width + nx
                if bg[nidx] or grad[nidx] > FLOOD_MAX_GRAD:
                    continue
                if _color_dist(here, pixels[nidx]) <= FLOOD_MAX_DIFF:
                    bg[nidx] = 1
                    stack.append(nidx)
    return bg


def largest_component(mask, width, height):
    """返回最大 4 连通域的像素索引列表（mask 为 bytearray，1=前景）。"""
    seen = bytearray(width * height)
    best = []
    best_size = 0
    total = width * height
    for start in range(total):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        comp = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            x = cur % width
            y = cur // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    nidx = ny * width + nx
                    if mask[nidx] and not seen[nidx]:
                        seen[nidx] = 1
                        stack.append(nidx)
        if len(comp) > best_size:
            best_size = len(comp)
            best = comp
    return best


def _percentile(sorted_values, ratio):
    if not sorted_values:
        return 0.0
    index = int(round(ratio * (len(sorted_values) - 1)))
    return float(sorted_values[max(0, min(index, len(sorted_values) - 1))])


def analyze_pixels(width, height, pixels):
    """纯函数：像素列表 -> 视觉指标 dict。pixels 为 [(r,g,b), ...] 行优先。"""
    if width <= 1 or height <= 1 or len(pixels) != width * height:
        raise ValueError("像素数据与尺寸不匹配: %dx%d / %d" % (width, height, len(pixels)))
    grad = gradient_map(width, height, pixels)
    bg = flood_background(width, height, pixels, grad)
    total = width * height
    bg_count = sum(bg)
    fg_mask = bytearray(1 - bg[i] for i in range(total))
    comp = largest_component(fg_mask, width, height)
    if comp:
        xs = [idx % width for idx in comp]
        ys = [idx // width for idx in comp]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        denom_x = float(max(1, width - 1))
        denom_y = float(max(1, height - 1))
        margins = {
            "left": min_x / denom_x,
            "right": (width - 1 - max_x) / denom_x,
            "top": min_y / denom_y,
            "bottom": (height - 1 - max_y) / denom_y,
        }
        bbox_px = [min_x, min_y, max_x, max_y]
    else:
        margins = {"left": 1.0, "right": 1.0, "top": 1.0, "bottom": 1.0}
        bbox_px = [0, 0, 0, 0]

    lums = sorted(_luminance(p) for p in pixels)
    mean = sum(lums) / float(total)
    variance = sum((v - mean) ** 2 for v in lums) / float(total)
    luminance = {
        "mean": mean,
        "std": variance ** 0.5,
        "p10": _percentile(lums, 0.10),
        "p50": _percentile(lums, 0.50),
        "p90": _percentile(lums, 0.90),
    }
    return {
        "width": width,
        "height": height,
        "subject_ratio": len(comp) / float(total),
        "background_ratio": bg_count / float(total),
        "margins": margins,
        "bottom_gap": margins["bottom"],
        "luminance": luminance,
        "subject_bbox_px": bbox_px,
    }


# ---------------------------------------------------------------------------
# 图像加载与阈值判定
# ---------------------------------------------------------------------------

def load_pixels(path, work_size=WORK_SIZE):
    """用 Pillow 读取 PNG 并缩到 work_size；Pillow 缺失或解码失败返回 None。"""
    if not pillow_available():
        return None
    try:
        from PIL import Image
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            if max(rgb.size) > work_size:
                rgb.thumbnail((work_size, work_size), Image.LANCZOS)
            width, height = rgb.size
            pixels = list(rgb.getdata())
    except Exception:
        return None
    return width, height, pixels


def analyze_image(path):
    """读取单张渲染图并计算指标；不可用时返回 None（调用方 SKIP）。"""
    loaded = load_pixels(path)
    if loaded is None:
        return None
    width, height, pixels = loaded
    try:
        metrics = analyze_pixels(width, height, pixels)
    except ValueError:
        return None
    metrics["path"] = str(path).replace("\\", "/")
    metrics["file"] = os.path.basename(str(path))
    return metrics


def gate_view(view):
    """按阈值判定单个视角，返回 issues: [{level, code, metric, message}]。"""
    issues = []
    ratio = view.get("subject_ratio")
    if isinstance(ratio, (int, float)):
        if ratio < SUBJECT_RATIO_MIN:
            issues.append({
                "level": "ERROR", "code": "VISION001", "metric": "subject_ratio",
                "message": "主体像素占比过小（%.1f%% < %.0f%%），疑似空场景/取景过远"
                           % (ratio * 100, SUBJECT_RATIO_MIN * 100),
            })
        elif ratio > SUBJECT_RATIO_MAX:
            issues.append({
                "level": "ERROR", "code": "VISION002", "metric": "subject_ratio",
                "message": "主体像素占比过大（%.1f%% > %.0f%%），疑似穿模/贴脸取景"
                           % (ratio * 100, SUBJECT_RATIO_MAX * 100),
            })
    margins = view.get("margins") or {}
    for side in ("left", "right", "top", "bottom"):
        value = margins.get(side)
        if isinstance(value, (int, float)) and value < MARGIN_MIN:
            issues.append({
                "level": "ERROR", "code": "VISION003", "metric": "margins." + side,
                "message": "%s 侧留白不足（%.1f%% < %.0f%%），主体可能被裁切"
                           % (side, value * 100, MARGIN_MIN * 100),
            })
    bottom = margins.get("bottom")
    if isinstance(bottom, (int, float)):
        if bottom > BOTTOM_GAP_MAX:
            issues.append({
                "level": "ERROR", "code": "VISION004", "metric": "bottom_gap",
                "message": "底部留白过大（%.1f%% > %.0f%%），疑似悬空或构图偏上"
                           % (bottom * 100, BOTTOM_GAP_MAX * 100),
            })
        elif bottom > BOTTOM_GAP_WARN:
            issues.append({
                "level": "WARN", "code": "VISION005", "metric": "bottom_gap",
                "message": "底部留白偏大（%.1f%% > %.0f%%），检查是否悬空"
                           % (bottom * 100, BOTTOM_GAP_WARN * 100),
            })
    lum = view.get("luminance") or {}
    mean = lum.get("mean")
    std = lum.get("std")
    if isinstance(mean, (int, float)) and not (MEAN_MIN <= mean <= MEAN_MAX):
        issues.append({
            "level": "WARN", "code": "VISION006", "metric": "luminance.mean",
            "message": "画面亮度异常（mean=%.1f，合理区间 %.0f~%.0f）"
                       % (mean, MEAN_MIN, MEAN_MAX),
        })
    if isinstance(std, (int, float)) and std < STD_MIN:
        issues.append({
            "level": "WARN", "code": "VISION007", "metric": "luminance.std",
            "message": "画面对比度偏低（std=%.1f < %.0f）" % (std, STD_MIN),
        })
    return issues


def _totals(views):
    if not views:
        return {
            "view_count": 0, "subject_ratio_mean": 0.0, "margin_min": 1.0,
            "bottom_gap_max": 1.0, "background_ratio_mean": 0.0,
            "luminance_mean": 0.0, "luminance_std_min": 0.0,
        }
    count = float(len(views))
    subject = [v["subject_ratio"] for v in views]
    margin_min = min(
        min(v["margins"][side] for side in ("left", "right", "top", "bottom"))
        for v in views)
    bottom = [v["bottom_gap"] for v in views]
    background = [v["background_ratio"] for v in views]
    lum_means = [v["luminance"]["mean"] for v in views]
    lum_stds = [v["luminance"]["std"] for v in views]
    return {
        "view_count": len(views),
        "subject_ratio_mean": sum(subject) / count,
        "margin_min": margin_min,
        "bottom_gap_max": max(bottom),
        "background_ratio_mean": sum(background) / count,
        "luminance_mean": sum(lum_means) / count,
        "luminance_std_min": min(lum_stds),
    }


def analyze_out(out_dir):
    """分析输出目录 renders/*.png，返回 {version, generated_at, views, totals, ok, issues}。"""
    renders_dir = os.path.join(out_dir, "renders")
    result = {
        "version": VISION_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "views": [],
        "totals": _totals([]),
        "ok": True,
        "issues": [],
    }
    if not os.path.isdir(renders_dir):
        result["ok"] = False
        result["issues"].append({
            "level": "ERROR", "code": "VISION000", "metric": "renders",
            "file": "", "message": "缺少 renders/ 目录: %s" % renders_dir,
        })
        return result
    names = [name for name in sorted(os.listdir(renders_dir))
             if name.lower().endswith(".png") and name != CONTACT_SHEET_NAME]
    skipped = []
    for name in names:
        metrics = analyze_image(os.path.join(renders_dir, name))
        if metrics is None:
            skipped.append(name)
            continue
        metrics["file"] = name
        metrics["path"] = "renders/" + name
        result["views"].append(metrics)
        for issue in gate_view(metrics):
            issue = dict(issue)
            issue["file"] = name
            result["issues"].append(issue)
    # 有 PNG 却一张都解不出来：无法判定，必须报错而不是 SKIP（Pillow 缺失时
    # 由调用方提前 SKIP，这里只在「有 Pillow 但解码全失败」时判定）。
    if names and not result["views"] and pillow_available():
        result["issues"].append({
            "level": "ERROR", "code": "VISION008", "metric": "renders",
            "file": "",
            "message": "renders/ 下的 %d 张 PNG 全部无法解码（文件损坏或伪造，"
                       "拒绝 SKIP）" % len(names),
        })
    result["totals"] = _totals(result["views"])
    result["ok"] = not any(item["level"] == "ERROR" for item in result["issues"])
    if not names:
        result["ok"] = False
        result["issues"].append({
            "level": "ERROR", "code": "VISION000", "metric": "renders",
            "file": "", "message": "renders/ 下没有可分析的 PNG",
        })
    if skipped:
        result["skipped"] = skipped
    return result


# ---------------------------------------------------------------------------
# 回写 report.json
# ---------------------------------------------------------------------------

def _write_report(report_path, report):
    """原子覆盖 report.json：先写同目录 .tmp，再 os.replace（失败清理临时文件）。"""
    tmp_path = report_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, report_path)
    except OSError:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def attach_to_report(out_dir, backfill=True):
    """把视觉指标写入 report.json 的 vision 字段；返回摘要 dict。

    backfill=True（默认，CLI --write 使用）：给存量项目补写，vision 带
    backfill=true / backfilled_at 标记，check_output 会放宽迭代记录格式校验。
    backfill=False（run_blender --stage full 自动写入的新产物）：不写标记。
    """
    if not pillow_available():
        return {"attached": False, "reason": "Pillow 未安装（可选依赖），视觉指标 SKIP"}
    report_path = os.path.join(out_dir, "report.json")
    if not os.path.isfile(report_path):
        return {"attached": False, "reason": "report.json 不存在: %s" % report_path}
    try:
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as exc:
        return {"attached": False, "reason": "report.json 无法解析: %r" % (exc,)}
    if not isinstance(report, dict):
        return {"attached": False, "reason": "report.json 顶层不是对象"}
    summary = analyze_out(out_dir)
    if backfill:
        summary["backfill"] = True
        summary["backfilled_at"] = datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report["vision"] = summary
    try:
        _write_report(report_path, report)
    except OSError as exc:
        return {"attached": False, "reason": "report.json 写入失败: %r" % (exc,)}
    return {
        "attached": True,
        "version": summary["version"],
        "views": len(summary["views"]),
        "ok": summary["ok"],
        "errors": sum(1 for item in summary["issues"] if item["level"] == "ERROR"),
        "warnings": sum(1 for item in summary["issues"] if item["level"] == "WARN"),
        "skipped": summary.get("skipped", []),
    }


# ---------------------------------------------------------------------------
# 自测（无需 Pillow）
# ---------------------------------------------------------------------------

def _flat_pixels(width, height):
    pixels = []
    for y in range(height):
        top = 30.0 + 120.0 * (y / float(max(1, height - 1)))
        for _x in range(width):
            value = int(top)
            pixels.append((value, value, value))
    return pixels


def _paint_square(width, pixels, x0, y0, x1, y1, color=20):
    for y in range(y0, y1):
        for x in range(x0, x1):
            pixels[y * width + x] = (color, color, color)


def selftest():
    failures = []

    def expect(name, condition):
        if condition:
            print("[PASS] selftest: " + name)
        else:
            print("[FAIL] selftest: " + name)
            failures.append(name)

    expect("Pillow 可选依赖可探测", isinstance(pillow_available(), bool))

    # 1) 平滑渐变背景 + 居中深色方块：应识别为主体，四边留白充足
    width = height = 64
    pixels = _flat_pixels(width, height)
    _paint_square(width, pixels, 20, 20, 44, 44)
    metrics = analyze_pixels(width, height, pixels)
    expect("主体占比落在合理区间",
           SUBJECT_RATIO_MIN < metrics["subject_ratio"] < 0.5)
    expect("背景占比大于 0.5", metrics["background_ratio"] > 0.5)
    expect("四边留白均 >= MARGIN_MIN",
           all(metrics["margins"][side] >= MARGIN_MIN
               for side in ("left", "right", "top", "bottom")))
    expect("居中主体无裁切 issue",
           not any(item["code"] == "VISION003" for item in gate_view(metrics)))

    # 2) 贴左边的主体：left 留白为 0 -> 必须报裁切 ERROR
    clipped = _flat_pixels(width, height)
    _paint_square(width, clipped, 0, 20, 24, 44)
    clipped_metrics = analyze_pixels(width, height, clipped)
    clipped_issues = gate_view(clipped_metrics)
    expect("贴边主体报 VISION003 裁切 ERROR",
           any(item["code"] == "VISION003" for item in clipped_issues))

    # 3) 只有渐变背景（空场景）：主体占比过小 -> VISION001
    empty_metrics = analyze_pixels(width, height, _flat_pixels(width, height))
    expect("空场景主体占比低于下限",
           empty_metrics["subject_ratio"] < SUBJECT_RATIO_MIN)
    expect("空场景报 VISION001",
           any(item["code"] == "VISION001" for item in gate_view(empty_metrics)))

    # 4) 悬空/构图偏上：底部留白过大 -> VISION004 ERROR
    floating = dict(metrics)
    floating["margins"] = {"left": 0.2, "right": 0.2, "top": 0.05, "bottom": 0.7}
    expect("底部留白过大报 VISION004",
           any(item["code"] == "VISION004" for item in gate_view(floating)))

    # 5) 过暗画面 -> 亮度 WARN
    dark = dict(metrics)
    dark["luminance"] = {"mean": 5.0, "std": 2.0, "p10": 1.0, "p50": 4.0, "p90": 9.0}
    codes = [item["code"] for item in gate_view(dark)]
    expect("过暗画面报亮度/对比度 WARN",
           "VISION006" in codes and "VISION007" in codes)

    # 6) totals 聚合
    merged = _totals([metrics, clipped_metrics])
    expect("totals 视角数正确", merged["view_count"] == 2)
    expect("totals 主体均值在 0-1", 0.0 <= merged["subject_ratio_mean"] <= 1.0)

    # 7) Pillow 可用时做一次真实 PNG 往返
    if pillow_available():
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="bm-vision-selftest-") as tmp:
            path = os.path.join(tmp, "view-front.png")
            image = Image.new("RGB", (64, 64))
            for y in range(64):
                for x in range(64):
                    image.putpixel((x, y), (40 + y, 40 + y, 40 + y))
            for y in range(20, 44):
                for x in range(20, 44):
                    image.putpixel((x, y), (10, 10, 10))
            image.save(path)
            loaded = analyze_image(path)
            expect("Pillow 读取真实 PNG 并计算指标",
                   loaded is not None and loaded["width"] > 1)
            if loaded is not None:
                expect("真实 PNG 的主体占比在合理区间",
                       loaded["subject_ratio"] > 0.05)
    else:
        print("[SKIP] selftest: 未安装 Pillow，跳过真实 PNG 往返（可选依赖）")

    # 8) 渲染图全部无法解码 -> VISION008（Pillow 可用才能区分「坏图」与「没装 Pillow」）
    if pillow_available():
        with tempfile.TemporaryDirectory(prefix="bm-vision-selftest-") as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            with open(os.path.join(renders, "view-front.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
            bad = analyze_out(tmp)
            expect("渲染图全部无法解码时报 VISION008",
                   not bad["ok"]
                   and any(item["code"] == "VISION008" for item in bad["issues"]))
    else:
        print("[SKIP] selftest: 未安装 Pillow，跳过 VISION008 用例（可选依赖）")

    # 9) report.json 原子写：成功后不残留 .tmp，内容可解析
    with tempfile.TemporaryDirectory(prefix="bm-vision-selftest-") as tmp:
        report_path = os.path.join(tmp, "report.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write('{"old": true}\n')
        _write_report(report_path, {"new": True})
        with open(report_path, "r", encoding="utf-8") as handle:
            written = json.load(handle)
        expect("report 原子写成功且无 .tmp 残留",
               written.get("new") is True
               and not os.path.exists(report_path + ".tmp"))

    # 10) --write 补写标记 backfill（存量迁移用；新产物不写）
    if pillow_available():
        with tempfile.TemporaryDirectory(prefix="bm-vision-selftest-") as tmp:
            renders = os.path.join(tmp, "renders")
            os.makedirs(renders)
            with open(os.path.join(renders, "view-front.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
            with open(os.path.join(tmp, "report.json"), "w", encoding="utf-8") as handle:
                json.dump({"object_count": 1}, handle)
            attached = attach_to_report(tmp, backfill=True)
            with open(os.path.join(tmp, "report.json"), "r", encoding="utf-8") as handle:
                report = json.load(handle)
            expect("补写 vision 带 backfill 标记",
                   attached.get("attached") is True
                   and report["vision"].get("backfill") is True
                   and bool(report["vision"].get("backfilled_at")))
            attach_to_report(tmp, backfill=False)
            with open(os.path.join(tmp, "report.json"), "r", encoding="utf-8") as handle:
                report_new = json.load(handle)
            expect("新产物写入不带 backfill 标记",
                   "backfill" not in report_new["vision"])
    else:
        print("[SKIP] selftest: 未安装 Pillow，跳过 backfill 标记用例（可选依赖）")

    if failures:
        print("\nSELFTEST FAILED: %d 项失败" % len(failures))
        return 1
    print("\nSELFTEST OK")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_analysis(payload):
    print("=== vision_metrics: %s ===" % payload["out"])
    if payload.get("skipped"):
        print("[SKIP] %d 张渲染图无法解码（不计入指标）" % len(payload["skipped"]))
    for view in payload["views"]:
        margins = view["margins"]
        lum = view["luminance"]
        print("[PASS] %s: 主体=%.1f%% 留白 L=%.1f%% R=%.1f%% T=%.1f%% B=%.1f%% 亮度 mean=%.0f std=%.0f"
              % (view["file"], view["subject_ratio"] * 100,
                 margins["left"] * 100, margins["right"] * 100,
                 margins["top"] * 100, margins["bottom"] * 100,
                 lum["mean"], lum["std"]))
    for issue in payload["issues"]:
        print("[%s] %s (%s) %s" % (issue["level"], issue.get("file") or "-",
                                   issue["code"], issue["message"]))
    totals = payload["totals"]
    print("[INFO] 汇总: 视角=%d 主体均值=%.1f%% 最小留白=%.1f%% 最大底部留白=%.1f%% 亮度均值=%.0f"
          % (totals["view_count"], totals["subject_ratio_mean"] * 100,
             totals["margin_min"] * 100, totals["bottom_gap_max"] * 100,
             totals["luminance_mean"]))


def main(argv=None):
    _enable_utf8_console()
    parser = argparse.ArgumentParser(
        description="渲染图视觉指标（主体占比 / 四边留白 / 底部留白 / 亮度分布）")
    parser.add_argument("--out", default=None, help="输出目录（含 renders/ 与 report.json）")
    parser.add_argument("--write", action="store_true",
                        help="把指标写入 report.json 的 vision 字段（临时文件 + os.replace "
                             "原子覆盖；手工补写存量项目会标记 backfill）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--selftest", action="store_true", help="只运行自测（无需 Pillow）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.out:
        parser.error("必须提供 --out <输出目录>（或使用 --selftest）")

    out_dir = os.path.abspath(args.out)
    if not pillow_available():
        if args.json:
            print(json.dumps({"out": out_dir, "skipped": True,
                              "reason": "Pillow 未安装（可选依赖）"},
                             ensure_ascii=False, indent=2))
        else:
            print("[SKIP] Pillow 未安装（可选依赖），视觉指标跳过。")
        return 0
    payload = analyze_out(out_dir)
    payload["out"] = out_dir
    attached = None
    if args.write:
        attached = attach_to_report(out_dir, backfill=True)
        payload["attached"] = attached
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_analysis(payload)
        if attached is not None:
            print("[%s] report.vision 回写: %s"
                  % ("PASS" if attached.get("attached") else "WARN",
                     attached.get("reason") or "views=%d" % attached.get("views", 0)))
    return 1 if any(item["level"] == "ERROR" for item in payload["issues"]) else 0


if __name__ == "__main__":
    sys.exit(main())
