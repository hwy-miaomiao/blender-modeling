# 报错与排障知识库（本机实测）

> 用于 `AGENTS.md` 第 15 节"错误定位三步"之后的查表。每条按 **症状 / 原因 / 解决 / 验证** 四段写。
> 环境：Windows + Blender 4.0.2（`C:\Program Files\Blender Foundation\Blender 4.0\blender.exe`）+ system Python 3.12 + kit。
> 标注 **【实测】** 的条目在本机复现并记录了证据；标注 **【待验证】** 的条目是通用经验，本机未复现，使用前先小样本确认。
> 编号 `T-*` 供 `AGENTS.md` 与 `render-and-check.md` 交叉引用。

## A. 环境与命令行

### T-1 run_blender.py 找不到 Blender

- **症状**：`[run_blender] Blender: ...` 行不存在或报"未找到 Blender / can not find blender"；退出码 1。
- **原因**：`--blender` 未给、`BLENDER_EXE` 未设，且 PATH/常见安装路径里没有 `blender.exe`。
- **解决**：`python scripts/run_blender.py --script ... --out ... --blender "C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"`；或会话内 `$env:BLENDER_EXE = "C:\...\blender.exe"`。
- **验证**：输出第一行出现 `[run_blender] Blender: <路径> (4.0.2)`；`BM_RESULT` 里 `blender_version` 为 `4.0.2`。

### T-2 doctor.py 报 ERROR（缺 kit / 模板 / references）

- **症状**：`[FAIL]` 行 + 末尾 `=== 结果: N PASS / M ERROR ===`，退出码 1，提示"技能当前不可用"。
- **原因**：`lib/blender_kit.py`、`templates/model_template.py`、`references/` 内容或 `scripts/` 缺失。
- **解决**：按 FAIL 提示补齐技能文件；确认 `<技能目录>` 是 SKILL.md 所在目录（不要在错误目录跑）。
- **验证**：重跑 `python scripts/doctor.py` 得到 `0 ERROR`、退出码 0；必要再跑 `--smoke` 确认 64×64 CYCLES 端到端 PASS。

### T-3 日志是乱码 / read 工具读不了日志

- **症状**：`logs/*.log` 用 read 工具打开提示 binary 或内容全是 `\x00` 或方块；编辑器看正常。
- **原因**：PowerShell 的 `*>` / `Out-File` 默认写 UTF-16LE（BOM `FF FE`）；Blender 自身 stdout 是 UTF-8。
- **解决**：优先用 run_blender.py 生成的日志（UTF-8 写入）；自己用 PowerShell 落日志时加 `-Encoding utf8`，或改用 `& blender.exe ... | Tee-Object` 避免 `*>`。
- **验证**：`Get-Content <log> -Encoding utf8 | Select-Object -Last 5` 能正常显示中文；read 工具可读。

### T-4 TBBmalloc 噪音污染错误判断

- **症状**：控制台/日志出现 `blender.exe : TBBmalloc: skip allocation functions replacement in ucrtbase.dll: unknown prologue for function _msize`，PowerShell 还把它包装成 `NativeCommandError`，看起来像命令失败。
- **原因**：Blender 自带 TBB 的 malloc 替换在本机 ucrtbase.dll 上探测失败，属**无害启动噪音**（stderr 输出，进程仍正常）。
- **解决**：忽略；不要据此判断构建失败。判断成败只看退出码与 `BM_RESULT.ok`。
- **验证**：`BM_RESULT` 的 `errors` 为空、`ok:true`（run_blender 已过滤该行）。

### T-5 路径含空格 / 中文导致命令失败

- **症状**：`'C:\Program' 不是内部或外部命令`；或脚本报 file not found。
- **原因**：工作区路径为 `F:\DeepSeek Harness`（含空格），PowerShell/命令行未加引号。
- **解决**：所有路径加双引号（`"$OUT\model.py"`）；PowerShell 调程序用 `& "C:\Program Files\..."`；脚本内用 `os.path.join` 而非字符串拼接。
- **验证**：命令回显路径被引号包住；run_blender 的 `[run_blender] out=` 行路径完整。

## B. bpy / context / addon

