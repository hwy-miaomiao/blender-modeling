# blender-modeling — 用 Blender 按提示词建模的 Agent Skill

给 DeepSeek Harness（以及其它支持 Agent Skill 的 AI 工具）用的技能：用户输入一句建模提示词，AI 生成 bpy 脚本、用本机 Blender 无头（headless）建模、渲染多角度预览、看图自检并迭代，最后交付可用的 3D 资产。

[![ci](https://github.com/hwy-miaomiao/blender-modeling/actions/workflows/ci.yml/badge.svg)](https://github.com/hwy-miaomiao/blender-modeling/actions/workflows/ci.yml)
· GitHub：[hwy-miaomiao/blender-modeling](https://github.com/hwy-miaomiao/blender-modeling)
· License：[MIT](LICENSE)
· 本机实测：Blender 4.0.2 + Windows，CYCLES CPU 预览约 1-2 秒/张

## 它交付什么

对一句提示词（如「做一个低多边形马克杯，暖色陶土质感」），产出一个目录：

```
<工作区>/blender-models/<slug>/
├── brief.md              # 建模简报：需求理解、假设、尺寸、风格
├── model.py              # 可复现的 bpy 建模脚本
├── renders/              # 多角度预览图（front / right / iso）
├── exports/
│   ├── model.blend       # 可在 Blender 里继续编辑
│   └── model.glb         # 可导入 Three.js / Unity / UE 等
└── report.json           # 场景统计 + 渲染统计 + 导出记录
```

## 安装（三选一）

**方式 A：项目级（推荐，本仓库已注册）**

```powershell
cmd /c mklink /J "F:\DeepSeek Harness\.dsh\skills\blender-modeling" "F:\DeepSeek Harness\blender-modeling"
```

**方式 B：用户级（所有项目可用）**

```powershell
# 把整个 blender-modeling 目录复制到：
C:\Users\<你>\.agents\skills\blender-modeling
```

**方式 C：从 GitHub 克隆到技能目录**

```powershell
git clone git@github.com:hwy-miaomiao/blender-modeling.git "$env:USERPROFILE\.agents\skills\blender-modeling"
# 或 HTTPS：git clone https://github.com/hwy-miaomiao/blender-modeling.git ...
```

技能目录要求包含 `SKILL.md`（带 `name` / `description` frontmatter），Harness 会自动发现。新增或修改技能后不需要重启。
本仓库的样例包含 `.blend` / `.glb` / PNG 预览（约 3 MB），克隆后即可离线查看效果。

## 前置依赖

- **Blender 4.x**（实测目标 4.0.2）。会自动在 PATH、`BLENDER_EXE` 环境变量、`C:\Program Files\Blender Foundation\` 下查找；也可在命令前设 `$env:BLENDER_EXE="...\blender.exe"`。
- **Python 3.9+**（系统 Python，跑 `scripts/*.py`；只用标准库）。
- 可选：**Pillow**（生成联系表 `contact-sheet.png`）。
- 无需 GPU：默认 CYCLES CPU 渲染，512px 预览每张 1-2 秒。

## 怎么用

在 Harness 里直接说「用 Blender 建一个 XXX 的模型」或输入 `/blender-modeling 低多边形马克杯`，AI 会按 `AGENTS.md` 的流程执行。

也可以手动跑：

```powershell
# 0. 体检（有 FAIL 先修环境）
python "F:\DeepSeek Harness\blender-modeling\scripts\doctor.py" --smoke

# 1. 执行建模脚本（build 阶段快速暴露 bpy 错误，full 阶段渲染+导出）
python "F:\DeepSeek Harness\blender-modeling\scripts\run_blender.py" `
  --script "blender-models\mug\model.py" --out "blender-models\mug" --stage full

# 2. 交付闸门（0 ERROR 才算过）
python "F:\DeepSeek Harness\blender-modeling\scripts\check_output.py" --out "blender-models\mug"

# 3. 可选：渲染图拼联系表
python "F:\DeepSeek Harness\blender-modeling\scripts\contact_sheet.py" --out "blender-models\mug"
```

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `SKILL.md` | 技能入口（Harness 加载它） |
| `AGENTS.md` | 完整工作规范：阶段 0-9、命令、验收条件、看图自检清单 |
| `scripts/run_blender.py` | 统一执行器：定位 Blender、注入 kit 路径、超时、日志、错误提取 |
| `scripts/doctor.py` | 环境体检（`--smoke` 跑端到端冒烟渲染） |
| `scripts/check_output.py` | 交付闸门（文件/魔数/渲染非全黑/report 统计） |
| `scripts/contact_sheet.py` | 渲染图拼联系表（可选，需要 Pillow） |
| `scripts/ci_check.py` | 仓库静态检查（frontmatter / 示例产物 / 文档引用 / 绝对路径；无需 Blender） |
| `lib/blender_kit.py` | 在 Blender 进程内 import 的辅助库（图元/材质/灯光相机/渲染/导出） |
| `templates/model_template.py` | 建模脚本骨架 |
| `references/` | 提示词解析、配方库、bpy 速查、渲染自检、报错知识库 |
| `examples/` | 两个完整实测样例（few-shot 参考） |

## 自测与 CI

改完脚本或文档后，先跑这两条（纯标准库，不需要 Blender，几秒完成）：

```powershell
python scripts\check_output.py --selftest   # 交付闸门的纯函数自测
python scripts\ci_check.py                  # 仓库静态检查，必须 0 ERROR
```

GitHub Actions（`.github/workflows/ci.yml`）在 Python 3.9 与 3.12 上跑同一套检查，外加 `compileall` 与
LF 行尾检查；它**不调用 Blender**，真实建模与看图验收在本地按 `AGENTS.md` 第 17 节闸门表完成。

## 常见问题

| 症状 | 处理 |
| --- | --- |
| `找不到 Blender` | 装 Blender 4.x，或设置 `BLENDER_EXE` 指向 `blender.exe` |
| 渲染全黑 / check_output 报 `std` 过低 | 检查相机是否对准物体、灯光是否启用、渲染是否落在空场景 |
| `Traceback` 连续出现 | 读 `run_blender.py` 输出里的 ERROR 行与日志尾部，按 `references/troubleshooting.md` 修 |
| Blender stderr 有 `TBBmalloc ... unknown prologue` | 正常噪音，忽略 |
| 渲染很慢 | 预览用 `--stage render` 或降分辨率/采样数；最终交付再提高质量 |

## 设计原则

- **两段式**：`--stage build` 只建模，1-2 秒暴露 API 错误；通过后再渲染，避免长时间试错。
- **可复现**：交付 `model.py` + 参数，任何人可在本机重跑出同一结果。
- **可验证**：渲染统计（std / black_ratio）与文件魔数由 `check_output.py` 自动把关，防止交付空场景或坏文件。
