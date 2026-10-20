# 提示词 → brief → 部件表 → 代码：量化建模方法

> 本文件是 `AGENTS.md` 第 4-5 节的展开说明，用于**阶段 1（提示词解析）与阶段 2（结构拆解）**。
> 读完 `AGENTS.md` 再读本文件；本文件只讲"怎么把一句话变成可执行参数"，命令与闸门以 `AGENTS.md` 为准。
> 所有尺寸单位为米（Blender 1 unit = 1 m），颜色为 0-1 RGB，角度为度。

## 1. 提示词解析五步法

拿到一句话提示词（例如"做个可爱一点的低多边形马克杯，放在桌面上"）按顺序拆：

| 步 | 问自己 | 落到 brief 的哪里 | 缺失时怎么办 |
| --- | --- | --- | --- |
| 1 对象 | 到底做什么物件？单件还是场景？ | `## 一句话目标` | 对象不明确是**唯一允许追问**的情况（问 1 个问题） |
| 2 风格 | 低多边形/卡通/写实/硬表面？ | `## 风格与量化参数` | 用第 2 节默认映射；无风格词 = 低多边形卡通 |
| 3 尺寸 | 真实尺度大约多少？关键比例？ | `## 尺寸（米）` | 查第 7 节默认值表 |
| 4 颜色材质 | 主色/辅色/材质感觉？ | `## 颜色与材质` | 按风格给安全色板（第 8 节） |
| 5 场景 | 要不要地台/道具/文字？ | `## 结构四层` 场景层 | 默认只留地台，其余不加 |

**硬规则**

- 默认不追问；每个没被用户指定的决定都必须写进 `## 假设与默认决策`，一条不落。
- 提示词里每个形容词都要落到**可执行参数**（分段数、圆角宽度、比例、粗糙度、饱和度），不能只抄形容词。
- 一句话多物件时选用户最强调的一个为主体，其余进场景层或明确说明"本轮只做主体"。

## 2. 模糊词 → 可执行参数映射

### 2.1 风格词量化表

| 用户说法 | 比例策略 | 圆角/倒角 | 分段数 | 材质参数 | 面数预算 |
| --- | --- | --- | --- | --- | --- |
| 可爱 / cute | 头大身短、部件粗短（宽高比 0.8-1.2 的圆胖化） | 大圆角 `add_bevel` 宽 = 尺寸 3-5%，segments 2-3 | 球 16/8，圆柱 12-16 | 高饱和主色（S≈0.5-0.7）、粗糙度 0.4-0.6、金属度 0 | < 1500 tris |
| 低多边形 / low-poly | 比例写实但几何简化 | 小倒角或无（`add_bevel` 宽 = 尺寸 1-2%，segments 1） | 圆柱 8-16，球 12/6-16/8，**开 shade_flat** | 纯色平涂、粗糙度 0.5-0.8、无纹理 | 300-3000 tris |
| 卡通 / stylized | 夸张 1.2-2 倍特征部位（鼻子/耳朵/轮子） | 中圆角（2-4%，segments 2） | 球 24/12，圆柱 16-24 | 中饱和、粗糙度 0.4-0.7，可有 1 个发光点缀 | 1500-8000 tris |
| 写实 / realistic | 严格真实比例（误差 ≤ 5%） | 倒角 + shade_smooth（angle 30-40°） | 圆柱 32-64，球 32/16+ | 粗糙度分区间（0.2-0.9）、金属度按材质、颜色低饱和 | 8000-100000 tris |
| 科幻 / 硬表面 | 方块化、切角、非对称附件 | 切角 bevel 1-2%，segments 1-2，**shade_flat** | 圆柱 16-24，立方体为主 | 深灰金属（金属度 0.8-1，粗糙度 0.2-0.4）+ 发光条 `emission` | 2000-20000 tris |
| 复古 / 怀旧 | 稍矮胖、对称 | 小圆角 1-2% | 圆柱 12-20 | 低饱和土色、粗糙度 0.6-0.9、金属度 0 | 1000-5000 tris |
| 极简 / minimal | 细长比例、留白多 | 小圆角或直角 | 圆柱 16-24，球 24/12 | 单色 + 白/灰、粗糙度 0.3-0.5 | 500-3000 tris |
| 自然 / organic | 不规则但不写实 | 用 `add_displace` 轻微起伏（strength = 尺寸 1-2%） | 球 24/12，圆柱 12-16 | 绿/棕/土色、粗糙度 0.7-0.9 | 1500-8000 tris |

