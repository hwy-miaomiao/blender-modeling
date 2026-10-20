# 导出与接入：把模型交付到真正要用的地方

> 适用阶段：阶段 7（终渲与导出）、阶段 9（交付说明）。本文件回答三个问题：
> 导出哪些格式、每个格式有什么坑、拿到文件的人（引擎/网页/打印机）怎么用。
> 纯 API 与版本差异仍以 `references/bpy-cookbook.md` 和 `lib/blender_kit.py` 源码为准。

---

## 1. 导出函数速查

kit 的导出都在 §4.6，全部**自动补后缀、自动建父目录**，返回绝对路径（失败返回 `""` 并把原因记进 log 与 `report.json.warnings`）。

| 函数 | 产出 | 默认行为 | 备注 |
| --- | --- | --- | --- |
| `save_blend(path)` | `.blend` | 保存**完整场景**：模型 + 摄影棚地台 + 相机 + 灯光 | 给人继续编辑/重渲用；不是交付给引擎的资产 |
| `export_glb(path, include_floor=False)` | `.glb` | 只导出几何对象，**排除** `kit_role='floor'` 的摄影棚地台；不导出相机灯光；Y-up；米 | 网页/引擎首选 |
| `export_stl(path, include_floor=False)` | `.stl` | 二进制 STL、带修改器求值、排除地台 | 3D 打印；无材质、无单位 |
| `export_fbx(path, include_floor=False)` | `.fbx` | 带修改器、排除地台 | Unity/UE 传统管线 |
| `export_obj(path, include_floor=False)` | `.obj` + `.mtl` | 带修改器、材质/法线/UV | 老管线；`.mtl` 要跟 `.obj` 一起拷 |
| `export_all(out_dir, stem="model")` | `.blend` + `.glb` + `report.json` | 交付必需组合 | `report.json` 落在 `out_dir` 的**上一级**（即 `report_dir = dirname(exports)`） |

为什么默认排除地台：`setup_scene(floor=True)` / `setup_floor()` 会建一块摄影棚地台（边长为 `max(20, distance×5)` 米，`setup_scene` 的 `distance` > 4 时随之放大），仅为渲染取景和接地影服务。它是**场景道具，不是模型本体**，混进 `.glb` 会让下游看到一片巨大平面。确实需要连地台一起交付时传 `include_floor=True`。

```python
# 典型：只要模型（默认）
exported = export_all(EXPORTS_DIR, stem="model")

# 需要连摄影棚一起给（很少用，比如交付整个场景预览）
exported = export_all(EXPORTS_DIR, stem="model", include_floor=True)

# 只要某一个格式时单独调
export_glb(os.path.join(EXPORTS_DIR, "mug.glb"))
```

导出的位置必须与 `report.json` 一致：`report.json` 的 `renders[].path`、`exports.blend.path`、`exports.glb.path` **都是相对路径**（相对 `<输出目录>`），这样整个目录可以整体拷给别人。

---

## 2. 该交什么格式（按用途选）

| 用途 | 交这个 | 理由 |
| --- | --- | --- |
| 用户要在 Blender 里继续改 | `.blend` | 保留材质、灯光、相机、修改器历史 |
| 网页（Three.js / Babylon / model-viewer） | `.glb` | 单文件、自描述、含材质、主流库都支持 |
| 游戏引擎（Unity / UE / Godot） | `.glb` 或 `.fbx` | glTF 是标准；FBX 在 Unity/UE 里导入设置更成熟 |
| 3D 打印 | `.stl`（或 `.obj`） | 切片软件只吃网格；STL 最通用 |
| 老 DCC / 工业软件交换 | `.obj` / `.fbx` | 兼容性优先 |
| 预览/给非技术用户看 | `renders/*.png` | 不需要任何软件 |

一次交付的推荐组合：`.blend` + `.glb` + `renders/`（check_output 就是按这个口径卡闸门），打印需求再加 `.stl`。

---

## 3. 单位与坐标（最容易翻车的地方）

| 事实 | 说明 |
| --- | --- |
| 1 Blender unit = 1 米 | 全技能统一口径；`report.json.dimensions` 也是米 |
| 模型正面朝 **+Y**、Z 轴向上 | `view-front.png` 的相机在 +Y 侧看向原点 |
| `.glb` 导出时转成 **Y-up**（`export_yup=True`） | glTF 规范就是 Y-up；Three.js/Unity/Godot 导入后方向自然正确 |
| `.fbx` 导出保持 Blender 轴向（-Z forward / Y up），按 1 单位 = 1 米 | Unity 吃这套；UE 内部 1 单位 = 1 cm，导入后若明显偏小/偏大，用导入器的 Uniform Scale（一般 ×100）修正 |
| `.stl` **没有单位、没有材质、没有对象名** | 切片软件默认按 mm 解释数值。一个 0.09 m 高的马克杯在 STL 里数值是 0.09，进切片软件会变成 0.09 mm——需要把导入缩放设为 1000（或 ×1000），或在导出前 `scale_obj` 放大 1000 再导 |
| `.obj` 无单位（按约定用米） | 与 `.mtl` 成对；拷到别处必须两个文件一起 |

