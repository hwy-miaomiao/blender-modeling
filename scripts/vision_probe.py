# -*- coding: utf-8 -*-
"""纯标准库视觉探针：不装 Pillow 也能机器验证「渲染图真的被看过/能解码/不是空白」。

背景（竞品融合第 2 批）：Amagine3D 的 commit gate 与 doctor --vision 说明，
「代理看过渲染图」必须变成机器可验证的证据；而 check_output 的视觉闸门依赖
Pillow（可选依赖），Pillow 缺失时只能 SKIP。本脚本用自实现的 PNG 解码器补上
这层证据：文件存在 + 结构完整（CRC/IEND，能发现截断/伪造）+ 像素可解压 +
尺寸符合预期 + 非空白（唯一色/亮度方差）+ 联系表尺寸与格数符合预期。

用法：
    python scripts/vision_probe.py --out <输出目录>      # 检查 renders/（期望尺寸取自 report.json）
    python scripts/vision_probe.py --dir <renders 目录>  # 只给渲染目录
    python scripts/vision_probe.py --file view-front.png  # 单图（可重复）
    python scripts/vision_probe.py --out <输出目录> --sheet renders/contact-sheet.png
    python scripts/vision_probe.py --out <输出目录> --json
    python scripts/vision_probe.py --selftest            # 自带夹具自测，不需要仓库产物

退出码：0 = 全部通过；1 = 存在失败项（--json 时判决在 {"ok": ...}）。
仅标准库；Python 3.9+；Windows/macOS/Linux 通用（不写临时文件、不依赖 PIL）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import tempfile
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CONTACT_SHEET_NAME = "contact-sheet.png"

# 判定门槛（宽松兜底：能抓「空白/纯色/坏图」，不重复 Pillow 的构图闸门）
MIN_VIEW_SIZE = 64          # 任一边 < 64px 视为占位/损坏
MIN_UNIQUE_COLORS = 8       # 唯一色（采样上限内）少于 8 = 疑似空白/纯色
MIN_LUMA_STD = 2.0          # 亮度标准差低于 2 = 疑似纯色（0-255 尺度，与 kit 口径一致）
UNIQUE_CAP = 4096           # 唯一色统计上限：超过即视为「颜色丰富」，防止大图 set 膨胀
STAT_SAMPLE_LIMIT = 800000  # 像素统计采样上限（超过则按 sqrt 步长确定性抽样）
MAX_DIM = 12000             # 单边上限，防伪造 IHDR 申请超大内存
MAX_PIXELS = 16000000       # 总像素上限（约 4000x4000）

# contact_sheet.py 的默认版式（联系表尺寸复算用；两边改动需同步）
SHEET_MARGIN = 10
SHEET_LABEL_HEIGHT = 24
SHEET_TILE_HEIGHT = 480
SHEET_COLS = 2
SHEET_MAX_TILES = 4


class PngError(Exception):
    """PNG 结构/解码错误（携带人读原因）。"""


def _enable_utf8_console():
    """让脚本在 Windows 上以 UTF-8 输出中文（避免 GBK 控制台乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# PNG 结构解析（不解压像素，速度足够做交付闸门的结构校验）
# ---------------------------------------------------------------------------

def _parse_chunks(data):
    """返回 (ihdr_payload, [(ctype, payload)], issues)；issues 非空表示结构损坏。"""
    issues = []
    if not isinstance(data, (bytes, bytearray)) or not bytes(data).startswith(PNG_MAGIC):
        return None, [], ["PNG 魔数错误（不是 PNG 文件）"]
    pos = 8
    ihdr = None
    chunks = []
    total = len(data)
    while True:
        if pos + 8 > total:
            issues.append("PNG 缺少 IEND 块（文件可能被截断）")
            break
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = bytes(data[pos + 4:pos + 8])
        end = pos + 8 + length
        if length > MAX_PIXELS * 4 + 1024:  # 异常巨大的块长度：伪造/溢出
            issues.append("PNG 块长度异常（%r 声明 %d 字节）" % (ctype, length))
            break
        if end + 4 > total:
            issues.append("PNG 数据截断（%r 块声明 %d 字节，文件不足）" % (ctype, length))
            break
        payload = bytes(data[pos + 8:end])
        crc = struct.unpack(">I", data[end:end + 4])[0]
        if zlib.crc32(ctype + payload) & 0xFFFFFFFF != crc:
            issues.append("PNG 块 CRC 校验失败（%r）" % ctype)
            break
        chunks.append((ctype, payload))
        pos = end + 4
        if ctype == b"IEND":
            break
    for index, (ctype, payload) in enumerate(chunks):
        if ctype == b"IHDR":
            if index != 0:
                issues.append("IHDR 不是首个数据块")
            if ihdr is not None:
                issues.append("PNG 出现重复 IHDR 块")
            if len(payload) != 13:
                issues.append("IHDR 长度非法: %d" % len(payload))
            ihdr = payload
    if ihdr is None:
        issues.insert(0, "PNG 缺少 IHDR 块")
    if not any(ctype == b"IDAT" for ctype, _payload in chunks):
        issues.append("PNG 缺少 IDAT 像素数据块")
    if not any(ctype == b"IEND" for ctype, _payload in chunks):
        if not any("缺少 IEND" in item for item in issues):
            issues.append("PNG 缺少 IEND 块（文件可能被截断）")
    return ihdr, chunks, issues