### 2.2 常用形容词 → 参数

| 形容词 | 参数化动作 |
| --- | --- |
| 圆润 / 胖乎乎 | 圆角 = 短边 4-8%；`add_subsurf` levels=1（低多边形不推荐） |
| 棱角分明 | 关闭 shade_smooth；`shade_flat`；倒角 segments=1 |
| 精致 | 加 1-2 个细节层部件（螺丝/接缝），倒角 segments 2-3 |
| 发光 | `mat(..., emission=(r,g,b), emission_strength=2-8)`，值 > 1 才在 AgX 下明显 |
| 金属感 | `metallic=0.8-1.0`，粗糙度 0.2-0.45；同时必须有环境/灯光否则发黑 |
| 磨砂 / 塑料 | 粗糙度 0.6-0.9，金属度 0 |
| 透明 | `mat(..., alpha=0.3-0.6)`；仅 EEVEE/正确混合设置下稳定，低多边形默认不用 |
| 大 / 巨大 | 目标高度 ×1.5-2；把 `setup_scene(distance=...)` 按比例放大（布光半径 = max(distance×0.8, 1.0)，三视角取景由 `render_views` 自动完成，不靠 distance）。注意 `setup_scene` 的灯光能量固定 500/150/300，不随 distance 缩放；需要更强补光时改用 `setup_scene(studio=False)` 后手动 `setup_studio_lights(center=..., radius=distance*0.8, key_energy=...)`（能量与距离² 成正比，距离翻倍约 ×4） |
| 迷你 / 小 | 目标高度 ×0.3-0.5；相机距离同步缩小，注意景深 |

**原则**：一个形容词最多映射到 2 个参数组；映射越多越难验收。写进 brief 时必须带数字。

## 3. brief.md 模板

用 write 工具写到 `<输出目录>/brief.md`（禁止 shell 重定向）。复制下面的模板填空：

```markdown
# <slug> 建模简报

## 需求原句
> 用户原话：<逐字贴提示词>

## 一句话目标
用 <风格> 做 <物件>，主体高约 <H> m，<用途>；本轮只做 <范围>。

## 风格与量化参数
| 风格词 | 量化决定 |
| --- | --- |
| 可爱 | 头身比 1.1:1；圆角 4%；球 16/8；主色饱和 0.6 |
| 低多边形 | 圆柱 12 段；shade_flat；总三角面 < 1500 |

## 尺寸（米）
| 部位 | 尺寸 | 依据 |
| --- | --- | --- |
| 总高 | 0.10 m | 常见马克杯 0.09-0.11 |
| 主体直径 | 0.09 m | 高径比约 1:1.1 |
| 杯柄外径 | 0.06 m | 约为杯高 2/3 |

## 颜色与材质
| 部位 | 颜色 RGB(0-1) | 粗糙度 | 金属度 | 其他 |
| --- | --- | --- | --- | --- |
| 杯身 | (0.92,0.92,0.90) | 0.35 | 0.0 | — |
| 描边装饰 | (0.20,0.45,0.75) | 0.45 | 0.0 | — |

## 结构四层
- 主体层：杯身（1 件）
- 附件层：杯柄（1 件）
- 细节层：杯口倒角、底部圆角（2 件）
- 场景层：地台（kit setup_floor 自带），不加道具

## 部件表
| 编号 | 部件 | 层 | 图元/构造 | 尺寸(m) | 位置/旋转(m,°) | 材质 | 修改器 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | body | 主体 | cylinder | r=0.045 h=0.09 | (0,0,0.045) | mug_white | add_bevel 0.002 | — |
| P02 | handle | 附件 | torus 半圈 | R=0.030 r=0.006 | (0.048,0,0.05) rotY=90 | mug_white | join→P01 | P01 |

## 假设与默认决策
1. 用户未指定颜色 → 按"可爱"给暖白主色 + 蓝色点缀。
2. 用户未指定用途 → 按摆件建模，不加液面/茶包。
3. 用户未指定尺寸 → 按常见陶瓷马克杯 0.09 m 高。

## 环境
| 项 | 值 |
| --- | --- |
| Blender / Python | Blender 4.0.2 headless bpy；Python 3.12（kit 要求 3.9+） |
| kit | `lib/blender_kit.py` 1.1.0（`scripts/doctor.py` 0 ERROR） |
| WARN | 0 WARN（`doctor.py` 的每条 WARN 原样记在这里） |

## 验收标准
- [ ] 三视角渲染图主体完整、比例与尺寸表误差 ≤ 10%
- [ ] 杯柄与杯身贴合，无悬空/穿模
- [ ] check_output.py 0 ERROR；报告 total_tris < 1500

## 迭代记录
| 轮次 | 问题（证据） | 改了什么 | 重跑结果 |
| --- | --- | --- | --- |
```