### T-6 `RuntimeError: Operator bpy.ops.object.mode_set.poll() Context missing active object`

- **症状**：【实测】空场景下调用 `bpy.ops.object.mode_set(mode="EDIT")` 抛该错误。
- **原因**：`bpy.ops` 依赖 `context.view_layer.objects.active` 与选中集，headless 下不会自动设置。
- **解决**：先设 active + select 再调用：

```python
import bpy
obj = bpy.data.objects["mug"]
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")   # 实测 FINISHED
```

另一种更稳的做法：用 `bmesh` 直接改网格，不进编辑模式（见 T-11）。注意**并非所有 op 都抛错**：实测 `origin_set`/`join`/`transform_apply`/`modifier_apply`/`mesh.delete` 在无选中时可能静默返回 `CANCELLED` 而不报错，所以"没报错"不等于"改成功了"。
- **验证**：调用前 `print(bpy.context.active_object)` 非 None；op 返回 `{'FINISHED'}`；改完后用 `len(mesh.vertices)` 或 `mesh_stats(obj)` 核对数量变化。

### T-7 `--factory-startup` 下插件状态

- **症状**：担心 glTF/STL/FBX 导出不可用；或误以为要手动 enable addon。
- **原因**：【实测】4.0.2 的 factory startup 默认启用 `cycles`、`io_scene_gltf2`、`io_scene_fbx`、`io_mesh_stl`、`io_scene_x3d` 等；`--factory-startup` 只是忽略用户偏好，不关闭这些内置 addon。
- **解决**：直接调用；若确实调不到，按 op 名检查（`hasattr(bpy.ops.export_scene, "gltf")`），不要盲目 `addon_utils.enable`。
- **验证**：`bpy.ops.export_scene.gltf(...)` 返回 `{'FINISHED'}` 且 glb 文件 magic 为 `glTF`。

### T-8 渲染全黑 / 纯色图

- **症状**：PNG 全黑或接近纯色；`report.json.renders[].black_ratio ≈ 1.0`、`std < 4`、文件约 9 KB。或渲染直接抛 `RuntimeError: Error: Cannot render, no camera`。
- **原因**（按实测签名区分）：
  1. `reset_scene()` 后 **world 可能为 None**（`read_factory_settings(use_empty=True)` 实测 `bpy.data.worlds` 为空），且无灯 → 全黑（mean≈0.4/std≈0.49/black_ratio=1.0）。
  2. 有灯但无 world → 很暗（mean≈15/std≈52/black_ratio≈0.924）。
  3. 相机落在物体内部 → 统计与全黑完全相同（mean≈0.4/std≈0.49/black_ratio=1.0）。
  4. `scene.camera` 为 None → 抛 `Cannot render, no camera`，不出图。
- **解决**：用 `setup_scene()`（内含相机+三灯+world+floor）或分别调 `setup_world()`+`setup_studio_lights()`+`add_camera()`；确认相机位置在物体外；确认 `setup_render`/`render_*` 调用前相机已存在。
- **验证**：`BM_RESULT.renders` 有 3 项、每张 > 15 KB；`report.json` 中 `black_ratio < 0.98` 且 `std > 4.0`；肉眼在 `view-iso.png` 能看到主体。

### T-9 中文字符渲染成空白/文字消失

- **症状**：`text()` 建的文字对象里中文完全消失或只剩几段；转 mesh 后顶点数极少/为 0。
- **原因**：【实测】默认字体 `Bfont Regular` **不含中文字形**：body="中文测试" 转 mesh 得 **0 顶点**（静默失败、不报错），而 "ABC" 得 860 顶点（口径：kit `text()` 默认 `size=1`、`extrude=0.05` 后 convert）。
- **解决**：加载系统字体再转 mesh：