写 `brief.md` 时就把单位写清楚（`r=0.045 m`），交付说明里也写一句"本模型 1 单位 = 1 米"，下游就不会猜错。

---

## 4. 网页接入（Three.js）

`.glb` 是最省事的一条路：材质（base color / metallic / roughness）随文件走，不需要额外贴图。

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.01, 100); // near 要按米调小
camera.position.set(0.25, 0.2, 0.35); // 米：模型高约 0.1 m 时这个距离刚好
camera.lookAt(0, 0.05, 0);

new GLTFLoader().load('./model.glb', (gltf) => {
  scene.add(gltf.scene);               // 默认 Y-up、单位米，直接加即可
  // 需要自动居中/落地时：
  // const box = new THREE.Box3().setFromObject(gltf.scene);
  // const center = box.getCenter(new THREE.Vector3());
  // gltf.scene.position.x -= center.x;
  // gltf.scene.position.z -= center.z;
});
```

要点：

- 模型只有几厘米到几米时，**相机 `near`/`far` 与灯光强度都要按米级场景设置**（`near=0.01`），否则模型会被近裁剪面裁掉或黑成一片。
- 想要统一比例就在场景里包一层 `THREE.Group` 做缩放，不要改 glb 内部节点。
- 需要更小体积时用 `gltfpack` / Draco 压缩，但要在加载端注册对应 decoder。

## 5. 引擎接入

**Unity**：装了 glTFast（或 UnityGLTF）后直接把 `.glb` 拖进 Assets 即可；或用 `.fbx`，导入设置里保持 1 单位 = 1 米、勾选材质生成。`.glb` 的材质会按 glTF 的 metallic-roughness 转成 URP/HDRP 材质，纯色 PBR 一般不需要再修。

**Unreal Engine**：`.fbx` 走传统导入（若尺寸差 100 倍，注意 UE 单位是 cm）；UE 5.3+ 可用 Interchange 直接比 glTF。导入后材质是占位材质，需要手动指认或换成 UE 材质——纯色模型建议导入后自己建 Simple Material。

**Godot 4**：把 `.glb` 拖进项目，自动生成 Mesh + 材质场景；Y-up、米制与 Godot 一致，无需调整。

**Blender 自己**：`文件 → 导入 → glTF 2.0 (.glb/.gltf)` 即可复核导出结果；`.blend` 直接双击。

---

## 6. 3D 打印（STL）清单

1. 打印件应当是**单个封闭网格**：多个对象会分别落在同一原点，打印前先在切片软件里拼；更稳的是在 Blender 里 `join` 成一个物体再导。
2. 先看 `report.json` 的 `non_manifold_edges`：为 0 表示网格封闭、没有非流形边；不为 0 大概率有开放边/穿插，切片会出空腔或薄壁。
3. 法线方向：STL 只有三角面，法线反了切片软件可能把内外判反。kit 的图元法线正确；用 bmesh 自己造面时要记得 `bmesh.ops.recalc_face_normals`。
4. 单位×1000 的坑见 §3 表格。
5. 壁厚/细节：0.4 mm 喷嘴一般打不出 < 0.6 mm 的细节；模型里的倒角、文字 extrude 要在这个尺度以上。

```python
# 打印件：合并 + 检查 + 导出
solid = join([body, foot, handle], "mug_solid")
apply_modifiers(solid)
print(scene_report()["non_manifold_edges"])   # 期望 0
export_stl(os.path.join(EXPORTS_DIR, "mug.stl"))
```

---

## 7. 材质与贴图（当前能力的边界）

- kit 的 `mat()` 只做**纯色 Principled BSDF**（线性 Base Color + roughness/metallic/emission/alpha），导出到 glb 是 baseColorFactor + metallicFactor + roughnessFactor，**没有贴图**。
- 因此 glb 不需要额外图片、体积极小，也不会出现"贴图丢了一堆粉色材质"的经典问题。
- 需要贴图/纹理时，本技能不提供 UV 展开：请在 Blender 里手动 Smart UV Project + 贴图，或改用专门资产管线（如 `meshyai` 技能）。这时 `.glb` 会把图片内嵌进文件。
- 透明材质：`mat(..., alpha=0.35)` 生成半透明；导 glb 后依赖渲染器的 alpha blend 设置，网页端可能需要 `material.transparent = true`（Three.js 通常自动处理）。

---

## 8. 交付前检查（复制到交付说明里）

- [ ] `<输出目录>/exports/` 下有 `model.blend` 与 `model.glb`，两者都非空；需要打印时再加 `model.stl`。
- [ ] `report.json` 里 `renders` 与 `exports` 路径均为相对路径，且指向真实存在的文件。
- [ ] `.glb` 里没有摄影棚地台（`include_floor` 未显式开启时）；有引擎需求时对方能直接导入。
- [ ] `report.json.dimensions` 与 brief 尺寸表一致（误差 ≤ 10%），交付说明写了「1 单位 = 1 米」。
- [ ] 3D 打印需求：`non_manifold_edges == 0`，已在说明里写清需要 ×1000 单位换算。
- [ ] `python scripts/check_output.py --out "<输出目录>"` 0 ERROR。