**brief 自检**：11 个小节齐全（含 `## 环境`）；尺寸表每个数字都带 `m`；假设至少 1 条；部件表 9 列；验收标准可判定（有数字或可看图判定）。

## 4. 四层结构拆解

### 4.1 分层判据

| 层 | 判据（满足即归入） | 数量建议 | 建模时机 |
| --- | --- | --- | --- |
| 主体层 | 去掉它物件就不成立、决定整体轮廓 | 1-3 | 最先写、先渲染 |
| 附件层 | 功能必须件（杯柄、轮子、门、机械臂） | 2-6 | 主体 build 通过后 |
| 细节层 | 提升辨识度但可省略（螺丝、按键、倒角、贴片） | 0-8 | 首轮预览通过后 |
| 场景层 | 地台、道具、背景、文字标牌 | 0-3 | 最后 |

### 4.2 拆解纪律

1. 每个部件必须能落到一次 kit 图元调用（或一段 bmesh 构造）；拆不出图元的部件不算数。
2. 主体不通过 build + 三视角预览，不许写附件层；依次推进，避免一次堆 15 个部件后无从排错。
3. 同逻辑组（如"四条腿"）先用一个图元建一条，再 `duplicate` 或循环建其余，最后 `join` 成组并 `set_origin(group, "BOTTOM")`。
4. 部件总数 ≤ 15（低多边形默认）；超了就把细节合并成材质色块或直接砍掉。
5. 场景层默认只用地台（`setup_scene(floor=True)`）；加道具必须写进 brief 的理由。

### 4.3 部件表填写示例（机器人）

| 编号 | 部件 | 层 | 图元/构造 | 尺寸(m) | 位置/旋转(m,°) | 材质 | 修改器 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | torso | 主体 | cube 1.0×0.45×0.6 | 0.45×0.45×0.60 | (0,0,0.75) | metal_gray | bevel 0.02/2 | — |
| P02 | head | 主体 | cube 0.35³ | 0.35×0.35×0.35 | (0,0,1.22) | metal_gray | bevel 0.03/3 | P01 |
| P03 | eye_l/eye_r | 细节 | sphere r=0.045 | d=0.09 | (±0.09,-0.18,1.24) | eye_glow | — | P02 |
| P04 | arm_l/arm_r | 附件 | cylinder r=0.05 h=0.35 | d=0.10 h=0.35 | (±0.30,0,0.80) rotZ=±12 | metal_dark | bevel 0.01/1 | — |
| P05 | leg_l/leg_r | 附件 | cylinder r=0.06 h=0.45 | d=0.12 h=0.45 | (±0.12,0,0.225) | metal_dark | shade_smooth | — |
| P06 | antenna | 细节 | tube 3 点 + sphere | r=0.008，球 r=0.02 | (0,0.05,1.45) | accent_red | — | P02 |
| P07 | floor | 场景 | setup_floor | 20×20 | z=0 | floor_gray | — | — |