def structure_issues(data):
    """只做结构校验（魔数/块长度/CRC/IHDR/IDAT/IEND），返回 issue 字符串列表。

    不 inflate 像素数据，因此几毫秒就能判断截断/伪造；像素级校验见 decode_png。
    """
    _ihdr, _chunks, issues = _parse_chunks(data)
    return issues


def read_png_header(path):
    """读 PNG 头返回 (width, height)；不是合法 PNG 返回 None。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read(33)
    except OSError:
        return None
    if len(data) < 33 or not data.startswith(PNG_MAGIC):
        return None
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


# ---------------------------------------------------------------------------
# PNG 解码（纯 Python：zlib + 行过滤还原；8bit、非隔行、色型 0/2/4/6）
# ---------------------------------------------------------------------------

_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, width, height, channels):
    """还原行过滤为裸像素字节（RGB 三通道；灰度/灰度+alpha 转 RGB，RGBA 丢弃 alpha）。"""
    stride = width * channels
    need = height * (stride + 1)
    if len(raw) < need:
        raise PngError("像素数据不足（期望 %d 字节，实际 %d，疑似截断）" % (need, len(raw)))
    if len(raw) > need:
        raise PngError("像素数据多余 %d 字节（疑似拼接/伪造）" % (len(raw) - need))
    bpp = channels
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + stride])
        pos += stride
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            if prev:
                for i in range(stride):
                    row[i] = (row[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev[i] if prev else 0
                row[i] = (row[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev[i] if prev else 0
                up_left = prev[i - bpp] if (prev and i >= bpp) else 0
                row[i] = (row[i] + _paeth(left, up, up_left)) & 0xFF
        else:
            raise PngError("PNG 行过滤类型非法: %d（第 %d 行）" % (filter_type, y))
        out[y * stride:(y + 1) * stride] = row
        prev = row
    if channels == 3:
        return bytes(out)
    pixels = bytearray(width * height * 3)
    if channels == 1:
        for i, value in enumerate(out):
            pixels[i * 3] = value
            pixels[i * 3 + 1] = value
            pixels[i * 3 + 2] = value
    elif channels == 2:  # 灰度 + alpha：只取灰度
        for i in range(width * height):
            value = out[i * 2]
            pixels[i * 3] = value
            pixels[i * 3 + 1] = value
            pixels[i * 3 + 2] = value
    else:  # RGBA：丢弃 alpha
        for i in range(width * height):
            pixels[i * 3:i * 3 + 3] = out[i * 4:i * 4 + 3]
    return bytes(pixels)


def decode_png(data):
    """解码 PNG 为 {"width", "height", "pixels": RGB bytes}；失败抛 PngError。"""
    ihdr, chunks, issues = _parse_chunks(data)
    if issues:
        raise PngError("；".join(issues[:2]))
    try:
        width, height, depth, color_type, compression, filter_method, interlace = \
            struct.unpack(">IIBBBBB", ihdr)
    except struct.error as exc:
        raise PngError("IHDR 无法解析: %r" % (exc,))
    if depth != 8:
        raise PngError("不支持的 PNG 位深: %d（仅支持 8bit；Blender 默认即 8bit）" % depth)
    if color_type not in _CHANNELS:
        raise PngError("不支持的 PNG 色型: %d（支持 0/2/4/6）" % color_type)
    if compression != 0 or filter_method != 0:
        raise PngError("不支持的 PNG 压缩/过滤方法: %d/%d" % (compression, filter_method))
    if interlace != 0:
        raise PngError("不支持隔行扫描 PNG（渲染图应为非隔行）")
    if width < 1 or height < 1 or width > MAX_DIM or height > MAX_DIM:
        raise PngError("PNG 尺寸非法: %dx%d（上限 %d）" % (width, height, MAX_DIM))
    if width * height > MAX_PIXELS:
        raise PngError("PNG 像素数过大: %dx%d（上限 %d，防止伪造图撑爆内存）"
                       % (width, height, MAX_PIXELS))
    idat = b"".join(payload for ctype, payload in chunks if ctype == b"IDAT")
    try:
        raw = zlib.decompress(idat)
    except zlib.error as exc:
        raise PngError("像素数据无法解压（zlib: %s）" % exc)
    pixels = _unfilter(raw, width, height, _CHANNELS[color_type])
    return {"width": width, "height": height, "pixels": pixels}


# ---------------------------------------------------------------------------
# 指标与判定
# ---------------------------------------------------------------------------

def _luminance(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def image_stats(decoded):
    """计算非空白判定指标：唯一色数 + 亮度均值/标准差（超过上限则确定性抽样）。"""
    width = decoded["width"]
    height = decoded["height"]
    pixels = decoded["pixels"]
    total_pixels = width * height
    step = 1
    if total_pixels > STAT_SAMPLE_LIMIT:
        step = max(1, int(math.ceil(math.sqrt(total_pixels / float(STAT_SAMPLE_LIMIT)))))
    stride = width * 3
    count = 0
    total = 0.0
    total_sq = 0.0
    unique = set()
    capped = False
    for y in range(0, height, step):
        row = y * stride
        for x in range(0, width, step):
            index = row + x * 3
            r = pixels[index]
            g = pixels[index + 1]
            b = pixels[index + 2]
            lum = _luminance(r, g, b)
            count += 1
            total += lum
            total_sq += lum * lum
            if not capped:
                unique.add((r << 16) | (g << 8) | b)
                if len(unique) > UNIQUE_CAP:
                    capped = True
    mean = total / count if count else 0.0
    variance = (total_sq / count - mean * mean) if count else 0.0
    std = math.sqrt(max(0.0, variance))
    return {
        "width": width,
        "height": height,
        "unique_colors": len(unique),
        "unique_capped": capped,
        "luma_mean": round(mean, 3),
        "luma_std": round(std, 3),
        "sampled_pixels": count,
        "sample_step": step,
    }


def inspect_image(path, expect_size=None, min_unique=MIN_UNIQUE_COLORS,
                  min_std=MIN_LUMA_STD):
    """校验单张 PNG；返回 {"path","ok","reasons",...}（不抛异常，坏图一律进 reasons）。"""
    abspath = os.path.abspath(path)
    result = {
        "path": abspath,
        "name": os.path.basename(abspath),
        "ok": False,
        "reasons": [],
        "width": None,
        "height": None,
        "bytes": 0,
        "unique_colors": None,
        "luma_mean": None,
        "luma_std": None,
    }
    reasons = result["reasons"]
    if not os.path.isfile(abspath):
        reasons.append("文件不存在: %s" % abspath)
        return result
    try:
        size = os.path.getsize(abspath)
    except OSError as exc:
        reasons.append("无法读取文件大小: %r" % (exc,))
        return result
    result["bytes"] = size
    if size == 0:
        reasons.append("文件为空（0 字节）")
        return result
    try:
        with open(abspath, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        reasons.append("无法读取文件: %r" % (exc,))
        return result
    header = read_png_header(abspath)
    if header:
        result["width"], result["height"] = header
    try:
        decoded = decode_png(data)
    except PngError as exc:
        reasons.append("PNG 解码失败: %s" % exc)
        return result
    result["width"] = decoded["width"]
    result["height"] = decoded["height"]
    if expect_size is not None:
        want_w, want_h = int(expect_size[0]), int(expect_size[1])
        if (decoded["width"], decoded["height"]) != (want_w, want_h):
            reasons.append("像素尺寸 %dx%d 不符合预期 %dx%d（声明值与实际 PNG 不一致？）"
                           % (decoded["width"], decoded["height"], want_w, want_h))
    if decoded["width"] < MIN_VIEW_SIZE or decoded["height"] < MIN_VIEW_SIZE:
        reasons.append("图像尺寸过小: %dx%d（任一边 < %d 视为占位/损坏）"
                       % (decoded["width"], decoded["height"], MIN_VIEW_SIZE))
    stats = image_stats(decoded)
    result.update({
        "unique_colors": stats["unique_colors"],
        "unique_capped": stats["unique_capped"],
        "luma_mean": stats["luma_mean"],
        "luma_std": stats["luma_std"],
        "sampled_pixels": stats["sampled_pixels"],
        "sample_step": stats["sample_step"],
    })
    rich = stats["unique_capped"] or stats["unique_colors"] >= min_unique
    contrast = stats["luma_std"] >= min_std
    if not rich and not contrast:
        reasons.append("疑似空白/纯色图（唯一色=%d < %d 且亮度 std=%.2f < %.2f）"
                       % (stats["unique_colors"], min_unique,
                          stats["luma_std"], min_std))
    elif not rich:
        reasons.append("颜色过少（唯一色=%d < %d，疑似纯色/占位图）"
                       % (stats["unique_colors"], min_unique))
    elif not contrast:
        reasons.append("画面对比度过低（亮度 std=%.2f < %.2f，疑似空白图）"
                       % (stats["luma_std"], min_std))
    result["ok"] = not reasons
    return result


# ---------------------------------------------------------------------------
# 渲染目录 / 输出目录 / 联系表
# ---------------------------------------------------------------------------

def _load_contact_sheet_module():
    """复用 contact_sheet.collect_images 的排序/过滤规则，避免两处漂移。"""
    try:
        import contact_sheet  # noqa: F401
        return contact_sheet
    except Exception:  # noqa: BLE001
        try:
            import importlib.util
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "contact_sheet.py")
            spec = importlib.util.spec_from_file_location("contact_sheet", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:  # noqa: BLE001
            return None


def list_render_pngs(renders_dir):
    """按 contact_sheet 的稳定顺序列出渲染图（排除联系表）。"""
    module = _load_contact_sheet_module()
    if module is not None:
        try:
            return module.collect_images(renders_dir)
        except Exception:  # noqa: BLE001
            pass
    if not os.path.isdir(renders_dir):
        return []
    names = [name for name in sorted(os.listdir(renders_dir))
             if name.lower().endswith(".png") and name != CONTACT_SHEET_NAME]
    return [os.path.join(renders_dir, name) for name in names]


def expected_sizes_from_report(out_dir):
    """从 report.json 的 renders 记录取「声明的宽高」，用于校验像素尺寸符合预期。"""
    report_path = os.path.join(out_dir, "report.json")
    try:
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(report, dict):
        return {}
    sizes = {}
    for entry in report.get("renders") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path") or entry.get("file")
        width = entry.get("width")
        height = entry.get("height")
        if not isinstance(path, str):
            continue
        if not (isinstance(width, int) and isinstance(height, int)):
            continue
        if width <= 0 or height <= 0:
            continue
        sizes[os.path.basename(path.replace("\\", "/"))] = (width, height)
    return sizes


def probe_renders(renders_dir, expect_size=None, declared_sizes=None,
                  min_unique=MIN_UNIQUE_COLORS, min_std=MIN_LUMA_STD):
    """检查一个渲染目录；返回 {"ok","mode","target","files","reasons"}。"""
    renders_dir = os.path.abspath(renders_dir)
    payload = {
        "mode": "renders",
        "target": renders_dir,
        "ok": False,
        "files": [],
        "reasons": [],
    }
    if not os.path.isdir(renders_dir):
        payload["reasons"].append("缺少 renders/ 目录: %s" % renders_dir)
        return payload
    paths = list_render_pngs(renders_dir)
    if not paths:
        payload["reasons"].append("renders/ 下没有 PNG 文件: %s" % renders_dir)
        return payload
    declared = declared_sizes or {}
    for path in paths:
        name = os.path.basename(path)
        size = expect_size
        if size is None and name in declared:
            size = declared[name]
        result = inspect_image(path, expect_size=size,
                               min_unique=min_unique, min_std=min_std)
        payload["files"].append(result)
        for reason in result["reasons"]:
            payload["reasons"].append("%s: %s" % (name, reason))
    payload["ok"] = all(item["ok"] for item in payload["files"])
    return payload


def probe_out(out_dir, min_unique=MIN_UNIQUE_COLORS, min_std=MIN_LUMA_STD):
    """检查输出目录（renders/ + report.json 声明的尺寸）；返回 payload。"""
    out_dir = os.path.abspath(out_dir)
    payload = probe_renders(os.path.join(out_dir, "renders"),
                            declared_sizes=expected_sizes_from_report(out_dir),
                            min_unique=min_unique, min_std=min_std)
    payload["mode"] = "out"
    payload["target"] = out_dir
    return payload


def expected_sheet_geometry(view_paths, cols=SHEET_COLS, tile_height=SHEET_TILE_HEIGHT,
                            max_tiles=SHEET_MAX_TILES):
    """按 contact_sheet.build_sheet 的版式复算联系表尺寸与格数。

    返回 {"ok","width","height","tiles","cols","rows","cell_width","reasons"}；
    任一渲染图头部不可解析时 ok=False（Pillow 侧同样会跳过该图，尺寸无从复算）。
    """
    info = {"ok": True, "width": 0, "height": 0, "tiles": 0,
            "cols": 0, "rows": 0, "cell_width": 0, "reasons": []}
    if cols < 1 or tile_height < 1 or max_tiles < 1:
        info["ok"] = False
        info["reasons"].append("联系表参数非法: cols=%r height=%r max=%r"
                               % (cols, tile_height, max_tiles))
        return info
    loaded = []
    for path in list(view_paths)[:max_tiles]:
        dims = read_png_header(path)
        if not dims or dims[1] <= 0:
            info["ok"] = False
            info["reasons"].append("无法读取渲染图头，联系表尺寸无法复算: %s"
                                   % os.path.basename(path))
            continue
        width = max(1, int(round(dims[0] * (tile_height / float(dims[1])))))
        loaded.append(width)
    if not loaded:
        info["ok"] = False
        if not info["reasons"]:
            info["reasons"].append("没有可用于复算联系表的渲染图")
        return info
    use_cols = max(1, min(cols, len(loaded)))
    rows = (len(loaded) + use_cols - 1) // use_cols
    cell_width = max(loaded)
    info.update({
        "tiles": len(loaded),
        "cols": use_cols,
        "rows": rows,
        "cell_width": cell_width,
        "width": use_cols * cell_width + (use_cols + 1) * SHEET_MARGIN,
        "height": rows * (tile_height + SHEET_LABEL_HEIGHT) + (rows + 1) * SHEET_MARGIN,
    })
    return info


def inspect_contact_sheet(sheet_path, renders_dir=None, cols=SHEET_COLS,
                          tile_height=SHEET_TILE_HEIGHT, max_tiles=SHEET_MAX_TILES,
                          min_unique=MIN_UNIQUE_COLORS, min_std=MIN_LUMA_STD):
    """校验联系表：可解码/非空白 + 尺寸与格数符合预期。返回 payload dict。"""
    payload = {
        "mode": "sheet",
        "target": os.path.abspath(sheet_path),
        "ok": False,
        "reasons": [],
        "files": [],
        "expected": None,
    }
    info = inspect_image(sheet_path, min_unique=min_unique, min_std=min_std)
    payload["files"].append(info)
    payload["reasons"].extend("联系表: %s" % reason for reason in info["reasons"])
    if not info["ok"]:
        return payload
    if renders_dir is not None:
        geometry = expected_sheet_geometry(list_render_pngs(renders_dir),
                                           cols=cols, tile_height=tile_height,
                                           max_tiles=max_tiles)
        payload["expected"] = geometry
        if not geometry["ok"]:
            payload["reasons"].extend(geometry["reasons"])
            return payload
        actual = (info["width"], info["height"])
        want = (geometry["width"], geometry["height"])
        if actual != want:
            payload["reasons"].append(
                "联系表尺寸 %dx%d 与预期 %dx%d 不符（%d 格，%d 列；"
                "可能被伪造/截断或与渲染图不同步）"
                % (actual[0], actual[1], want[0], want[1],
                   geometry["tiles"], geometry["cols"]))
        if len([p for p in list_render_pngs(renders_dir)]) < 1:
            payload["reasons"].append("渲染图列表为空，无法验证联系表格数")
    payload["ok"] = not payload["reasons"]
    return payload


def probe_files(paths, expect_size=None, min_unique=MIN_UNIQUE_COLORS,
                min_std=MIN_LUMA_STD):
    """检查一组单图；返回 {"ok","mode","target","files","reasons"}。"""
    payload = {"mode": "files", "target": ", ".join(paths), "ok": False,
               "files": [], "reasons": []}
    for path in paths:
        result = inspect_image(path, expect_size=expect_size,
                               min_unique=min_unique, min_std=min_std)
        payload["files"].append(result)
        for reason in result["reasons"]:
            payload["reasons"].append("%s: %s" % (result["name"], reason))
    payload["ok"] = bool(payload["files"]) and all(item["ok"]
                                                   for item in payload["files"])
    return payload


def probe_out_full(out_dir, sheet=None, cols=SHEET_COLS, tile_height=SHEET_TILE_HEIGHT,
                   max_tiles=SHEET_MAX_TILES):
    """输出目录完整探针：渲染图 + （可选/自动发现的）联系表。"""
    payload = probe_out(out_dir)
    renders_dir = os.path.join(os.path.abspath(out_dir), "renders")
    candidates = []
    if sheet:
        candidates.append(sheet)
    auto = os.path.join(renders_dir, CONTACT_SHEET_NAME)
    if not sheet and os.path.isfile(auto):
        candidates.append(auto)
    payload["sheet"] = None
    if candidates:
        sheets = [inspect_contact_sheet(path, renders_dir=renders_dir, cols=cols,
                                        tile_height=tile_height, max_tiles=max_tiles)
                  for path in candidates]
        payload["sheet"] = sheets[0] if len(sheets) == 1 else sheets
        for item in sheets if isinstance(payload["sheet"], list) else [payload["sheet"]]:
            if not item["ok"]:
                payload["ok"] = False
                payload["reasons"].extend(item["reasons"])
    return payload


# ---------------------------------------------------------------------------
# 自测（自带夹具，不依赖仓库产物/Pillow）
# ---------------------------------------------------------------------------

def _encode_rgb_png(width, height, pixels):
    """自测用最小 PNG 编码器（8bit RGB，filter=0）；pixels 为 width*height*3 字节。"""
    rows = []
    stride = width * 3
    for y in range(height):
        rows.append(b"\x00" + bytes(pixels[y * stride:(y + 1) * stride]))
    raw = b"".join(rows)

    def chunk(ctype, payload):
        return (struct.pack(">I", len(payload)) + ctype + payload
                + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (PNG_MAGIC + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def _gradient_pixels(width, height, base=40, span=150):
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            index = (y * width + x) * 3
            pixels[index] = (base + x * span // max(1, width - 1)) & 0xFF
            pixels[index + 1] = (base + y * span // max(1, height - 1)) & 0xFF
            pixels[index + 2] = 128
    return bytes(pixels)


def _solid_pixels(width, height, color=(90, 90, 90)):
    return bytes(bytearray(color * (width * height)))


def _write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _sheet_pixels(width, height):
    """伪造一张尺寸正确、内容非空白的联系表（深色渐变底 + 色块标签）。"""
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            index = (y * width + x) * 3
            pixels[index] = (28 + x % 17) & 0xFF
            pixels[index + 1] = (28 + y % 19) & 0xFF
            pixels[index + 2] = 32
    for row in range(2):
        for col in range(2):
            y0 = SHEET_MARGIN + row * (64 + SHEET_LABEL_HEIGHT)
            x0 = SHEET_MARGIN + col * (64 + SHEET_MARGIN)
            for y in range(y0, min(y0 + 64, height)):
                for x in range(x0, min(x0 + 64, width)):
                    index = (y * width + x) * 3
                    pixels[index] = 60 + col * 40
                    pixels[index + 1] = 80 + row * 50
                    pixels[index + 2] = 120
    return bytes(pixels)


def selftest():
    failures = []

    def expect(name, condition):
        if condition:
            print("[PASS] selftest: " + name)
        else:
            print("[FAIL] selftest: " + name)
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="bm-vision-probe-") as tmp:
        wide, tall = 64, 64
        good_path = _write(os.path.join(tmp, "view-front.png"),
                           _encode_rgb_png(wide, tall, _gradient_pixels(wide, tall)))
        good = inspect_image(good_path, expect_size=(wide, tall))
        expect("正常渲染图判定通过", good["ok"] and good["reasons"] == [])
        expect("正常图唯一色充足", good["unique_colors"] >= MIN_UNIQUE_COLORS)
        expect("正常图亮度方差足够", good["luma_std"] >= MIN_LUMA_STD)

        blank_path = _write(os.path.join(tmp, "view-iso.png"),
                            _encode_rgb_png(wide, tall, _solid_pixels(wide, tall)))
        blank = inspect_image(blank_path)
        expect("纯色/空白图必须失败",
               not blank["ok"] and any("空白" in r for r in blank["reasons"]))

        good_bytes = _encode_rgb_png(wide, tall, _gradient_pixels(wide, tall))
        truncated_path = _write(os.path.join(tmp, "truncated.png"),
                                good_bytes[:len(good_bytes) // 2])
        truncated = inspect_image(truncated_path)
        expect("截断 PNG 必须失败（结构损坏）",
               not truncated["ok"]
               and any("截断" in r or "IEND" in r for r in truncated["reasons"]))

        corrupt_crc = bytearray(good_bytes)
        corrupt_crc[40] ^= 0xFF
        corrupt_path = _write(os.path.join(tmp, "crc.png"), bytes(corrupt_crc))
        expect("CRC 被篡改的 PNG 必须失败",
               not inspect_image(corrupt_path)["ok"])

        wrong_path = _write(os.path.join(tmp, "wrong.png"),
                            _encode_rgb_png(48, 48, _gradient_pixels(48, 48)))
        wrong = inspect_image(wrong_path, expect_size=(wide, tall))
        expect("尺寸与预期不符必须失败",
               not wrong["ok"] and any("不符合预期" in r for r in wrong["reasons"]))

        empty_path = _write(os.path.join(tmp, "empty.png"), b"")
        expect("空文件必须失败",
               not inspect_image(empty_path)["ok"])

        not_png = _write(os.path.join(tmp, "fake.png"), b"not a png" * 100)
        expect("非 PNG 必须失败",
               not inspect_image(not_png)["ok"])

        # 渲染目录探针：正常 2 张 -> ok；夹一张空白 -> 整体失败
        renders = os.path.join(tmp, "out", "renders")
        os.makedirs(renders)
        _write(os.path.join(renders, "view-front.png"), good_bytes)
        _write(os.path.join(renders, "view-right.png"),
               _encode_rgb_png(wide, tall, _gradient_pixels(wide, tall, base=90)))
        dir_payload = probe_renders(renders)
        expect("渲染目录探针通过", dir_payload["ok"] and len(dir_payload["files"]) == 2)
        _write(os.path.join(renders, "view-iso.png"),
               _encode_rgb_png(wide, tall, _solid_pixels(wide, tall)))
        expect("渲染目录出现空白图必须整体失败", not probe_renders(renders)["ok"])

        # 联系表：几何复算 + 尺寸校验 + 错尺寸失败
        sheet_dir = os.path.join(tmp, "sheet-out", "renders")
        os.makedirs(sheet_dir)
        for index, name in enumerate(("view-front.png", "view-right.png", "view-iso.png")):
            _write(os.path.join(sheet_dir, name),
                   _encode_rgb_png(wide, tall,
                                   _gradient_pixels(wide, tall, base=30 + index * 30)))
        geometry = expected_sheet_geometry(list_render_pngs(sheet_dir),
                                           cols=2, tile_height=64, max_tiles=4)
        # 3 张 64x64、tile_height=64、cols=2 -> 2 列 2 行
        expect("联系表几何复算正确",
               geometry["ok"] and geometry["tiles"] == 3 and geometry["cols"] == 2
               and geometry["rows"] == 2
               and geometry["width"] == 2 * 64 + 3 * SHEET_MARGIN
               and geometry["height"] == 2 * (64 + SHEET_LABEL_HEIGHT) + 3 * SHEET_MARGIN)
        sheet_path = _write(os.path.join(sheet_dir, CONTACT_SHEET_NAME),
                            _encode_rgb_png(geometry["width"], geometry["height"],
                                            _sheet_pixels(geometry["width"],
                                                          geometry["height"])))
        sheet_ok = inspect_contact_sheet(sheet_path, renders_dir=sheet_dir,
                                         cols=2, tile_height=64, max_tiles=4)
        expect("联系表尺寸/格数校验通过", sheet_ok["ok"])
        bad_sheet = _write(os.path.join(sheet_dir, "bad-sheet.png"),
                           _encode_rgb_png(geometry["width"] + 7, geometry["height"],
                                           _sheet_pixels(geometry["width"] + 7,
                                                         geometry["height"])))
        expect("联系表尺寸不符必须失败",
               not inspect_contact_sheet(bad_sheet, renders_dir=sheet_dir,
                                         cols=2, tile_height=64,
                                         max_tiles=4)["ok"])

        # 输出目录探针：report.json 声明的宽度与 PNG 实际不符 -> 失败
        out_dir = os.path.join(tmp, "out-report")
        os.makedirs(os.path.join(out_dir, "renders"))
        _write(os.path.join(out_dir, "renders", "view-front.png"), good_bytes)
        with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as handle:
            json.dump({"renders": [{"path": "renders/view-front.png",
                                    "width": 128, "height": 128}]}, handle)
        expect("report 声明尺寸与 PNG 不符必须失败", not probe_out(out_dir)["ok"])

        # --json 判决字段齐全（直接调用 CLI）
        stdout = []
        real_print = print

        class _Capture(object):
            def write(self, text):
                stdout.append(text)

            def flush(self):
                pass

        original = sys.stdout
        try:
            sys.stdout = _Capture()
            code = main(["--dir", renders, "--json"])
        finally:
            sys.stdout = original
        try:
            payload = json.loads("".join(stdout))
        except ValueError:
            payload = None
        expect("--json stdout 是纯 JSON 且含 ok/files/reasons",
               code == 1 and isinstance(payload, dict)
               and payload.get("ok") is False
               and isinstance(payload.get("files"), list)
               and isinstance(payload.get("reasons"), list))

    if failures:
        print("\nSELFTEST FAILED: %d 项失败" % len(failures))
        return 1
    print("\nSELFTEST OK")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_payload(payload):
    print("=== vision_probe: %s ===" % payload["target"])
    for item in payload.get("files") or []:
        if item["ok"]:
            print("[PASS] %s %dx%d 解码 OK 唯一色=%s%s 亮度 mean=%.1f std=%.1f (%.1f KB)"
                  % (item["name"], item["width"], item["height"],
                     item["unique_colors"],
                     "+" if item.get("unique_capped") else "",
                     item["luma_mean"], item["luma_std"], item["bytes"] / 1024.0))
        else:
            print("[FAIL] %s %s" % (item["name"],
                                   "；".join(item["reasons"])))
    sheet = payload.get("sheet")
    if isinstance(sheet, dict):
        if sheet["ok"]:
            print("[PASS] 联系表 %dx%d（%d 张）"
                  % (sheet["files"][0]["width"], sheet["files"][0]["height"],
                     (sheet.get("expected") or {}).get("tiles", 0)))
        else:
            print("[FAIL] 联系表: %s" % "；".join(sheet["reasons"]))
    reasons = payload.get("reasons") or []
    if not payload["ok"]:
        print("=== 结果: FAIL（%d 条原因）===" % len(reasons))
    else:
        print("=== 结果: PASS ===")


def _parse_size(text):
    try:
        parts = str(text).lower().split("x")
        if len(parts) != 2:
            raise ValueError
        width, height = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("尺寸格式应为 WxH，例如 512x512")
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("尺寸必须为正整数")
    return width, height


def main(argv=None):
    _enable_utf8_console()
    parser = argparse.ArgumentParser(
        description="纯标准库视觉探针（PNG 解码/非空白/尺寸/联系表，不依赖 Pillow）")
    parser.add_argument("--out", default=None, help="输出目录（检查 renders/ + report.json）")
    parser.add_argument("--dir", default=None, help="直接给 renders 目录")
    parser.add_argument("--file", action="append", default=None,
                        help="单张 PNG（可重复；也可逗号分隔）")
    parser.add_argument("--sheet", default=None, help="联系表 PNG 路径")
    parser.add_argument("--sheet-cols", type=int, default=SHEET_COLS,
                        help="联系表列数（默认 %d，与 contact_sheet.py 一致）" % SHEET_COLS)
    parser.add_argument("--sheet-height", type=int, default=SHEET_TILE_HEIGHT,
                        help="联系表每格高度（默认 %d）" % SHEET_TILE_HEIGHT)
    parser.add_argument("--sheet-max", type=int, default=SHEET_MAX_TILES,
                        help="联系表最多张数（默认 %d）" % SHEET_MAX_TILES)
    parser.add_argument("--expect-size", type=_parse_size, default=None,
                        help="要求每张渲染图都是该尺寸，如 512x512")
    parser.add_argument("--min-unique", type=int, default=MIN_UNIQUE_COLORS,
                        help="非空白判定的唯一色下限（默认 %d）" % MIN_UNIQUE_COLORS)
    parser.add_argument("--min-std", type=float, default=MIN_LUMA_STD,
                        help="非空白判定的亮度 std 下限（默认 %.1f）" % MIN_LUMA_STD)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出判决")
    parser.add_argument("--selftest", action="store_true", help="运行自带夹具自测")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.sheet_cols < 1 or args.sheet_height < 1 or args.sheet_max < 1:
        parser.error("--sheet-cols/--sheet-height/--sheet-max 必须 >= 1")

    def run(payload):
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.out:
        payload = probe_out_full(
            os.path.abspath(args.out), sheet=args.sheet,
            cols=args.sheet_cols, tile_height=args.sheet_height,
            max_tiles=args.sheet_max)
        if args.expect_size is not None:
            payload["expect_size"] = list(args.expect_size)
            for item in payload["files"]:
                if item["width"] is None:
                    continue
                if (item["width"], item["height"]) != args.expect_size:
                    item["ok"] = False
                    item["reasons"].append("像素尺寸 %dx%d 不符合预期 %dx%d"
                                           % (item["width"], item["height"],
                                              args.expect_size[0], args.expect_size[1]))
                    payload["ok"] = False
                    payload["reasons"].append("%s: 像素尺寸不符合预期" % item["name"])
        return run(payload)
    if args.dir:
        payload = probe_renders(os.path.abspath(args.dir),
                                expect_size=args.expect_size,
                                min_unique=args.min_unique, min_std=args.min_std)
        return run(payload)
    if args.file:
        paths = []
        for value in args.file:
            paths.extend(part for part in str(value).split(",") if part.strip())
        payload = probe_files(paths, expect_size=args.expect_size,
                              min_unique=args.min_unique, min_std=args.min_std)
        return run(payload)
    if args.sheet:
        payload = inspect_contact_sheet(args.sheet,
                                        renders_dir=args.dir,
                                        cols=args.sheet_cols,
                                        tile_height=args.sheet_height,
                                        max_tiles=args.sheet_max,
                                        min_unique=args.min_unique,
                                        min_std=args.min_std)
        return run(payload)
    parser.error("必须提供 --out / --dir / --file / --sheet 之一（或使用 --selftest）")
    return 2


if __name__ == "__main__":
    sys.exit(main())
