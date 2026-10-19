# CLAUDE.md

本项目的全部工作规范在 [`AGENTS.md`](./AGENTS.md)。请在开始任何工作前完整读取它，并严格按其中的阶段与校验闸门执行；
各阶段细节在 `references/` 目录，按 AGENTS.md 第 16 节的指引按需读取。

速记：模型必须由 `<输出目录>/model.py` 生成 · 每轮渲染后必须 `read_image` 真看图 · `doctor.py` 无 FAIL 且
`check_output.py` 0 ERROR 才能交付 · 产物只写 `<工作区>/blender-models/<slug>/`，禁止写进技能目录。

本地自测（纯函数，不需要 Blender；GitHub Actions 也跑这一套）：

```bash
python scripts/check_output.py --selftest
python scripts/ci_check.py
```

改了 `scripts/`、`lib/` 或模板后，先跑上面两条，再跑一次真实建模流程（`--stage full` + 看图）。