## 5. 三个完整示例

### 示例 A：低多边形马克杯

**提示词**：`做一个可爱的低多边形马克杯，白色带蓝色点缀，放在桌面上`

**量化决策**：高 0.09 m、直径 0.09 m；圆柱 24 段（主体较大取 24）、杯柄 torus 12×8；圆角 0.002（约短边 2%）；主色暖白、点缀蓝；总面数目标 < 1200。

**brief 关键值**：总高 0.09；杯身 r=0.045 h=0.09；杯柄 R=0.030 r=0.006，中心高 = 0.55×杯高；相机 target=(0,0,0.045)、distance=3.0、lens=50。

**代码结构**（`model.py` 的 `build()` 部分，kit 调用全部来自 `lib/blender_kit.py` 公开 API）：

```python
def build():
    reset_scene()
    setup_scene(target=(0, 0, 0.045), distance=3.0, lens=50)
    white = mat("mug_white", color=(0.92, 0.92, 0.90), roughness=0.35)
    blue = mat("mug_blue", color=(0.20, 0.45, 0.75), roughness=0.45)
    body = cylinder("mug_body", radius=0.045, depth=0.09, vertices=24,
                    location=(0, 0, 0.045), material=white)
    add_bevel(body, width=0.002, segments=2)
    handle = torus("mug_handle", major_radius=0.030, minor_radius=0.006,
                   location=(0.048, 0, 0.05), rotation=(90, 0, 0), material=white)
    mug = join([body, handle], "mug")
    set_origin(mug, "BOTTOM")
    assign(mug, white)
    stripe = cylinder("mug_stripe", radius=0.0455, depth=0.012, vertices=24,
                      location=(0, 0, 0.078), material=blue)
    assign(mug, white)
    return mug
```

> 注意：`assign(mug, white)` 在 `join` 后整体赋一次即可；`cylinder` 的 `location` 是几何中心，所以杯身 z 取 高/2、杯柄 z 取 高×0.55。装饰环半径比杯身大 0.0005 m 防止共面闪烁。

**常见坑**：杯柄 torus 直接用默认朝向会立在杯身侧面（环面在 XY 平面），必须 `rotation=(90,0,0)` 让它竖起来；杯口不要用布尔挖空——低多边形用"深色顶面/杯口圆环"表达即可。

### 示例 B：卡通机器人

**提示词**：`做一个卡通机器人，站姿，方脑袋，红色天线，金属灰机身，低多边形风格`

**量化决策**：总高 1.6 m（人形尺度）；方头 = 立方体 + 3 段大倒角；机身略宽（0.45×0.28×0.60）；手臂圆柱 16 段、腿 16 段；金属灰 `metallic=0.85, roughness=0.3`；天线红色发光 `emission_strength=3`；总面数 < 3000；`shade_flat` 表现低多边形。

**brief 关键值**：脚底 z=0（着地），腿高 0.45、机身中心 z=0.75、头中心 z=1.22、天线到 1.45；相机 target=(0,0,0.8)、distance=4.5。

**代码结构**：