```python
import bpy
txt = bpy.data.objects["label"]
font = bpy.data.fonts.load(r"C:\Windows\Fonts\simhei.ttf")  # 黑体，实测可用
txt.data.font = font
txt.data.body = "中文测试 ABC"
bpy.context.view_layer.objects.active = txt
txt.select_set(True)
bpy.ops.object.convert(target="MESH")  # 实测 FINISHED，7464 顶点
```

  实测可用字体（口径：kit `text()` 默认 `size=1`、`extrude=0.05`，body="中文测试 ABC" 转 mesh）：`C:\Windows\Fonts\simhei.ttf`（7464 顶点）、`msyh.ttc`（4496 顶点）。`msyh.ttc` 是 TTC 集合，个别环境不认，优先 simhei.ttf。
- **验证**：转 mesh 后 `len(obj.data.vertices) > 0`；`report.json` 中对象类型为 MESH；渲染图中文字完整。

### T-10 文字对象导出到 glb 后类型变化

- **症状**：重新导入 glb 后文字对象变成 MESH。
- **原因**：【实测】glTF 不支持 Blender 的 FONT 对象，导出时自动烘焙成 MESH（重新导入得到 `('Text','MESH')`），这是正常行为。
- **解决**：无需处理；若需保留可编辑文字，保留 `.blend`。
- **验证**：`bpy.ops.import_scene.gltf(filepath=...)` 后对象类型为 MESH 且几何在。

## C. 导出

### T-11 glTF 导出参数

- **症状**：导出的 glb 缺相机/灯光/应用修改器；或选了某个物体却导出全场景。
- **原因**：`export_scene.gltf` 默认只导几何与材质，相机/灯光默认关；修改器默认不应用。
- **解决**：按需传参（【实测】这些参数在 4.0.2 存在且生效）：

```python
bpy.ops.export_scene.gltf(
    filepath=path,
    export_format="GLB",          # GLB 单文件（嵌入）
    export_apply=True,            # 应用修改器
    use_selection=True,           # 只导选中（需先 select）
    export_cameras=True,
    export_lights=True,
    export_normals=True,
    export_texcoords=True,
    export_materials="EXPORT",
)
```

- **验证**：文件 magic 为 `glTF`、大小 > 1 KB；重新导入后 `object_count` 与预期一致；`BM_RESULT.exports` 含 `exports/model.glb`。

### T-12 用 `bpy.ops.export_scene.obj` 报错：operator could not be found

- **症状**：【实测】`AttributeError: Calling operator "bpy.ops.export_scene.obj" error, could not be found`。
- **原因**：Blender 4.0 移除了旧 OBJ 导出 API（`export_scene.obj`），改为 `wm.obj_export`。
- **解决**：改用 `bpy.ops.wm.obj_export(filepath=..., export_selected_objects=True, apply_modifiers=True, export_materials=True)`；或直接调 kit 的 `export_obj(path)`。
- **验证**：返回 `{'FINISHED'}`；生成 .obj 文件存在且非空。

### T-13 导出文件过小 / 为空

- **症状**：`check_output.py` 报导出文件过小或缺失；glb 只有几百字节。
- **原因**：导出时场景为空（`reset_scene` 后没建东西就导出）、只导选中但没选中、导出路径目录不存在。
- **解决**：确保导出在 `build()` 之后；用 `export_all(EXPORTS_DIR, stem="model")` 固定导出 blend+glb；目录不存在时先 `os.makedirs(EXPORTS_DIR, exist_ok=True)`（kit 一般会建，但自建最稳）。
- **验证**：`.blend` 大于几十 KB（最小场景实测约 408 KB）、`.glb` 至少几 KB；`report.json.exports` 记录齐全。

## D. 几何与修改器

### T-14 布尔运算无效（结果没变化且不报错）

- **症状**：【实测】用 `plane`（单面，默认 `size=2 m`；改成 1 m 时 z=0.50 会切到）当 cutter 做 DIFFERENCE，cube 仍是 8 顶点/6 面，无报错。
- **原因**：布尔要求 cutter 是**闭合实体**（有体积）；单面片没有内外，EXACT 求解器直接忽略。
- **解决**：cutter 用 `cube`/`cylinder` 等实体，并确保与目标有真实重叠；`add_boolean(obj, cutter, operation="DIFFERENCE", solver="EXACT", apply=True)`；失败就降级用图元叠加/倒角（`AGENTS.md` 15.2）。
- **验证**：结果 `mesh_stats(obj)` 的 verts/polys 变化符合预期；切面在预览图中可见。

