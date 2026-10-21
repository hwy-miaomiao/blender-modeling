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
- `docs/previews/`：建筑/人物/动物/植物四张效果预览图（各由两个代表题材的 960×960 实测终渲拼合），README「效果预览」与四篇领域文档顶部均已嵌入；`scripts/ci_check.py` 新增预览图检查（存在性、PNG 魔数、尺寸与体积下限、README 与领域文档双向引用）。
- `scripts/vision_metrics.py`：视觉自检量化（无需 GPU、Pillow 可选）——对 `renders/view-*.png` 做四角种子 + 梯度受限背景 flood、取最大连通域，输出主体占比、四边留白、底部留白、亮度分位；`VISION001`-`VISION007` 阈值常量与 `--selftest`；无 Pillow 时自动跳过。`run_blender.py --stage full` 成功后自动把 `vision` 写入 `report.json`（`--no-vision` 可关）。
- `scripts/snapshot.py`：迭代版本化（竞品 commit gate 思路）——`--list` 看 `history/vN`、`--promote`/`--rollback` 回退最佳版本，`best.json` 记录 schema/渲染图/面数/`model.py` sha256；结构不合法只 WARN，不阻塞交付。
- `scripts/safe_check.py`：SAFE_MODE 静态审查——AST 检查 `model.py`/模板是否出现 `subprocess`、`os.system`、`eval`/`exec`、网络库、`__import__`、绝对路径或 `..` 写文件与魔术属性；按 `file:line` 输出 SAFE001-SAFE009，`--selftest` 有 13 个用例；`ci_check.py` 默认审 `templates/` 与 `examples/*/model.py`。
- `check_output.py` 新增三组结构检查：视觉指标闸门（`--no-vision` 可关，Pillow 缺失自动 SKIP）、brief 迭代记录校验（引用的渲染图必须存在；`report` 含 `vision` 时要求每轮写图名+量化值）、`history/best.json` 结构一致性（只 WARN）。
- 测试：新增 `tests/test_vision_metrics.py`、`tests/test_snapshot.py`、`tests/test_safe_check.py`（+27 用例，视觉与快照测试用临时目录与假 PNG，不依赖 Blender/Pillow）；`ci_check.py` REQUIRED_FILES 与 CI 工作流同步新增三个 `--selftest` 步骤。
- 文档：README 新增「什么时候用本项目（以及什么时候不用）」分工表（vs TRELLIS/Hunyuan3D、blender-mcp）与三个新脚本命令；AGENTS 铁律 0.3 扩为七条（新增 SAFE_MODE）、§9 迭代记录改为「看了哪张图 + 量化值」5 列、§11 闸门表与 §14 清单接入 `report.vision`、§17 新增视觉/SAFE_MODE/快照三道闸门；SKILL 铁律与最小工作流同步。

### 修复

