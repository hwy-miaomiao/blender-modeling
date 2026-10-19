# office-chair — 低多边形办公转椅（实测样例）

本目录是 `--stage full` 跑通后的真实实测产物，同时作为 `model.py` 的 few-shot 参考。

## 演示什么

- 多部件建模：五星底座（循环写 5 条腿 + 5 个脚轮）、升降杆 + 防尘罩锥体、座垫、靠背、两侧扶手
- 按逻辑组 `join`（base / lift / seat / back / arms）并各自 `set_origin(BOTTOM)`；倒角后先 `apply_modifiers` 再 join
- 深色材质经验：强三点布光会把深色 albedo 抬亮，织物给到 0.05 级别才读得出「深色网布」

## 提示词原句与实测统计

> 「帮我做个低多边形办公转椅，深色网布坐垫和靠背，金属五星脚架带轮子，能看清扶手和升降杆。」

- `object_count=10`、`mesh_count=5`、`total_tris=1100`、`dimensions=0.625 × 0.638 × 0.952 m`（含底座与脚轮外沿）
- 3 张 512² CYCLES 渲染（16 samples + denoise）：std 50.2 / 49.8 / 31.6，black_ratio 全 0

## 目录与重跑

`model.py`（参数在 `PARAMS`）· `brief.md` · `renders/`（三视角）· `exports/model.blend` + `model.glb` · `report.json`（路径均相对本目录）

```powershell
python scripts/run_blender.py --script "<技能目录>\examples\office-chair\model.py" --out "<技能目录>\examples\office-chair" --stage full
```
`--stage full` 会重出 3 张 `view-*.png`、`exports/model.blend`、`exports/model.glb` 与 `report.json`。
