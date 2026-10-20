# 效果预览图（docs/previews）

这四张图由 `blender-modeling` 技能自身流程生成：解析提示词 → 写 `model.py` → Blender 无头多角度渲染 → `read_image` 看图迭代定稿，再把两个代表题材的 960×960 终渲图拼合成一张（左/右各一个题材，下方中文标签）。

| 文件 | 领域文档 | 左：题材 | 右：题材 | 演示工程（临时目录，未入库） |
| --- | --- | --- | --- | --- |
| `architecture.png` | [建筑](../../references/architecture-modeling.md) | 双层联排住宅（13 对象 / 1176 tris / full 157.70 s） | 石拱桥（10 对象 / 900 tris / full 183.76 s） | `.tmp/domain/arch/blender-models/` |
| `character.png` | [人物](../../references/character-modeling.md) | Q 版人物 3 头身（7 对象 / 2790 tris） | 招手人物 4.8 头身（8 对象 / 4052 tris） | `.tmp/domain/char/` |
| `animal.png` | [动物](../../references/animal-modeling.md) | 低模猫（6 对象 / 2308 tris） | 展翅海鸥（6 对象 / 2036 tris） | `.tmp/domain/animal/` |
| `plant.png` | [植物](../../references/plant-modeling.md) | 阔叶树（6 对象 / 624 tris） | 花坛（6 对象 / 3558 tris） | `.tmp/domain/plant/` |

- 所有演示产物都通过 `scripts/check_output.py` 交付闸门：`27 PASS / 0 ERROR / 0 WARN`（石拱桥为 `31 PASS`，因为它多一张 hero 终渲）。
- 原图为 960×960（CYCLES CPU，48 samples）；预览图缩放到 560×560 后拼合、PNG 无损压缩，单张约 450 KB。
- 拼图脚本属于一次性产物，不随仓库发布；重新生成时准备同样结构的 `renders/final-*.png` 即可。
- 想看完整多视角渲染与逐轮迭代记录，读对应领域文档的 §10「实测记录」，或按文档 §5 的配方骨架在自己机器上重跑。