- **视觉闸门不再把「无法判定」当通过**：`vision_metrics.analyze_out` 在 `renders/` 非空但所有 PNG 都无法解码时新增 `VISION008` ERROR（伪造/损坏图不再落入 skipped 后 SKIP）；`check_output.check_vision` 对这种情况直接判 ERROR，退出码 1。
- **存量项目迁移（backfill）**：`vision_metrics.py --write` 手工补写 `report.vision` 时写入 `backfill: true` 与 `backfilled_at`；`check_output.check_iteration_records` 对 backfill 只校验迭代记录里的图片引用、不强制新 5 列表格；`run_blender.py --stage full` 自动重算的 vision 不带 backfill 标记，严格校验随即生效。AGENTS §9 与 README 常见问题补充迁移说明。
- **`safe_check.py` 路径写文件加固**：`Path.open` / `Path.write_text` 的接收者路径纳入检查；变量路径写文件从 WARN 升为 `SAFE006` ERROR；新增盘符相对路径（`C:evil.txt`，`SAFE003`）与 `shutil.copyfile/copy/copy2/copytree`（`SAFE002`）；写文件白名单改为「目录前缀」语义，`data/report.json` 等借 basename 的绕过不再放行；`%TEMP%` / `tempfile.gettempdir()` 等输出目录表达式继续放行。
- **`snapshot.py --json` 输出纯 JSON**：`--list` / 创建 / promote / rollback 的人读日志改走 stderr，stdout 只输出可 `json.loads` 的 JSON。
- **`vision_metrics.py --write` 原子覆盖**：先写同目录 `.tmp` 再 `os.replace`，替换失败时保留原 `report.json` 并清理临时文件。
- **`report.vision` 全字段一致性**：`check_output` 逐字段对照主体/背景占比、四边留白、底部留白与亮度 mean/std（容差 0.02 / 2.0），不一致从 WARN 升为 ERROR；并校验 `report.vision.ok` 与实测一致（WARN）。
- **空迭代记录**：`report.json` 含（非 backfill）`vision` 但 brief「## 迭代记录」没有任何数据行时，`check_output` 报 ERROR（新产物至少记录 1 轮），不再 vacuous PASS。
- **CI 覆盖真实产物**：工作流安装 Pillow 并跑两个 `examples/` 的 `check_output.py`，用 `grep "视觉指标: SKIP"` 兜底（SKIP 计数必须为 0）；`ci_check.check_ci_workflow` 同步要求这些步骤关键字。
- **文档**：README 常见问题与设计原则、AGENTS §0.3 铁律 7 / §9 迁移与快照说明 / §11 ERROR 表 / §14 清单 / §17 闸门表补 `VISION008`、`SAFE006` 变量路径、`shutil` 拷贝与 `--rollback` 不还原 `exports/` 的说明；SKILL 铁律 4 与小工作流同步。
- 测试：新增 `tests/test_check_output_vision.py`（真实 PNG、backfill、空迭代表、篡改指标、坏 PNG 阻断 7 用例）；`test_bl_common.py` 增 vision attach / execute 分支 / `--no-vision` 5 用例；`test_vision_metrics.py` 增 VISION008、backfill、原子写用例；`test_safe_check.py` 增 Path.open/变量路径/shutil/盘符相对/`--json` 纯度等 9 用例；`ci_check.py` REQUIRED_FILES 与 CI 步骤关键字同步。
- **第二轮验证 B10 残留：`report.renders` 统计也从渲染图重算对照**：`check_output` 在 Pillow 可用时用与 kit 相同的 sRGB 亮度公式（`lum = 0.2126R + 0.7152G + 0.0722B`、alpha≤2 忽略、总体 std、`black_ratio = lum<8` 占比）从 PNG 重算 `mean/std/black_ratio`，与 `report.json.renders[]` 记录对照（容差 mean/std 1.0、`black_ratio` 0.01），不一致报 ERROR「report.renders 统计与渲染图不符」；Pillow 缺失或解码失败静默降级（不误报）。`tests/test_check_output_vision.py` 增篡改 std / black_ratio 的反例。
- **第二轮验证 R2-B1：无 Pillow 环境测试契约**：`tests/test_vision_metrics.py` 的 `test_undecodable_png_is_error_not_skip` 改用 `@unittest.skipUnless(vm.pillow_available(), ...)` 跳过，与 `tests/README.md`「Pillow 用例自动跳过」一致；无 Pillow 的 Python 3.9.13 环境整份 `unittest discover` 全绿（20 skip）。
- **第三轮验证 R3-B1：部分渲染图损坏不再降级为 WARN**：`check_output.check_vision` 把 `skipped` 从 WARN 升为 `VISION009` ERROR，错误信息列出无法解码的文件名/张数（`全部无法解码` 的 `VISION008` 也补上文件名）；Pillow 缺失仍 SKIP 降级，`--no-vision` 仍可整体关闭视觉闸门。`tests/test_check_output_vision.py` 增「好图+坏图混合 → ERROR」用例，`check_output --selftest` 增桩测试（共 40 项）；AGENTS §11/§14/§17 与 `tests/README.md` 同步。

