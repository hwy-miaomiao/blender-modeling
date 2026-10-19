# Changelog

本文件的格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循语义化版本。

## [Unreleased]

### 新增

- `references/architecture-modeling.md`：建筑领域建模技巧（模块化墙体/楼板/屋顶/门窗阵列/台阶/栏杆、真实尺寸表、技巧库与配方，城镇居民楼与拱桥两个 `--stage full` 实测）。
- `references/character-modeling.md`：人物领域建模技巧（头身比量算、球棍式/箱式/锥台三条路径、五官与发型参数、静态摆姿三步法，Q 版与招手卡通人物实测）。
- `references/animal-modeling.md`：动物领域建模技巧（四足/鸟/鱼/昆虫体块拆解、剪影优先、翼面上反角与可见性、物种尺寸表，猫与展翅海鸥实测）。
- `references/plant-modeling.md`：植物领域建模技巧（递归分枝、树冠几何簇、叶卡片与花瓣环、季节配色板、地面融合，阔叶树与花坛实测）。
- `scripts/ci_check.py` 新增领域技巧文档检查：10 节结构齐全、python 代码块可编译、无盘符绝对路径。
- SKILL.md 参考表、AGENTS.md 第 16 节索引与第 5 节拆解指引、README 目录结构加入四篇领域文档入口。

## [1.1.0] - 2026-10-19

一次系统性审计（两位独立审计员 + 全量回归）后的修复与增强版本。目标是让「交付出去的资产」和「闸门说的话」都可信。

### 新增

- `lib/blender_kit.py` 新增 `open_blend(path)`：打开已有 `.blend` 继续编辑/重渲/重导出，配合新模板支持「改模型」请求。
- `templates/edit_model_template.py`：修改已有模型的工作流模板（对象增删、位移/旋转/缩放、换材质、隐藏，再重新渲染导出）。
- `references/export-and-integration.md`：导出格式选择、单位与坐标系、Three.js / Unity / Unreal / Godot 接入、3D 打印清单、材质边界。
- `tests/`：`test_cli_contract.py`、`test_bl_common.py`、`test_contact_sheet.py`（标准库 unittest，CI 每次跑）、`kit_smoke.blender.py` 与 `kit_regression.blender.py`（需要 Blender 的手工回归）。
- `scripts/ci_check.py` 新增：交付 GLB 资产检查（不得含摄影棚地台 / 布尔 cutter / `.001` 重名）、CI workflow 步骤检查、更多必需文件。
- CI 增加单元测试步骤与 `tests/` 语法编译。

### 修复

- **交付 GLB 混入摄影棚地台**：`export_glb/stl/fbx/obj` 改为只导出几何对象，默认排除 `kit_role="floor"` 的 20 m 地台；新增 `include_floor=False` 参数可按需保留。`.blend` 仍保留完整场景方便重渲。
- **布尔 cutter 混进交付**：`add_boolean(apply=False)` 的 cutter 现在标记 `kit_role="cutter"` 并 hide_viewport，导出与取景都会跳过它。
- **隐藏对象污染取景与统计**：新增 `_visible_geometry()`，`fit_camera` / `scene_report` 只统计可见几何，隐藏的 40 m 参考物不再把相机推到 91 m、也不再污染 dimensions。
- **面数统计忽略修改器**：`mesh_stats` 默认按 depsgraph 求值后的网格统计（倒角+细分后不再是 12 面而是真实面数），与 AGENTS.md 的质量基线口径一致。
- **`add_mirror(bisect=...)` 参数无效**：不再静默切掉跨镜像面的原始几何；`bisect=False` 时保留完整几何。
- **对象重名 `.001`**：`_unique_object_name` 支持排除自身，`tube()` / `cube("Cube")` / `text("Text")` / 同名 `join` 不再自动加 `.001`。
- **失效对象统一降级**：`mesh_stats` / `apply_modifiers` / `join` / `shade_smooth` / `assign` 对已删除对象改为 warn 返回，不再抛 `ReferenceError`。
- **渲染设置泄漏**：`render_views` / `render_turntable` 结束后恢复原渲染设置；`render_still(camera=...)` 恢复 `scene.camera`；`render_still` 的记录补上 engine/resolution/samples。
- **report.json 绝对路径**：`save_report` 统一写相对路径（`/` 分隔），与 `check_output.py` 的交付闸门口径一致。
- `open_blend` 对损坏 `.blend` 不再抛未捕获 `RuntimeError`，改为 warn 并返回 `{}`。
- `setup_floor` 幂等：重复调用不再叠加 `Floor.001`。
- `cube(size=(1,2))` 不再抛 `IndexError`；`look_at` 相机与目标重合时给出警告。
- 脚本层修复：`check_output.py` 拒绝 report 绝对路径、校验渲染图最小尺寸与 `--min-views >= 1`、`--json` 输出纯 JSON；`bl_common.py` 对显式指定的 Blender 路径做严格校验（不静默回退）、清洗 `--label` 防 NTFS ADS/路径穿越/Windows 保留名、退出码 0 时把弱错误行降级为警告、render/full 阶段零产物判失败；`ci_check.py` 对脏 report.json 不再 Traceback 崩溃、绝对路径检查同时识别正斜杠写法、类型错误统一报 ERROR。
- 文档：AGENTS.md / SKILL.md / README.md 更新「改模型」流程、导出排除地台说明、构图判据与实测数字；README 去掉本机绝对路径。

## [1.0.0] - 2026-10-19

首个版本：`blender-modeling` 技能本体。

- `SKILL.md` 入口 + `AGENTS.md` 完整工作流规范（阶段 0-9、校验闸门、质量基线、看图清单、失败处理）。
- `lib/blender_kit.py`：场景/图元/变换/修改器/材质/渲染/导出/report 的 headless bpy 封装。
- 脚本：`run_blender.py`（无头执行 + 日志分类）、`doctor.py`（环境体检 + 冒烟）、`check_output.py`（交付闸门 + 纯函数自测）、`contact_sheet.py`（多角度拼图）、`ci_check.py`（仓库静态检查）。
- `templates/model_template.py`：两段式（build / full）建模模板。
- 参考文档：prompt-to-model、modeling-recipes、render-and-check、troubleshooting、bpy-cookbook。
- 两个可复现样例：`lowpoly-mug`、`office-chair`（含预览图、`.blend`、`.glb`、report）。
- MIT License、GitHub Actions CI、本地 `doctor.py --smoke` 端到端冒烟。
