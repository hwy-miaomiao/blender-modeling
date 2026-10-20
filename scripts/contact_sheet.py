# -*- coding: utf-8 -*-
"""把多角度渲染图拼成一张联系表（contact sheet），方便一眼查看整体效果。

用法：
    python scripts/contact_sheet.py --out <输出目录> [--cols 2] [--height 480]

依赖 Pillow（可选）。未安装时打印 WARN 并以 0 退出（不阻塞建模流程）。
产物：<输出目录>/renders/contact-sheet.png
"""

from __future__ import annotations

import argparse
import os
import sys


def _enable_utf8_console():
    """让脚本在 Windows 上以 UTF-8 输出中文（避免 GBK 控制台把中文写成乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_enable_utf8_console()

try:
    from PIL import Image, ImageDraw
except ImportError:  # 可选依赖
    Image = None
    ImageDraw = None

PREFERRED_ORDER = ("front", "right", "left", "back", "iso", "top")
# 交付要求的 view-* 必须排在同角度的 final-* 前面：默认 --max 4 时不能挤掉必要的 iso 视角。
TIER_VIEW = 0
TIER_FINAL = 1
TIER_OTHER = 2
MARGIN = 10
BG = (28, 28, 32)
FG = (235, 235, 235)


def _angle_rank(name):
    lower = name.lower()
    for index, key in enumerate(PREFERRED_ORDER):
        if key in lower:
            return index
    return len(PREFERRED_ORDER)


def _tier_rank(name):
    lower = name.lower()
    if lower.startswith("view-"):
        return TIER_VIEW
    if lower.startswith("final-"):
        return TIER_FINAL
    return TIER_OTHER


def collect_images(renders_dir):
    if not os.path.isdir(renders_dir):
        return []
    names = [
        name for name in sorted(os.listdir(renders_dir))
        if name.lower().endswith(".png") and name != "contact-sheet.png"
    ]
    # 先按 view-/final- 分层，再按角度优先级，最后按文件名保证结果稳定
    return [os.path.join(renders_dir, name) for name in
            sorted(names, key=lambda item: (_tier_rank(item), _angle_rank(item), item))]


def build_sheet(out_dir, cols=2, tile_height=480, max_images=4):
    renders_dir = os.path.join(out_dir, "renders")
    images = collect_images(renders_dir)[:max_images]
    if not images:
        print("WARN: %s 下没有可用的 PNG，跳过联系表" % renders_dir)
        return None

    loaded = []
    for path in images:
        try:
            image = Image.open(path).convert("RGB")
        except Exception as exc:  # PIL 的异常类型随版本变化，统一兜底
            print("WARN: 打开失败 %s (%s)" % (path, exc))
            continue
        width = max(1, round(image.width * (tile_height / float(image.height))))
        loaded.append((os.path.basename(path), image.resize((width, tile_height))))
    if not loaded:
        print("WARN: 没有成功读取的图片，跳过联系表")
        return None

    cols = max(1, min(cols, len(loaded)))
    rows = (len(loaded) + cols - 1) // cols
    cell_width = max(item[1].width for item in loaded)
    label_height = 24
    sheet = Image.new(
        "RGB",
        (cols * cell_width + (cols + 1) * MARGIN,
         rows * (tile_height + label_height) + (rows + 1) * MARGIN),
        BG,
    )
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(loaded):
        row, col = divmod(index, cols)
        x = MARGIN + col * (cell_width + MARGIN) + (cell_width - image.width) // 2
        y = MARGIN + row * (tile_height + label_height + MARGIN)
        sheet.paste(image, (x, y))
        draw.text((x + 4, y + tile_height + 4), name, fill=FG)

    sheet_path = os.path.join(renders_dir, "contact-sheet.png")
    sheet.save(sheet_path)
    print("PASS: 联系表已生成 %s (%dx%d, %d 张)" % (
        sheet_path, sheet.width, sheet.height, len(loaded)))
    return sheet_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="把渲染图拼成联系表（需要 Pillow）")
    parser.add_argument("--out", required=True, help="输出目录（读取其下 renders/）")
    parser.add_argument("--cols", type=int, default=2, help="列数（默认 2）")
    parser.add_argument("--height", type=int, default=480, help="每格高度像素（默认 480）")
    parser.add_argument("--max", type=int, default=4, help="最多拼入几张（默认 4）")
    args = parser.parse_args(argv)
    # 参数在动 Pillow 之前先校验：--height 0/负数会让 resize 抛未捕获的 ValueError
    if args.cols < 1:
        parser.error("--cols 必须 >= 1")
    if args.height < 1:
        parser.error("--height 必须 >= 1")
    if args.max < 1:
        parser.error("--max 必须 >= 1")

    if Image is None:
        print("WARN: 未安装 Pillow，无法生成联系表（pip install pillow 后重试）")
        return 0

    out_dir = os.path.abspath(args.out)
    if not os.path.isdir(out_dir):
        print("ERROR: 输出目录不存在: %s" % out_dir)
        return 1
    path = build_sheet(out_dir, cols=args.cols, tile_height=args.height, max_images=args.max)
    return 0 if path else 1


if __name__ == "__main__":
    sys.exit(main())