```python
def build():
    reset_scene()
    setup_scene(target=(0, 0, 0.8), distance=4.5, lens=50)
    metal = mat("robot_metal", color=(0.55, 0.57, 0.60), roughness=0.30, metallic=0.85)
    dark = mat("robot_dark", color=(0.18, 0.19, 0.22), roughness=0.45, metallic=0.60)
    glow = mat("robot_glow", color=(0.55, 0.05, 0.05), roughness=0.30,
               emission=(1.0, 0.15, 0.10), emission_strength=3.0)

    torso = cube("robot_torso", size=(0.45, 0.28, 0.60), location=(0, 0, 0.75), material=metal)
    add_bevel(torso, width=0.02, segments=2)
    head = cube("robot_head", size=(0.35, 0.32, 0.32), location=(0, 0, 1.22), material=metal)
    add_bevel(head, width=0.03, segments=3)
    eye = sphere("robot_eye", radius=0.04, segments=16, rings=8,
                location=(0, -0.17, 1.24), material=glow)
    arm_l = cylinder("robot_arm_l", radius=0.05, depth=0.35, vertices=16,
                     location=(0.30, 0, 0.80), rotation=(0, 12, 0), material=dark)
    arm_r = duplicate(arm_l, "robot_arm_r", location=(-0.30, 0, 0.80))
    leg_l = cylinder("robot_leg_l", radius=0.06, depth=0.45, vertices=16,
                     location=(0.12, 0, 0.225), material=dark)
    leg_r = duplicate(leg_l, "robot_leg_r", location=(-0.12, 0, 0.225))
    antenna = tube("robot_antenna", points=[(0, 0.02, 1.38), (0, 0.02, 1.45)],
                   radius=0.008, resolution=6, material=dark)
    tip = sphere("robot_antenna_tip", radius=0.02, segments=12, rings=6,
                 location=(0, 0.02, 1.45), material=glow)
    robot = join([torso, head, eye, arm_l, arm_r, leg_l, leg_r, antenna, tip], "robot")
    set_origin(robot, "BOTTOM")
    return robot
```

**常见坑**：机器人左右件不要手写两遍尺寸（易错位）——建一件后 `duplicate` 并给负 x；金属材质必须有足够灯光/世界亮度，否则渲染发黑；发光件 `emission_strength` 建议 2-8，1.0 在 AgX 下几乎看不出。

### 示例 C：低多边形小屋

**提示词**：`建一个低多边形森林小屋，有斜屋顶、烟囱、门窗，晚上亮着灯，周围有一棵树`

**量化决策**：屋体 2.4×2.0×1.8 m（总高含屋顶 2.6）；坡屋顶用三棱柱（`cylinder(vertices=3)` 旋转 90°，轴向 X）；烟囱 0.3×0.3×0.8；门窗用薄立方体 + 发光窗；树 = 圆柱干 + 2 层圆锥；地面 = `setup_floor`；窗外发光 `emission_strength=4`；相机 target=(0,0,1.0)、distance=7.0。

**brief 关键值**：屋体中心 z=0.9；屋顶脊高 2.6；烟囱顶 2.9；树高 5 m 放在 (-3.2, 1.0, 0)，场景总宽约 6 m。

**代码结构**：

```python
def build():
    reset_scene()
    setup_scene(target=(0, 0, 1.0), distance=7.0, lens=50)
    wood = mat("cabin_wood", color=(0.50, 0.33, 0.20), roughness=0.75)
    roof_mat = mat("cabin_roof", color=(0.28, 0.16, 0.12), roughness=0.65)
    warm = mat("cabin_light", color=(1.0, 0.85, 0.55), roughness=0.4,
               emission=(1.0, 0.75, 0.35), emission_strength=4.0)
    leaf = mat("tree_leaf", color=(0.16, 0.38, 0.20), roughness=0.85)

    body = cube("cabin_body", size=(2.4, 2.0, 1.8), location=(0, 0, 0.9), material=wood)
    # 三棱柱坡屋顶：正三角截面 + 压坡。radius = 屋体半深 / cos30° = 1.1547；
    # rotation=(90,0,90) 让截面立在 YZ 平面、屋脊沿 X；再沿 Y 压到半深 1.0（0.462 = 需要的坡度系数）。
    # 注意：本段用到 scale_obj，文件头 from blender_kit import ... 要把它加上（模板默认没导入）。
    roof = cylinder("cabin_roof", radius=1.1547, depth=2.6, vertices=3,
                    location=(0, 0, 1.8 + 0.2667), rotation=(90, 0, 90), material=roof_mat)
    scale_obj(roof, (1.0, 0.462, 1.0))
    chimney = cube("cabin_chimney", size=(0.3, 0.3, 0.8), location=(0.7, -0.4, 2.5), material=wood)
    door = cube("cabin_door", size=(0.55, 0.06, 1.0), location=(0, -1.0, 0.5), material=roof_mat)
    window = cube("cabin_window", size=(0.5, 0.06, 0.5), location=(-0.6, -1.0, 1.25), material=warm)
    trunk = cylinder("tree_trunk", radius=0.14, depth=2.2, vertices=10,
                     location=(-3.2, 1.0, 1.1), material=wood)
    crown1 = cone("tree_crown_low", radius1=1.1, radius2=0.0, depth=1.8, vertices=10,
                  location=(-3.2, 1.0, 2.6), material=leaf)
    crown2 = cone("tree_crown_high", radius1=0.75, radius2=0.0, depth=2.0, vertices=10,
                  location=(-3.2, 1.0, 4.0), material=leaf)
    cabin = join([body, roof, chimney, door, window], "cabin")
    set_origin(cabin, "BOTTOM")
    tree = join([trunk, crown1, crown2], "tree")
    set_origin(tree, "BOTTOM")
    return cabin
```

