# lowpoly-mug — 低多边形马克杯（实测样例）

本目录是 `--stage full` 跑通后的真实实测产物，同时作为 `model.py` 的 few-shot 参考。

## 演示什么

- 最小标准流程：`reset_scene` → `setup_scene` + `setup_floor` → 图元建模 → `render_views` → `export_all` + `save_report`
- 布尔挖杯腔：cutter 必须带材质，否则布尔新面拿到非法材质索引（渲染串色）
- 倒角先 `apply_modifiers` 再 `join`（join 会丢非活动对象修改器）；多色部件建件时赋材质，join 后勿再 `assign`

## 提示词原句与实测统计

> 「做个低多边形马克杯，白色陶瓷杯身、蓝色底圈和杯柄，能打开杯口看到内壁。」

- `object_count=6`、`total_tris=1816`、`dimensions=0.154 × 0.145 × 0.099 m`（整体 yaw -35° 的 AABB；建模名义 0.125 × 0.090 × 0.099）
- 3 张 512² CYCLES 渲染（16 samples + denoise）：std 61.7 / 56.2 / 23.0，black_ratio 全 0

## 目录与重跑

`model.py`（参数在 `PARAMS`）· `brief.md` · `renders/`（三视角）· `exports/model.blend` + `model.glb` · `report.json`（路径均相对本目录）

```powershell
python scripts/run_blender.py --script "<技能目录>\examples\lowpoly-mug\model.py" --out "<技能目录>\examples\lowpoly-mug" --stage full
```
`--stage full` 会重出 3 张 `view-*.png`、`exports/model.blend`、`exports/model.glb` 与 `report.json`。
