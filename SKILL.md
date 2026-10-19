---
name: blender-modeling
description: 用本机 Blender（headless bpy 脚本）把自然语言提示词做成真实可交付的 3D 模型：解析需求→结构拆解→写 bpy 建模脚本→无头多角度渲染→看图自检迭代→导出 .blend/.glb/.stl 与预览图。用户说「用 Blender 建模」「做个 3D 模型」「建个模」「低多边形××」「3D 场景」「改模型」「导出 glb/stl/blend」等时调用。完整规范在 AGENTS.md，动手前必须整篇读完。
---

# Blender 建模（blender-modeling）

把用户的一句提示词变成**真实、可交付、可复现**的 3D 模型：几何 + 材质 + 灯光相机 + 多角度渲染图 + 导出文件，全部由本机 Blender 以 headless bpy 脚本完成。

用户输入的提示词就是建模目标。如果本技能被调用时没有拿到具体提示词，先向用户要一句描述（主体 + 风格 + 用途），不要凭空猜。

## 三条铁律（违反任一条视为任务失败）

1. **先读规范再动手。** 本文件只是入口，完整流程、命令与验收标准在 [`AGENTS.md`](AGENTS.md)。动手前必须整篇读完，并严格按其「阶段 0 → 阶段 9」执行。
2. **必须真看图再交付。** 每轮渲染后用 `read_image` 打开 `renders/view-*.png` 逐张检查；禁止只看日志就宣称模型没问题。
3. **必须过闸门。** `scripts/check_output.py` 0 ERROR 且 `scripts/doctor.py` 无 FAIL，才允许向用户交付。

## 最小工作流（细节以 AGENTS.md 为准）

0. 环境体检：`python scripts/doctor.py`（有 FAIL 先按提示修环境，再开工）
1. 解析提示词 → 写建模简报 `<输出目录>/brief.md`（默认不问用户，把假设写清楚）
2. 复制 `templates/model_template.py` 为 `<输出目录>/model.py`，用 `lib/blender_kit.py` 的 API 实现建模
3. build 自检：`python scripts/run_blender.py --script <输出目录>/model.py --out <输出目录> --stage build`
4. 渲染预览后**看图自检**：read_image 打开 `<输出目录>/renders/view-*.png`，对照提示词找问题
5. 迭代修正（最多 4 轮，每轮只改 1-2 类问题）
6. 终渲导出：`--stage full` → blend/glb + 最终渲染图 + `report.json`
7. 交付闸门：`python scripts/check_output.py --out <输出目录>`
8. 向用户交付：文件路径、怎么看预览、还能怎么改

## 路径约定

- `<技能目录>`：本文件所在目录（skill 工具会返回 base directory；`scripts/`、`lib/`、`templates/` 都在这里）
- `<工作区>`：用户当前项目根目录（cwd）
- `<输出目录>`：`<工作区>/blender-models/<slug>/`（slug 全小写连字符，如 `lowpoly-mug`）
- 产物禁止写进技能目录；`model.py` 里禁止硬编码 Blender 路径（执行器自动定位）

## 参考文档（按需读，不要一次全读）

| 文档 | 什么时候读 |
| --- | --- |
| `AGENTS.md` | **动手前必读**：完整流程、每阶段命令与验收条件 |
| `references/prompt-to-model.md` | 阶段 1-2：提示词怎么翻译成建模简报与部件表 |
| `references/modeling-recipes.md` | 阶段 3：常见题材的部件拆解与代码骨架 |
| `references/bpy-cookbook.md` | 阶段 3-4：bpy 4.0 实测 API 与坑 |
| `references/render-and-check.md` | 阶段 5-6：相机灯光参数与看图自检清单 |
| `references/troubleshooting.md` | 报错时查：症状 / 原因 / 解决 |
| `examples/` | 需要 few-shot 参考时看两个完整实测样例 |

## 交付时告诉用户

模型是什么、文件在哪（`.blend` / `.glb` / 渲染图）、怎么在 Blender 里打开或导入游戏引擎、哪些是简化处理、下一轮可以怎么改。