**常见坑**：坡屋顶别用两个斜立方体硬拼（接缝会漏光）——用三棱柱最稳；`cylinder(vertices=3)` 的三角截面默认尖朝 +Y 且是等边三角形，直接 `rotation=(0,90,0)` 会把截面放平（实测屋顶横穿屋体、总高 3.64 而非 2.6）；正确做法是 `rotation=(90,0,90)` 让截面立在 YZ 平面、屋脊沿 X，再 `scale_obj` 沿 Y 压坡（上例 0.462），`location.z = 檐口 + 三角高/3`。不要用 `rotation=(0,90,120)`——那只是绕世界 Z 转 120°，截面朝向不变（实测仍错）；门窗薄立方体要稍微嵌入墙面 0.01 m，避免共面闪烁。

## 6. brief → 部件表 → 代码 的映射检查

写代码前做一遍"三查"：

| 查 | 方法 | 不通过则 |
| --- | --- | --- |
| 部件表完整 | 每个部件是否都有图元/尺寸/位置/材质 | 回第 4 节补拆 |
| 尺寸可加和 | 主体尺寸 + 附件外扩 ≈ brief 总尺寸（误差 ≤ 10%） | 调整尺寸表 |
| 每个部件可落地 | 表里的函数名在 `AGENTS.md` 第 6 节 / `references/bpy-cookbook.md` 的 kit API 中存在 | 改用等价图元或 bmesh 裸写 |

写代码后反向核一遍：`grep` 每个部件名，确认 `model.py` 里出现次数 ≥ 1；`PARAMS` 里出现所有尺寸数字，函数体内无魔法数字。

## 7. 常见物件尺寸默认值（米）

| 物件 | 默认总高/总长 | 关键比例 | 备注 |
| --- | --- | --- | --- |
| 马克杯/茶杯 | 0.09-0.10 | 高径比 1.0-1.2；杯柄高 ≈ 杯高 1/2 | 带碟另加 0.015 |
| 玻璃杯 | 0.12-0.15 | 直径 0.06-0.08 | 薄壁，低多边形不做内壁 |
| 矿泉水瓶 | 0.22-0.25 | 直径 0.065 | 瓶盖 0.03 |
| 餐盘 | 直径 0.25，高 0.02 | — | — |
| 书本 | 0.24×0.17×0.03 | — | 平放 z=0.015 |
| 手机 | 0.15×0.07×0.008 | — | 桌面场景用 |
| 台灯 | 0.45 | 灯罩直径 0.25 | 灯罩用 cone |
| 办公椅 | 0.90-1.00 | 座高 0.45，靠背高 0.55 | 5 条腿可简化为 4 |
| 餐桌 | 0.75 | 桌面 1.4×0.8 | 桌腿 0.04 见方 |
| 沙发 | 0.85 | 宽 2.0，坐深 0.9 | — |
| 双人床 | 0.55（床架） | 2.0×1.5 | 床垫 +0.2 |
| 衣柜 | 2.0 | 宽 1.2，深 0.6 | — |
| 门 | 2.0-2.1 | 宽 0.8-0.9 | — |
| 窗 | 1.2-1.5 | 宽 0.8-1.2 | — |
| 显示器 | 0.45（含支架） | 屏 0.55×0.33 | — |
| 键盘 | 0.025（厚） | 0.44×0.14 | — |
| 单人床/椅/桌的"人" | 1.75 | 头高 0.23 | 人物仅作比例参考 |
| 小汽车 | 4.5（长）×1.8×1.5 | 轴距 2.7，轮径 0.65 | 低多边形轮子 12 段 |
| 自行车 | 1.8（长）×1.1 | 轮径 0.68 | — |
| 树（阔叶） | 5-8 | 冠幅 ≈ 高度 0.6；干高 ≈ 总高 0.4 | 低多边形圆锥 2-3 层 |
| 灌木 | 0.8-1.2 | — | 球压扁 |
| 路灯 | 4-5 | 灯头 0.5 | — |
| 单层小屋 | 3-4（含屋顶） | 屋体 2.4×2.0×1.8；屋顶脊高 +0.8 | 坡屋顶三棱柱 |
| 两层住宅 | 6-7 | 每层 2.8-3.0 | — |
| 狗/猫（低多边形） | 0.4-0.6 | 头身比 1:1.5 | — |
| 机器人（人形） | 1.5-1.8 | 腿 0.45、机身 0.6、头 0.3 | 见示例 B |
| 无人机 | 0.25×0.25×0.1 | 轴距 0.25 | 螺旋桨用 3 叶薄立方体 |
| 手提箱 | 0.55×0.35×0.2 | — | — |
| 花瓶 | 0.25-0.35 | 口径 0.08 | 用 cylinder 缩放 |
| 盆栽 | 0.5-0.7 | 盆高 0.2，冠 0.4 | — |