## [1.1.1] - 2026-10-21

第 8 轮深度审计后的修复版本，重点是渲染取景与渲染状态恢复的边界行为，以及 Blender 子进程临时目录隔离。

### 修复

- **`render_views(views=...)` 边界**：传单个字符串（如 `views="front"`）不再被逐字符迭代成 5 个未知视角、全部写成 `view-iso.png`；空 `views` 现在给出 WARN 并返回空列表，不再静默无输出。
- **`sensor_fit="VERTICAL"` 取景裁切**：`fit_camera` 计算 PERSP 纵向视角时改用 `sensor_height`（此前误用 `sensor_width`，纵向 FOV 被算大 1.5 倍，相机会摆得太近、画面纵向裁切）；`AUTO`/`HORIZONTAL` 行为不变。
- **渲染设置泄漏（续）**：`render_still` 结束后恢复 `scene.render.filepath` 与 `image_settings.file_format`（此前只恢复 `scene.camera`，单独调用会污染后续手工渲染）。
- **部分覆盖渲染参数**：`render_views` / `render_turntable` 只传 `samples`（或 `engine`/`resolution` 之一）时，未指定的参数继承当前场景值，不再硬编码回退 `CYCLES`/48/960（此前手工设成 EEVEE 的场景会被静默切回 CYCLES）。
- **Blender 子进程临时目录隔离**：`run_blender.py`（经 `bl_common.execute`）把 Blender 子进程的 `TMP`/`TEMP`/`TMPDIR` 指向 `<out>/logs/tmp-*`，结束后清理。Blender 4.0.2 在 session 临时子目录创建失败时会把基目录当 session 目录、退出时递归清空它——此前基目录是系统 `%TEMP%`，可能清空系统临时目录并表现为莫名的 `TIMEOUT`（上游 2025-08 才修复，见 #139585）。
- **`check_output.py` 导出候选定位**：规范名候选改回 `exports/model.<ext>`（此前拼成 `exports/blend`），`exports/` 里排序靠前的损坏文件不再遮蔽合法的 `exports/model.blend`（假「魔数不对」）；report 缺导出记录时改为报「report 缺少 blend/glb 导出记录」，不再误报「相对路径: None」。宽松的 exports 目录扫描能力保留。
- **模板 `preview.denoise`**：`templates/model_template.py` 的 `PARAMS.render.preview.denoise` 现在真正生效（此前是死参数，设 `False` 不关降噪）。

### 测试

- `tests/kit_regression.blender.py` 53 → 63 项（新增 F20–F25：views 字符串/空列表、`render_still` 状态恢复、VERTICAL/AUTO 取景角点、部分覆盖保持引擎）。
- `scripts/check_output.py --selftest` 新增 4 项（规范名不被同目录损坏文件遮蔽、缺导出记录文案、不误报相对路径、非规范文件名仍能被 exports 扫描定位）。
- `tests/test_bl_common.py` 新增 2 个用例：子进程 `TMP`/`TEMP`/`TMPDIR` 被隔离到 `<out>/logs/tmp-*` 且结束后清理；隔离目录创建失败时降级为 WARN 并继续执行。

## [1.1.0] - 2026-10-19

一次系统性审计（两位独立审计员 + 全量回归）后的修复与增强版本。目标是让「交付出去的资产」和「闸门说的话」都可信。

### 新增

- `lib/blender_kit.py` 新增 `open_blend(path)`：打开已有 `.blend` 继续编辑/重渲/重导出，配合新模板支持「改模型」请求。
- `templates/edit_model_template.py`：修改已有模型的工作流模板（位移/旋转/缩放、换材质、隐藏已有对象，再重新渲染导出）。
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