### T-15 非流形（non-manifold）检测口径

- **症状**：`mesh_stats(obj)["non_manifold_edges"]` 不为 0；不知道这数字怎么算、要不要修。
- **原因**：非流形边 = 该边连接的**面数不是 2**（边界边、三面共享边、孤立边）。【实测】bmesh 三种口径一致：删除 cube 一个面后，`sum(e.is_boundary)` = 4、`not e.is_manifold` = 4、`len(e.link_faces) != 2` = 4。
- **解决**：低多边形渲染不要求全封闭，开放底面/开口杯**允许存在边界边**（边界边也是非流形）；只有"三面共享/孤立边"才需要修。检测：

```python
import bmesh
bm = bmesh.new(); bm.from_mesh(obj.data)
bad = [e for e in bm.edges if len(e.link_faces) not in (1, 2)]
bm.free()
```

- **验证**：修复后 `len(bad) == 0`；或确认剩余非流形边全是 `is_boundary` 的开口边并写进 brief。

### T-16 法线翻转 / "黑面"

- **症状**：怀疑某部件法线反了；或看到暗色面片以为是黑面。
- **原因**：【实测】Cycles 是双面光照，把球面全反转后渲染统计与正常完全相同（mean 54.6/std 41.37/black_ratio 0），即**法线反不会直接变黑**；真正的黑面多来自无灯、材质未赋值、面重叠遮挡、金属无环境反射。
- **解决**：先排灯光/材质（T-8）；确需修正法线时用 bmesh 重算（【实测】可用）：

```python
import bmesh
bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(obj.data); bm.free()
```

- **验证**：渲染统计无明显变化；若原本暗面变亮，说明确实存在单面材质/背光问题，而不是法线方向问题。

### T-17 对象名出现 `.001` 后缀

- **症状**：`scene_report()["object_count"]` 比预期多、名字带 `.001`。
- **原因**：同名对象重复创建（Blender 自动加后缀）；多见于没调用 `reset_scene()` 或循环里固定名字。
- **解决**：`model.py` 起手 `reset_scene()`；循环建件时名字带编号（`f"leg_{i}"`）；最后 `join` 合并同组。
- **验证**：`report.json.materials`/对象列表无 `.001`；对象数在 3-20。

## E. 渲染与资源

### T-18 渲染超时 / 进程被杀

- **症状**：【实测】`run_blender.py --timeout 3` 超时 → 控制台 `[run_blender] ERROR: TIMEOUT: 超过 3.0s 未结束`，`BM_RESULT` 为 `ok:false, exit_code:-1, errors:["TIMEOUT: 超过 3.0s 未结束"]`，CLI 退出码 1，`logs/` 仍生成日志。
- **原因**：分辨率/采样过高、物体数过多、denoise 或大纹理、脚本卡在循环里；`--timeout` 默认 600 s。
- **解决**：先 `--stage build` 排除建模问题；预览降 512/16、WORKBENCH；终渲 `--timeout 900` 并确认单张 < 30 s；拆阶段跑。Windows 上被强杀的进程通常结算为退出码 1（无信号标记），不要当成脚本自身报错。
- **验证**：重跑后 `BM_RESULT.ok:true` 且 `duration_s` 在预期内；日志末尾无 `TIMEOUT`。

### T-19 EEVEE 在后台（headless）的初始化

- **症状**：EEVEE 渲染报 GPU/EGL 相关错误，或首张明显比后续慢。
- **原因**：【实测】本机 headless 下 EEVEE 可用：512×512 首次 0.79 s、进程内后续 0.47 s（含 GPU/GL 上下文初始化）；EEVEE 需要 GPU/OpenGL 上下文，远程桌面或纯软件环境可能初始化失败【待验证】。
- **解决**：默认用 CYCLES CPU（不受 GPU 影响）；必须用 EEVEE 时把首张耗时计入预算；失败则回退 CYCLES。
- **验证**：`BM_RESULT.renders` 有图且 > 15 KB；`report.json.engine` 为 `BLENDER_EEVEE`。

### T-20 Cycles 内存不足（大场景崩溃）