**使用规则**：先查表取默认值，再按用户"大/小/迷你"等词乘系数（×1.5-2 / ×0.3-0.5），最后写进 brief 并保证 `report.json.dimensions` 误差 ≤ 10%。

## 8. 风格参数差异表（写进 PARAMS）

| 参数 | 低多边形 | 卡通造型 | 写实 | 硬表面科幻 |
| --- | --- | --- | --- | --- |
| 圆柱 `vertices` | 8-16 | 16-24 | 32-64 | 16-24 |
| 球 `segments/rings` | 12/6-16/8 | 24/12 | 32/16+ | 24/12 |
| 平滑 | `shade_flat` | `shade_smooth(angle=30-40)` | `shade_smooth` + 倒角 | `shade_flat` + 切角 |
| 倒角宽度 | 0-1% | 2-4% | 1-3% | 1-2% 切角 |
| 材质粗糙度 | 0.5-0.8 | 0.4-0.7 | 0.2-0.9 分区 | 0.2-0.4 |
| 金属度 | 0 | 0-0.2 | 按材质 | 0.8-1.0 |
| 颜色饱和 | 中低 | 高 | 低-中 | 低（灰/黑）+ 发光点缀 |
| 发光 | 不用 | 1 处点缀 | 谨慎 | 发光条/屏 |
| 面数预算 | 300-3000 | 1500-8000 | 8000+ | 2000-20000 |
| 灯光 | 三灯棚拍 | 更柔、key 能量 +20% | 三点布光 + 环境 | 低 key + 强 rim 勾边 |

## 9. 常见反模式

| 反模式 | 后果 | 正确做法 |
| --- | --- | --- |
| brief 只抄形容词不量化 | 代码里全是猜的数字，无法验收 | 每个形容词 → 数字参数（第 2 节） |
| 一次建 15 个部件再渲染 | 出错定位困难，改一处崩三处 | 主体 → 预览 → 附件 → 预览 → 细节 |
| 尺寸不查默认表 | 模型 10 米高的杯子/1 厘米的房子 | 查第 7 节，真实尺度起步 |
| 用布尔做所有挖孔 | 低多边形布尔易失败、面数爆炸 | 用叠图元/白模分区/倒角表达 |
| 所有部件单独成对象 | 对象数爆炸、check_output 对象数失控 | 同逻辑组 `join` + `set_origin` |
| 颜色用 0-255 | kit 收到 >1 的值，颜色过曝 | 统一 0-1 RGB |
| 忘了写假设 | 返工时不知道当初为什么这么定 | brief 的"假设与默认决策"逐条写 |
