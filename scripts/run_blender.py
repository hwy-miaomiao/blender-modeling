# -*- coding: utf-8 -*-
"""统一执行器：用 Blender headless 运行建模脚本。

用法：
    python scripts/run_blender.py --script <model.py> --out <输出目录> [--stage build|render|full]
                                  [--timeout 600] [--label run] [--blender <blender.exe>] [-- 透传参数]

行为：
- 自动定位 Blender（--blender > BLENDER_EXE > PATH > 常见安装路径）
- 以 `blender -b --factory-startup -noaudio --python-exit-code 1 --python <script>` 执行
- 注入环境变量 BLENDER_KIT_DIR / BLENDER_SKILL_DIR / BLENDER_OUT_DIR / BLENDER_STAGE
- stdout+stderr 合并写入 <out>/logs/<label>-<时间戳>.log
- 结束时打印一行机器可读结果：`BM_RESULT {...}`
- 退出码：成功 0，失败 1
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bl_common  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="用 Blender headless 执行建模脚本（统一日志/超时/错误提取）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/run_blender.py --script outputs/mug/model.py --out outputs/mug --stage build\n"
            "  python scripts/run_blender.py --script outputs/mug/model.py --out outputs/mug --stage full --timeout 900\n"
            "  python scripts/run_blender.py --script model.py --out out -- --views 4\n"
        ),
    )
    parser.add_argument("--script", required=True, help="建模脚本路径（.py）")
    parser.add_argument("--out", required=True, help="输出目录（renders/exports/logs/report.json 的父目录）")
    parser.add_argument("--stage", default="full", choices=("build", "render", "full"),
                        help="阶段：build 只建模不做最终渲染；render 渲染预览；full 全流程（默认）")
    parser.add_argument("--timeout", type=float, default=600.0, help="超时秒数（默认 600）")
    parser.add_argument("--label", default=None, help="日志文件名前缀（默认用 stage）")
    parser.add_argument("--blender", default=None, help="显式指定 Blender 可执行文件")
    parser.add_argument("extra", nargs=argparse.REMAINDER,
                        help="`--` 之后的参数会透传给建模脚本（sys.argv）")
    args = parser.parse_args(argv)

    extra = list(args.extra or [])
    if extra and extra[0] == "--":
        extra = extra[1:]

    result = bl_common.execute(
        script=args.script,
        out_dir=args.out,
        stage=args.stage,
        timeout=args.timeout,
        label=args.label,
        extra_args=extra,
        blender=args.blender,
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