- **症状**：渲染中途进程退出/崩溃（无 Python traceback），或系统内存吃满。
- **原因**：面数/纹理/分辨率过大，Cycles 场景同步与 BVH 占用内存；本机未复现 OOM【待验证】。
- **解决**：降分辨率与采样、关闭 denoise 以外的重效果、减少物体与细分级别、先 `--stage build` 确认 `total_tris` 合理（低多边形 < 3000）；单次只渲一个相机视角排查。
- **验证**：任务管理器观察 Blender 内存峰值下降；`BM_RESULT.ok:true` 且渲染完成。

### T-21 脚本崩溃但日志看不出原因

- **症状**：退出码 1，日志末尾只有 `Error: script failed, file: '...', exiting.`。
- **原因**：Blender 以 `--python-exit-code 1` 运行；Python 未捕获异常会让整个进程退出码 1，真正错误在 Traceback 中间。
- **解决**：日志里搜 `Traceback (most recent call last):` 与最后一条 `RuntimeError`/`Error:`，定位到 `model.py` 行号；在可疑处临时加 `print` 或 `traceback.print_exc()`。
- **验证**：修复后 `BM_RESULT.errors` 为空；日志末尾是 `Blender quit` 且无 Traceback。

### T-22 材质全灰 / 颜色不对

- **症状**：渲染出来所有部件同色，或颜色明显偏暗/偏亮。
- **原因**：创建材质后忘了 `assign`/`assign_all`；或颜色用了 0-255 而 kit 期望 0-1；或金属度高、无环境反射。
- **解决**：`mat()` 的 RGB 用 0-1；每个对象 `assign(obj, m)` 或 `assign_all(objects, m)`；金属件补环境/灯光（T-8）。
- **验证**：`scene_report()["materials"]` 列出预期材质；预览图中至少两种颜色可区分。

### T-23 run_blender 已隔离子进程临时目录（防 Blender 4.0.2 清空 %TEMP%）

- **症状**：【实测】`run_blender.py` 莫名超时（420 s / 600 s 仍未结束），日志出现 `WARN (bke.appdir): ... tempdir_session_create: Could not generate a temp file name for '...\blender_XXXXXX', falling back to '<系统临时目录>\'`，随后大量 `Unable to delete file`；极端情况下系统 `%TEMP%` 被递归清空。
- **原因**：Blender 4.0.2 在无法创建 session 临时子目录时，把**基目录本身**当成 session 目录，退出时 `BKE_tempdir_session_purge()` 递归删除它。基目录若来自 `TMP`/`TEMP`，就等于递归清理系统临时目录（上游 #139585，2025-08 的 commit 87c4f47 才修；4.0.2 属未修复的老行为）。出现该缺陷时进程会卡在清理阶段，看起来像脚本超时。
- **解决**：`run_blender.py` 自 1.1.1 起（`bl_common.execute`）把 Blender 子进程的 `TMP`/`TEMP`/`TMPDIR` 指向 `<out>/logs/tmp-*`，运行结束就删除；即使触发缺陷，被清空的也只是这个一次性目录。手工直接调 `blender.exe` 时，自己设 `$env:TMP`/`$env:TEMP` 到专用临时目录。
- **验证**：日志里没有 `falling back`；`<out>/logs` 运行后只剩 `*.log`（没有 `tmp-*` 残留）；`BM_RESULT.ok:true` 且 `duration_s` 正常。

## F. 快速排查顺序（照着走）

1. `BM_RESULT.ok` 是否为 true？`errors` 里第一条是什么？
2. 打开 `log`，从末尾往上找 `Traceback` 与最后一条 `Error:`/`RuntimeError`。
3. 是 Python 报错 → 按 T-6/T-9/T-14/T-17 查；是渲染问题 → T-8/T-19/T-20；是导出问题 → T-11/T-12/T-13；是命令/环境 → T-1~T-5。
4. 同一类错误连续 2 次 → 停止硬试，按 `AGENTS.md` 15.2 走降级路径。
5. 单步卡超过 20 分钟 → 向 Lead 报卡点、已试方案、日志末 20 行与图片路径。
