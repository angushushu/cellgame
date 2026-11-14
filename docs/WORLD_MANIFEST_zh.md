# 世界清单（World Manifest）与观察格式 v2 — 规格草案

状态：草案 v0.2。**M1 已实现**（见 §13），其余部分仍是设计。
适用版本：CellGame 0.2 起。0.1.x 的行为作为 `legacy` 世界完整保留。

已实现接口与兼容约定以 [核心接口标准 1.0.0-rc.1](CORE_STANDARD_zh.md) 为准。本文件保留未来设计，不代表所有清单字段已经可用。

---

## 0. 设计原则

1. **世界规则在服务器，有机体规则在客户端。** 服务器是唯一权威：它决定世界如何运转、每个单位能知道什么、行动代价多少。客户端代码完全自由，但只能看到服务器给它的东西。
2. **不直接奖励预测。** 世界通过四种条件让"预测"成为玩家自发发现的生存策略：**隐藏状态、规律、延迟、信息成本**（见 §8）。
3. **一切可变的东西都写进清单。** 感知方式、行动集、代价、资源层、会话形态、离线策略……都由世界规则声明。客户端 SDK、组合器界面、文档提示都从清单自动适配，不写死。
4. **感知即权限。** 玩家拿到的观察就是服务器按感知模型裁剪后的结果。不再向玩家广播全图。
5. **诚实的边界。** 服务器能强制的是"玩家之间、有机体与外界之间"的信息隔离；同一玩家的进程内部如何共享信息，服务器无法强制（见 §11）。

---

## 1. 术语

| 术语 | 含义 |
|---|---|
| 世界规则（World Rules） | 服务器端 Python 文件 + 清单数据，定义世界的一切 |
| 清单（Manifest） | 世界规则对外声明的契约，连接时下发给客户端 |
| 预设（Preset） | 一份打包好的世界规则，代表一种游戏类型 |
| 细胞（Cell） | 占据一个格子的最小单位，拥有服务器分配的稳定 `cell_id` |
| 个体（Entity） | 通过连接（bond）相连的细胞组，等同于现有的 organism |
| 角色（Role） | 毯感知下每个细胞的拓扑角色：`boundary`（边界）或 `interior`（内部） |
| 感知（Percept） | 某个细胞在某个 tick 对某个格子的一次观察 |
| 大脑（Brain） | 玩家本地运行的有机体规则（Python、HTTP 模型、外部程序） |
| 本能（Instinct） | 由服务器执行的声明式行为配置，大脑缺席时接管 |

---

## 2. 清单结构

清单是 JSON 对象。服务器在 `welcome` 消息中下发完整清单和它的哈希。

```jsonc
{
  "manifest_version": 1,
  "id": "deep-dive",
  "name": "深潜",
  "description": "毯感知、感知收费、隐藏季节。",

  "world": {
    "width": 128, "height": 128,
    "topology": "bounded",          // bounded | torus
    "tick_ms": 1000, "deadline_ms": 800
  },

  "session":     { ... },   // §7
  "perception":  { ... },   // §4
  "visibility":  { ... },   // §4.4
  "actions":     [ ... ],   // §5
  "cell_types":  [ ... ],   // §6.1
  "layers":      [ ... ],   // §6.2
  "ecology":     { ... },   // §6.3
  "bonds":       { "enabled": true, "group_move_max_cells": 256 },
  "observation": { "version": 2, "coordinates": "relative" },  // §3
  "offline":     { ... },   // §7.2
  "mutable": ["actions.*.cost", "ecology.*", "layers.*.regrow"]
}
```

### 2.1 结构性字段与可变字段

- **结构性字段**（感知模型、行动集、细胞类型、资源层、坐标模式）在一个世界的整个生命周期内固定。改动它们等于开一个新世界。
- **可变字段**列在 `mutable` 中，例如代价和再生速度。世界规则可以在运行中修改它们（替代现在的 `on_epoch` 返回参数），服务器随后广播 `manifest_update`：

```json
{"type": "manifest_update", "payload": {"revision": 7, "changes": {"actions.move.cost": 3}}}
```

客户端以 `revision` 为准，丢失更新时可请求完整清单。

### 2.2 世界规则文件如何声明清单

```python
# my_world.py
PRESET = "deep-dive"          # 从官方预设继承
MANIFEST = {                  # 只写需要覆盖的部分
    "world": {"width": 96, "height": 96},
    "perception": {"model": "blanket", "external_radius": 1},
}

def on_epoch(view, tick):            # 可选：修改可变字段
    return {"ecology.food_regrow": 200}

def on_event(event, view):           # 可选：现有接口保留
    return []
```

服务器启动时合并 预设 → `MANIFEST` → 命令行参数，校验后生成最终清单。校验失败则拒绝启动，并给出具体字段。

---

## 3. 观察格式 v2

### 3.1 现有格式的问题

- `neighborhood` 固定为 `(n, 45)`，`env` 固定为 `(n, 12)`，无法容纳可变半径或可变感知方式。
- 用坐标标识细胞，细胞一移动身份就丢了，玩家很难给单个细胞挂上记忆。
- "空格"和"看不见的格子"无法区分，都是 0。
- 玩家另外还会收到全图快照和增量，所以感知限制形同虚设。

### 3.2 新格式

每个 tick 服务器向每个玩家发送一份 `observation`：

```jsonc
{
  "version": 2,
  "tick": 120,
  "manifest": "sha256:…",         // 清单哈希
  "revision": 7,                  // 可变字段修订号

  "cells": {                      // 自己的细胞，每行一个
    "columns": ["cell_id", "x", "y", "type", "state", "energy", "bonds", "entity", "role"],
    "data": ndarray(n, 9)
  },

  "percepts": {                   // 稀疏感知表：只包含被感知到的格子
    "columns": ["observer", "dx", "dy", "occupant", "type", "state", "energy", "food", "chem0"],
    "data": ndarray(m, k)
  },

  "events": [ ... ]               // 本 tick 与自己相关的结果：行动失败原因、被攻击、出生等
}
```

规则如下：

- **`cells.columns` 与 `percepts.columns` 由清单决定。** 世界开启化学层，感知表里就多出 `chem0…`；世界关闭能量可见性，就没有 `energy` 列。SDK 按列名读取，不按下标。
- **`observer`** 是 `cells` 中的行号；`dx, dy` 是相对观察者的偏移。
- **`occupant`** 编码：`0` 空，`1` 自己且与观察者相连，`2` 自己但未相连（包括观察者自己），`3` 其他玩家，`4` 有占用但无法辨认（例如对方的内部细胞，见 §4.4，M1 保留未用），`5` 世界边界之外。
- 两张表在线路上是 NumPy 结构化数组，字段名就是列名。M1 的字段：
  - `cells`：`cell_id`(uint32) `x` `y` `type` `state`(int64) `energy` `bonds` `entity` `role`
  - `percepts`：`observer` `dx` `dy` `occupant` `species` `type` `state`(int64) `energy` `food`(float32) `temp`(float32)
- M1 中每份观察还附带 `constraints`（与旧版相同的世界参数字典）和 `world_run`（本次服务器运行的随机标识，`cell_id` 只在同一次运行内唯一）；`manifest_update` 在后续阶段实现。

**线路上的紧凑形式（M1 已实现）。** 如果逐个细胞发送感知表，相邻细胞的感知窗口大量重叠，大种群时消息会超过 32 MB 的上限。所以在 `radius` 世界中，服务器发送的不是 `percepts`，而是 `tiles`：本玩家所有细胞感知到的格子的并集，每个格子只出现一次，带绝对坐标。字段为 `x` `y` `occupant`(只有 0/2/3) `species` `type` `state` `energy` `food` `temp`。客户端 SDK 根据细胞位置和清单中的感知偏移，把它还原成上面的逐细胞 `percepts` 表（`shared/observation.py` 的 `expand_observation`），包括"相连"和"世界之外"这两种只与观察者有关的编码。规则代码看到的始终是逐细胞的 `percepts`。

这样做没有多泄露信息：同一玩家的知识本来就是共享的（§11 第 1 条）。消息大小的上限从"细胞数 × 窗口大小"变成了"世界面积"。以后感知方式不再由位置和偏移决定时（例如 `blanket` 或 `custom`），需要为线路格式增加"观察者 → 格子"的索引。
- **看不见的格子不出现在表里。** "不在表里"就表示未知，与"空"严格区分。
- **数值不可见时为 `-1`**，例如能看到有细胞但看不到能量。
- **`role`**：`0` 无（非毯模型），`1` 边界，`2` 内部。
- **`events`** 告诉玩家上一 tick 每个提议的结果（`ok` / `target_occupied` / `insufficient_energy` / `contested` / `attacked` …）。这是写代码玩家最需要的调试反馈，也是预测误差的一个天然来源。

### 3.3 坐标模式

`observation.coordinates` 取值：

- `absolute`（默认，兼容）：`cells` 中包含真实 `x, y`。
- `relative`（研究向）：不发送绝对坐标，`x, y` 列被移除。玩家只知道细胞的 `cell_id` 和相对关系，没有"GPS"。定位本身成为需要推断的隐藏状态。

### 3.4 稳定的细胞身份

服务器为每个细胞分配 `cell_id`（uint32，单个世界内不重复使用），移动、整体移动、类型变化都保持不变，死亡后作废。新增世界数组 `cell_id`。

### 3.5 行动提议 v2

不再用源坐标标识细胞：

```
INTENTION_V2 = [cell_id, action_id, dx, dy, param]
```

- 消息格式：`{"type": "intentions", "payload": {"tick": 120, "format": 2, "data": <(n, 5) 整数数组>}}`。格式错误时服务器回复 `error`（`code = "bad_intentions"`）。
- `action_id` 来自清单的行动表（§5），不再写死枚举。
- 目标位置 = 细胞当前位置 + `(dx, dy)`；作用于自身的行动 `dx = dy = 0`。
- 服务器校验所有权、`cell_id` 存活、距离限制和代价，规则与现在的仲裁器一致。

### 3.6 Python SDK

`decide_cell / decide_entity / decide_unity / decide` 四个入口全部保留，背后改用 v2 观察：

```python
def decide_cell(cell):
    for p in cell.percepts():             # 只返回被感知到的格子
        if p.occupant == p.ENEMY and p.energy != -1 and p.energy < cell.energy:
            return cell.attack(p.direction)
    here = cell.sense(0, 0)               # 看不见时返回 None
    if here and here.food > 0:
        return cell.eat()
    return cell.wait()

cell.id          # 稳定身份，可作为记忆的键
cell.role        # "boundary" / "interior" / None
cell.memory      # SDK 提供的按 cell_id 保存的字典，细胞死亡时清除
```

现有属性 `empty_neighbors()`、`surrounding()`、`food_here` 继续可用，读取的是感知表中内圈 3×3 的格子。旧接口无法表达"未知"，所以内圈中未被感知的格子在这些旧接口里显示为空；需要区分时请用 `cell.sense()`。

在 legacy 世界中 `cell.id` 为 `None`，`cell.percepts()` 返回空列表，`cell.sense()` 返回 `None`，读取 `cell.memory` 会报错。

批量接口 `decide(cells, neighborhood, env, constraints, tick)` 不变；如果在参数中加上 `observation=None`，就会收到完整的 v2 观察。HTTP 模型服务和外部程序收到的 JSON 中多一个 `observation` 字段，里面是线路形式的 `cells` 和 `tiles`（各有 `columns` 和 `rows`，坐标为绝对坐标）；它们仍以旧格式的行动行回复。

### 3.7 向后兼容

- 清单 `perception.model = "legacy"` 时，服务器继续发送现在的 `sense_batch`（`cells`、`neighborhood`、`env`），旧代码和旧客户端不受影响。
- 新客户端连接 `legacy` 世界时使用 v1 路径；旧客户端连接非 `legacy` 世界时，服务器在 `welcome` 中返回明确的版本错误，而不是静默失败。

---

## 4. 感知模型

`perception.model` 选择一种模型。每种模型最终都只做一件事：为每个玩家生成感知表。

### 4.1 `radius` — 半径感知

```json
"perception": {"model": "radius", "radius": 2, "metric": "chebyshev", "occlusion": false}
```

- 每个细胞感知以自己为中心、半径 `radius` 内的格子。`metric`：`chebyshev`（方形）或 `euclidean`（圆形）。
- `occlusion: true` 时被细胞挡住的格子不可见（视线遮挡，可选，后期实现）。
- `radius: 1` 加上完全可见性就等于今天的行为。

### 4.2 `blanket` — 毯感知

```json
"perception": {
  "model": "blanket",
  "external_radius": 1,
  "interior_sees": "bonded_neighbors",
  "single_cell_is_boundary": true
}
```

**角色计算**（每 tick 在仲裁和生态结算之后，由服务器完成）：

- 以连接组件（Entity）为单位。若一个细胞的 8 个邻格中至少有一个不属于本组件（包括空格、其他组件、世界边缘），它就是 `boundary`，否则是 `interior`。这与现在 `species/units.py` 中 `is_boundary` 的定义一致。
- 未连接的单个细胞就是只有自己的组件，因此总是 `boundary`。

**感知规则：**

| 角色 | 能感知什么 |
|---|---|
| boundary | 半径 `external_radius` 内的外部格子，以及相连的邻居 |
| interior | 只有相连邻居的 `state`、`energy`、`type`；看不到外部格子，也看不到脚下的资源层 |

**配套的权衡**写在 `ecology` 与 `cell_types` 中，由世界决定，例如：

```json
"ecology": {"metabolism": {"boundary": 2, "interior": 1}},
"actions": {"eat": {"actor_roles": ["boundary"]}}
```

这样会自然产生面积与体积的权衡：个体越大越安全，但膜的维护更贵，信息只能从边界进入。

"内部细胞在膜被打破前不能被攻击"不需要单独的规则：攻击只能指向相邻格子，而一个细胞只要旁边有敌人，按定义就是边界细胞。这一点由几何关系保证（M2 测试 `test_attack_targets_are_always_boundary_cells`）。

### 4.3 `custom` — 自定义感知

研究者可以在世界规则中实现：

```python
def perceive(view, player_id, cells):
    """返回本玩家的感知表行：[(observer_row, dx, dy, {column: value}), ...]"""
```

- 服务器对返回值做校验：只能包含清单声明的列，`observer` 必须是该玩家自己的细胞。
- 有超时（与 `on_event` 相同），超时则该 tick 发送空感知表并记日志。
- `custom` 模型的性能由世界作者负责，清单需声明 `"max_percepts_per_cell"` 作为上限。

### 4.4 可见性（Visibility）

感知模型决定"能看到哪些格子"，可见性决定"看到的格子里能读到什么"：

```json
"visibility": {
  "state":  "boundary_only",       // all | boundary_only | none
  "energy": "all",                  // all | boundary_only | none
  "type":   "all",
  "others_interior": "hidden",      // visible | hidden：hidden 时显示为 occupant=4，属性全为 -1
  "spectator": "full"               // full | none（M2）；delayed 计划随 M5 速战模式实现
}
```

- 这些规则只作用于**其他玩家**的细胞；自己的细胞总是完全可见。
- `boundary_only`：其他玩家只能读到边界细胞的该属性。内部细胞的 `state` 成为真正的私有记忆，边界细胞的 `state` 成为对外信号，可以用来伪装或警告。
- legacy 世界会向玩家发送全图，因此不能设置玩家可见性（`spectator` 除外）。
- 速战模式下观战者可能就是对手；`spectator: "none"` 会让观察页和 `/spectate` 不再提供地图，玩家列表中的细胞数和能量也会隐藏。

### 4.5 感知成本（主动感知）

```json
"actions": {"sense": {"enabled": true, "cost_per_radius": 1, "max_radius": 4}}
```

- 行动编号 11，参数为半径（1 到 `max_radius`），花费 `cost_per_radius × 半径` 的能量。SDK 中的写法是 `cell.extend_sense(3)`（`cell.sense(dx, dy)` 是读取感知，名字已被占用）。
- 细胞付费后，下一份观察中它的感知半径变为 `max(基础半径, param)`，之后恢复。观察的 `cells` 表中 `sense_radius` 一列给出每个细胞本次实际使用的半径。
- 在 `blanket` 世界中只有边界细胞能使用（内部细胞看不到外部）；默认的 `actor_roles` 就是 `["boundary"]`。
- 这一个行动就同时引入了**信息成本**和**延迟**两种条件，"少看、多猜"会自然成为可行策略。

### 4.6 玩家地图界面

非 `legacy` 世界里，客户端地图不再显示全图，而是由自己的感知累积成"已知地图"：当前感知到的格子正常显示，过去见过、现在看不到的格子淡化显示并标注"最后看到于第 N tick"。这本身就是一种可视化的内部模型。

---

## 5. 行动表

清单中的 `actions` 列出本世界所有可用行动。现有 11 种行动作为内置行动保留原编号。

```jsonc
{
  "name": "move",
  "id": 0,
  "target": "neighbor",            // self | neighbor | bonded_neighbor | component
  "cost": {"base": 2, "by_type": {"armor": 3}},
  "requires": {"unbonded": true, "target_empty": true},
  "phase": 6                       // 结算顺序
}
```

- `phase` 让世界声明结算顺序。默认顺序与现在一致：DIE → CHANGE → SET_STATE → BOND/UNBOND/TRANSFER → EAT → REPRODUCE → MOVE → MOVE_GROUP → ATTACK。
- 世界可以禁用内置行动（例如合作世界里不允许 `attack`），客户端组合器会相应隐藏模块。
- 计划新增的内置行动：`sense`（§4.5）、`emit`（向化学层释放信号，§6.2）。
- **暂不支持**用 Python 定义全新的行动语义。新行动先以内置方式加入，等接口稳定后再考虑开放。

---

## 6. 世界内容

### 6.1 细胞类型表

取代写死的"装甲 = 类型 1"：

```json
"cell_types": [
  {"id": 0, "name": "basic"},
  {"id": 1, "name": "armor", "defense_bonus": 3, "move_surcharge": 1, "change_cost": 1},
  {"id": 2, "name": "sensor", "sense_radius_bonus": 2, "metabolism_bonus": 1, "change_cost": 2}
]
```

可配置字段先限定为一组白名单：`defense_bonus`、`move_surcharge`、`metabolism_bonus`、`sense_radius_bonus`、`can_eat`、`can_attack`、`change_cost`。

### 6.2 资源层与化学层

```json
"layers": [
  {"name": "food", "kind": "resource", "regrow": 300, "regrow_near_cells": 30, "max": 20},
  {"name": "toxin", "kind": "resource", "looks_like": "food", "damage": 3},
  {"name": "chem0", "kind": "signal", "diffusion": 0.2, "decay": 0.1, "max": 255}
]
```

- `resource` 层可被 `eat` 消耗；`looks_like` 让两种资源在感知中无法区分，需要玩家通过后果学习。
- `signal` 层由 `emit` 写入，每 tick 扩散和衰减。它是有限距离、有延迟的通信方式，可以替代现在客户端"群体共享线索"这种全局信息。
- 隐藏层：`"hidden": true` 的层不出现在感知表中，只通过效果影响世界，例如一个看不见的季节相位决定食物在哪里刷新。

### 6.3 生态

现有的 `metabolism_interval`、`food_regrow`、`temp_delta`、`reproduce_enabled` 移入 `ecology`，并允许按角色和类型分别设置代谢。

---

## 7. 会话、离线与持久化

### 7.1 会话形态

```jsonc
"session": {
  "mode": "match",                 // match | persistent
  "duration_ticks": 1800,          // match 专用：1 秒一 tick 约 30 分钟
  "max_players": 8,
  "spawn": {"cells": 20, "energy": 10, "placement": "ring"},
  "scoring": [                     // match 专用
    {"metric": "biomass", "weight": 1},
    {"metric": "survival_ticks", "weight": 1},
    {"metric": "lineage_depth", "weight": 0.5}
  ],
  "save_every_ticks": 0            // persistent 专用：定期写存档
}
```

- `match`：有开始和结束，结束时按 `scoring` 结算并广播排名。
- `persistent`：无限期运行，定期存档，服务器重启后可恢复。

### 7.2 离线策略：大脑与本能

```json
"offline": {
  "policy": "instinct",          // die | freeze | instinct
  "grace_ticks": 30,             // 断线后保留身份的时间
  "instinct": {
    "cost_multiplier": 1.5,      // 本能驱动的行动更贵
    "allowed_actions": ["eat", "move", "reproduce", "transfer", "sense"],
    "max_ticks": null            // null 表示不限；数字表示超时后进入休眠
  }
}
```

- `die`：当前行为。断线或连续沉默就清除所有细胞。适合速战。
- `freeze`：细胞进入休眠，不行动，代谢减半，仍可被攻击。
- `instinct`：服务器执行玩家预先上传的本能配置。

**本能**就是组合器生成的配置（现在 `species/composer.py` 的 `CONFIG`），是纯数据，不是代码：

1. 客户端加入世界时上传本能，可以随时更新（限速，例如每 30 tick 一次）。
2. 服务器端有一个本能解释器，读取 v2 观察，执行与组合器相同的逻辑。
3. **大脑在线时，本能也是兜底：** 大脑在截止时间前没有回复，这一 tick 由本能接管，而不是让所有细胞闲置。
4. 大脑重新连上后自动接管。

### 7.3 重连身份

- 首次加入时服务器发放 `rejoin_token`（随机 128 位），客户端保存在本地。
- 在 `grace_ticks`（或 persistent 模式下无限期）内用该令牌重连，可以重新接管原来的细胞。
- 这只是"持有者凭证"，不是账户认证。README 中关于"仅在可信网络使用"的说明继续有效。

### 7.4 规模

面向上万智能体的世界，以下参数由清单控制：`tick_ms`、`deadline_ms`、每玩家细胞上限、每 tick 感知行数上限。感知表、增量和事件都按玩家单独生成，不再广播全图。

---

## 8. 让预测有价值：世界设计清单

不直接奖励预测，而是让世界满足以下条件。设计官方预设时逐项核对。

| 条件 | 可用的机制 |
|---|---|
| 隐藏状态 | `hidden` 层、`looks_like` 资源、`relative` 坐标、内部细胞对外不可见 |
| 有规律 | 季节周期、食物迁移路线、有固定行为模式的环境智能体 |
| 有延迟 | `sense` 下一 tick 才生效、信号层扩散需要时间、整体移动的代价 |
| 信息有成本 | `sense` 收费、边界代谢更高、`sensor` 类型代谢更高 |

如果一个世界四条都不满足，"看到什么就做什么"已经足够，预测就不会出现。

---

## 9. 官方预设（首批）

| 预设 | 类型 | 感知 | 关键设置 |
|---|---|---|---|
| `legacy` | 兼容 | 现有方式 | 0.1.x 行为原样保留 |
| `primordial`（原汤） | 30 分钟速战 | `radius: 2` | 小地图、离线即死、按生物量和存活计分；新手推荐 |
| `deep-dive`（深潜） | 生存 | `blanket` | 感知收费、边界代谢更高、隐藏季节、`toxin` 伪装成食物 |
| `chemical-sea`（化学之海） | 大规模持久世界 | `blanket` + 信号层 | 本能离线、定期存档、`emit` 通信 |

预设文件同时是写世界规则的范例。

---

## 10. 研究模式

```python
from cellgame.lab import World

env = World(preset="deep-dive", seed=42)
obs = env.reset(players=["a", "b"])
for _ in range(1000):
    actions = {"a": my_policy(obs["a"]), "b": baseline(obs["b"])}
    obs, info = env.step(actions)        # 同一进程内满速运行，无网络
env.export_metrics("run.parquet")
```

- 与服务器使用同一套仲裁、生态和感知代码，保证本地实验与线上一致。
- 固定种子即可完全复现（前提是玩家策略本身确定）。
- 指标：每个个体的细胞数、能量、存活时长、血缘、行动成功率；玩家代码还可以通过 `info` 上报自定义指标，比如自己的预测误差。

---

## 11. 已知限制与未决问题

1. **同一玩家内部的信息共享无法强制。** 一个玩家的所有细胞由同一个本地进程控制，进程可以随意汇总所有边界细胞的感知。因此，本游戏中强制执行的"毯"位于**玩家与玩家之间、有机体与环境之间**，认知单位是"玩家"，而不是单个个体。研究者如果想让每个个体拥有独立大脑，可以在本地自愿这样运行，研究模式可以提供辅助。
2. **世界规则是可信的 Python 代码。** 自己开服时没有问题；以后社区分享世界规则时，需要沙箱，或者把规则限制为纯数据格式。
3. **感知计算成本。** 半径和玩家数一大，逐玩家生成感知表的开销会明显上升，需要基准测试并设上限。
4. **默认坐标模式。** 建议普通预设用 `absolute`，研究预设用 `relative`。待定。
5. **本能的表达能力。** 本能只能用组合器能表达的行为。是否允许更强的声明式规则（例如简单的状态机），留到组合器下一版再定。

---

## 12. 实施顺序

每一步都保持 `legacy` 世界可玩、现有测试全部通过。

| 阶段 | 内容 | 完成标准 |
|---|---|---|
| M1 清单与 v2 骨架 | 清单结构与校验、预设合并、`cell_id`、观察 v2、行动提议 v2、`radius` 感知、停止向非 legacy 玩家广播全图、SDK 适配 | `radius: 1` 世界中现有物种行为与 `legacy` 一致；新旧客户端都能得到明确结果 |
| M2 毯 | 角色计算、`blanket` 感知、可见性、按角色代谢、`sense` 行动、玩家"已知地图"界面、行动结果 `events` | 验证实验（见下）出结果 |
| M3 离线与持久 | 本能解释器、本能兜底、`rejoin_token`、`freeze`、存档与恢复 | 断线重连后接管原细胞；服务器重启后世界恢复 |
| M4 内容 | 细胞类型表、资源层与信号层、`emit`、`custom` 感知、研究模式 `lab` | `chemical-sea` 预设可玩 |
| M5 玩法 | `match` 计分与结算、四个官方预设、组合器按清单生成模块 | 新手能在 `primordial` 里完整玩完一局 |

**M2 验证实验：** 在 `deep-dive` 规则下，用 `tests/playtest.py` 的方式对比三类物种——无连接的单细胞群、有内部结构的连接个体、会用 `sense` 和记忆的个体。如果三者在不同世界参数下各有优势，说明"形态与信息策略决定生存"成立，后续方向就有了基础；如果某一类始终碾压，就先调整世界参数，再继续推进。

## 13. M1 实现状态

**已实现：**

- `shared/manifest.py`：清单默认值、合并与校验、哈希、感知偏移。目前清单只接受 `id`、`name`、`world`（`width` / `height` 16–512，`topology` 仅 `bounded`；512 以内能保证完整快照和完整格子列表都远低于 32 MB 的消息上限）、`perception`、`observation`（`coordinates` 仅 `absolute`）。其他章节的字段会被明确拒绝，并指向本文档，不会静默忽略。
- 感知模型 `legacy` 与 `radius`（`radius` 1–8，`metric` 为 `chebyshev` 或 `euclidean`；`euclidean` 至少要 2，才能覆盖旧接口需要的完整 3×3）。
- 稳定的 `cell_id`；观察 v2；行动提议 v2；SDK 的 `cell.id`、`cell.percepts()`、`cell.sense()`、`cell.memory`。
- 非 legacy 世界不再向玩家发送 `world_snapshot` / `world_delta`。玩家地图只显示当前感知到的格子；过去见过的格子不保留（"已知地图"属于 M2）。
- 协议版本握手：非 legacy 世界拒绝 `protocol_version < 2` 的客户端，并返回 `protocol_unsupported` 和更新提示；新客户端连接旧服务器时自动按 legacy 运行。
- 观察以紧凑的 `tiles` 形式发送（见 §3.2）。在 256×256 世界中，19,600 个细胞、半径 3 的观察消息小于 4 MB。
- 每个玩家每个 tick 只接受一条行动消息；重复的和过期的 tick 会在网络层直接丢弃，一个玩家无法用刷消息的方式挤掉其他玩家的行动窗口。
- `cell.memory` 按 `world_run` 区分；连到新一次服务器运行时自动清空，避免新细胞继承旧细胞的记忆。

**启动方式：**

```bash
python -m cellgame server --perception radius --sense-radius 2
```

也可以在世界规则文件中声明 `MANIFEST = {"perception": {"model": "radius", "radius": 2}}`。命令行选项会覆盖文件中的设置。

**验证：** `tests/observation_v2_test.py` 中有一个对拍测试：三种物种（含连接与整体移动）在 `radius: 1` 世界和 legacy 世界中运行 80 tick，每个 tick 的全部世界数组都完全一致。`tests/protocol_v2_e2e_test.py` 通过真实网络验证握手、观察下发、v2 行动和官方客户端。

**M1 的已知限制：**

- 服务器观察页面和 `/api/snapshot` 仍公开全图。在非 legacy 世界里，任何能打开观察页的人都能看到全部信息。观战可见性（§4.4 的 `spectator`）在 M2 处理。
- 本地预览仍按 legacy 世界运行。
- `events` 字段目前始终为空（M2）。
- 刚启动的约 3 秒内，第一份观察可能比 `welcome` 先到，客户端会忽略它，这一 tick 记为沉默（连续 3 tick 沉默才判定掉线）。
- `cell_id` 用尽（约 43 亿个）时服务器会停止，实际运行中不会遇到。
- 他方细胞在玩家地图上按 `species` 归属玩家，这依赖于"物种编号等于玩家编号"的现有约定。

## 14. M2 实现状态

**已实现：**

- **角色计算**（`server/world.py` 的 `component_labels` / `roles`）：先按连接求出连接组件（向量化的并查集），再判断：8 个邻格中只要有一个不属于本组件（空格、别的组件、世界边缘），就是边界细胞，否则是内部细胞。结果按世界版本缓存，所有改变细胞或连接的操作都会让缓存失效。
- **`blanket` 感知**：边界细胞看见 `external_radius` 窗口；内部细胞只看见自己和相连的邻居，而且看不到这些格子的资源层（`env_visible = false`，`food = -1`）。线路上仍是格子并集；客户端根据每个细胞的 `role`、`sense_radius` 和 `bonds` 还原逐细胞感知，不需要额外索引。
- **可见性**（§4.4）：`others_interior`、`state` / `energy` / `type` 三档、`spectator`（`full` / `none`）。所有隐藏都在服务器发送之前完成。
- **按角色代谢**：`ecology.metabolism.boundary` / `interior`。
- **行动规则**：`actions` 中可以按行动名设置 `enabled` 和 `actor_roles`；`sense` 另有 `cost_per_radius` 和 `max_radius`。被禁用或角色不允许的提议会得到明确的结果代码。
- **`sense` 行动**（§4.5）。
- **行动结果事件**：每个可归属的提议都有一条结果（成功、格式无效、能量不足、重复、被禁用、条件不满足、被竞争、应用时被打断、角色不允许），另外还有出生和死亡事件（死因：被攻击、饿死、自愿）。SDK 中 `cell.last_result` 给出上一个行动的结果名称。
- **玩家"已知地图"**：控制台地图显示所有见过的格子；当前看不到的格子变暗，从未见过的格子是黑的。玩家列表的统计只计算当前看得到的细胞。
- **预设 `deep-dive`（深潜）**：`--world-preset deep-dive`，内容见 `server/worlds/deep_dive.py`，§8 的四个条件各有对应机制。
- **示例物种**：`species/blob.py`（会长出内部的紧凑连接体）和 `species/sensing_forager.py`（付费看远处、记住目标）。

**与原设计不同的地方：**

- 攻击的"目标角色"限制被删除，原因见 §4.2：几何关系已经保证内部细胞不会被攻击。
- `spectator: "delayed"` 推迟到 M5 的速战模式。
- 内部细胞的感知固定为"自己 + 相连邻居"，暂不提供 `interior_sees` 选项。

**验证：** `tests/blanket_test.py`（单元）、`tests/blanket_e2e_test.py`（真实网络）。另外用一个模糊测试比对了重写后的仲裁器和 0.1.3 版：在默认世界中，800 次随机运行、6,293 条被接受的提议，结果和顺序都完全一致。

**代码审查后的修正（均有回归测试）：**

- **`deep-dive` 默认 `spectator: "none"`**：它的核心就是隐藏信息，观察页不能把肥沃区和别人的内部暴露出来。代价是服主在观察页上也看不到地图；想看的话，用一个自定义规则文件把 `spectator` 改回 `full`。
- **地图不公开时隐藏种子**：`--seed` 默认改为随机，`/api/players` 也不再返回种子、世界参数和全局行动统计，因为用种子可以重建初始食物分布。
- **`blanket` 世界默认只有边界细胞能进食**：否则内部细胞可以用"尝试进食"免费探测脚下有没有食物。世界作者可以用 `actions.eat.actor_roles` 明确放开。`sense` 的 `actor_roles` 在 `blanket` 世界中不能包含 `interior`。
- **内部观察者的逐细胞感知永远不含资源层**：即使同一格子也在某个边界细胞的窗口里。
- **角色在需要时一律下发**：radius 世界只要使用了按角色的规则，`cells.role` 也会填上，否则玩家会收到"角色不允许"却不知道自己的角色。
- **HTTP 和外部程序控制器收到的 `observation.events` 是 `columns` + `rows` 表**（之前无法转成 JSON，会导致控制器在第一个行动之后停止工作）。
- **其他修正**：同一连接组里有别的成员的整体移动成功时，被跳过的整体移动报告为"被竞争"而不是"应用时被打断"；`sense` 窗口改用世界大小的掩码计算，内存不再随"细胞数 × 窗口面积"增长。

**仍然存在的已知限制：** `cell_id` 和个体编号是全局递增的，玩家可以据此粗略估算全世界的出生速度。

### M2 验证实验结果

`python tests/blanket_experiment.py --ticks 240 --seeds 3`。三个物种各自单独运行，再一起运行；数值是第 240 tick 时存活细胞数的平均值。

| 世界 | 群体（无连接） | blob（有内部） | 感知觅食者 | 三者同场 |
|---|---|---|---|---|
| deep-dive | 120.0 | 51.3 | 131.3 | 13.3 / 0.0 / 165.3 |
| 感知免费 | 120.0 | 51.3 | 640.3 | 0.0 / 0.3 / 538.7 |
| 无膜成本 | 258.7 | 86.3 | 517.7 | 26.3 / 10.3 / 379.7 |
| radius 对照 | 258.7 | 109.7 | 123.0 | 0.0 / 5.0 / 216.3 |

**结论：**

1. **信息成本确实改变结果。** 感知觅食者在 `sense` 收费时为 131，免费时为 640。
2. **膜成本确实改变结果。** 无连接群体的每个细胞都是边界细胞，在边界代谢 2 时为 120，代谢 1 时为 259。
3. **"形态决定命运"还没有成立。** blob 确实长出了内部（平均每 tick 约 8 个内部细胞），但在所有世界里生物量都低于无连接群体。内部的两个好处是代谢便宜和不会被攻击，可是这次实验里没有捕食者，第二个好处完全没有被检验到。
4. **按 §12 自己定的标准，平衡还不过关。** 同场时感知觅食者在所有世界里都碾压另外两个，在禁用 `sense` 的 radius 对照里也一样。这说明它的优势有很大一部分不来自感知本身，而来自其他参数（例如 14 就开始繁殖、会走向记住的目标）。

**进入 M3 之前建议先做**（已在 §15 完成；结论是失衡主要来自实验物种本身，而不是世界规则）： 加入捕食者物种来检验内部的保护作用；让三个物种的繁殖阈值一致，以便公平比较；再调整内部细胞的好处（例如内部代谢为 0，或允许内部储存更多能量），重新运行实验，直到三类策略在不同参数下各有胜场。

## 15. 平衡调整（M2 之后）

**问题：** §14 的实验里，感知觅食者在所有世界都碾压其他物种，包括禁用了感知的 radius 对照世界。

**原因：不是世界规则失衡，而是实验物种不公平。** 三个物种的经济阈值不同：群体吃到 20 就停，而且能量高于 4 就会四处游走（每步花 2 能量）；感知觅食者吃到 30 才停，没有目标时原地等待。实验测到的其实是"囤积"对"游荡"，而不是"感知"对"盲目"。

**做法：**

- 四个探测物种使用同一套经济规则（吃到 25、能量 14 时繁殖、能量高于 6 才走动），每个只有一个策略特征不同：
  - `species/swarm.py`：盲目游走的无连接群体。
  - `species/blob.py`：有内部的连接体，不移动。
  - `species/sensing_forager.py`：付费感知并记住目标；不能感知时像群体一样游走。
  - `species/predator.py`：攻击能打赢的相邻敌方细胞，其余行为同群体。新增的目的是检验"内部不可被攻击"。
- `tests/blanket_experiment.py` 用数据描述世界变体，每个物种先单独运行，再四者同场，并记录每个种子的胜者。

**结果**（240 tick，6 个种子；"单独"一栏是结束时存活细胞数的平均值）：

| 世界 | swarm | blob | sensing | predator | 同场胜者（6 个种子） |
|---|---|---|---|---|---|
| deep-dive（预设，未改动） | 49 | 61 | 43 | 49 | sensing 3、predator 1、blob 1、swarm 1 |
| 感知免费 | 49 | 61 | 67 | 49 | **sensing 4**、swarm 1、blob 1 |
| 无膜成本 | 99 | 90 | 85 | 99 | **predator 3、swarm 2**、sensing 1 |
| 食物分散丰富 | 255 | 125 | 197 | 255 | **predator 3**、sensing 2、swarm 1 |
| 捕食有利（奖励 100%、攻击成本 1） | 49 | 61 | 43 | 49 | swarm 2、predator 2、sensing 1、blob 1 |
| 饥荒（食物稀少） | 18 | 25 | 15 | 18 | **blob 5**、sensing 1 |
| radius 对照 | 99 | 103 | 98 | 99 | predator 3、sensing 2、swarm 1 |

**结论：**

1. **`deep-dive` 预设不需要改。** 换成公平的物种之后，四个物种同场时各自都赢过至少一次；感知觅食者稍占优（6 局赢 3 局），但已经不是碾压。
2. **每种策略都有自己能赢的环境，而且都由世界规则决定：** 信息便宜时感知赢；没有膜成本或食物分散时，无连接的群体和捕食者赢；饥荒时连接体赢。§12 的标准（"在不同世界参数下各有优势，没有一类始终碾压"）已经满足。
3. **连接体的优势来自整体策略，而不是内部代谢便宜。** 把内部代谢从 1 降到 0，blob 单独时只从 25 增加到 28，同场胜负没有变化；它在饥荒中获胜，靠的是共享能量和不用走动。"内部代谢"是一个很弱的平衡杠杆。
4. **捕食仍然几乎没有被检验到。** 即使捕食有利，每 tick 的攻击也只有 0.1 到 0.2 次：探测用的捕食者和别人一样在 14 时繁殖，很少比邻居强。所以"内部不可被攻击"的价值依然没有测到。要检验它，需要一个会囤积能量、主动追猎的捕食者，这是下一步的物种设计工作，不属于世界规则的调整。

**顺带修复的问题：** 在 Windows 上，服务器或客户端进程被直接结束时（例如测试里的 `terminate()`），模拟子进程会一直运行，原因有两个：子进程不检查父进程是否还在；事件队列的后台线程在退出时等待写入一个已经没有人读的管道。客户端的规则子进程也有同样的问题。测试反复运行后，累计约 50 个孤儿进程占满了内存，这也是之前出现"内存不足"和 `edge_test` 失败的原因。现在两种子进程都会在父进程消失后约 1 秒内退出，跑完整套测试后不再有残留进程，`edge_test` 也恢复通过。

## 16. 主动捕食者与"身体"的防御

**目标：** §15 的捕食者几乎不攻击，"内部不可被攻击"的价值一直没有测到。这一节设计一个真正会狩猎的物种，用它来检验连接体的内部是否真的提供保护。

### 16.1 `species/stalker.py` 的设计过程

每一步都先测量，再修改：

1. **初版**（囤积能量：吃到 45、到 40 才繁殖；付费感知猎物并追击）：开局 60 tick 内从 20 个细胞崩溃到 2 个。原因是能量只有 10 就开始追击和感知，没有储备。→ **改为先进食，能量到 15 才开始狩猎；繁殖阈值降到 30。**
2. **会存活了，但仍然很少攻击。** 逐步统计后发现：在 568 个有能力狩猎的细胞·tick 中，只有 6 次看到过敌人。不是打不过，而是遇不到：各物种分散成团，靠随机游走和半径 1 的视野几乎碰不到猎物。→ **加入定向搜索**：保持一个方向直线前进（比随机游走覆盖的范围大得多），用最大半径 4 感知。遇敌次数提高约 9 倍。
3. **同场四个物种时猎物仍然太稀疏**，所以检验保护作用改用**一对一对决**：`python tests/blanket_experiment.py --versus stalker`。它会统计每种猎物被吃掉的细胞数，以及按细胞·tick 和按边界细胞·tick 计算的被杀率。

stalker 的经济阈值有意不同于其他探测物种：囤积能量本身就是狩猎策略的一部分。

### 16.2 结论：不能防御的膜什么也保护不了

stalker 一对一的结果（240 tick，4 个种子；被杀率单位是"每千个细胞·tick"）：

| 世界 | 猎物 | 单独存活 | 有捕食者时存活 | 被杀率 |
|---|---|---|---|---|
| deep-dive | 群体 | 46 | 54 | 2.6 |
| deep-dive | blob | 57 | **15** | **9.8** |
| 捕食有利 | blob | 57 | **0（灭绝）** | **40.8** |

连接体反而是**最容易被吃掉**的猎物。"内部不可被攻击"只意味着捕食者要先吃掉外层。blob 不能移动、不能逃跑，它的边界细胞和单个细胞一样弱，捕食者可以一层一层地剥。

- **试过装甲，没有用。** 给 blob 加"接触敌人就变成装甲"后，deep-dive 中被杀的细胞反而从 19 增加到 42：+3 防御挡不住囤积到 15–45 能量的捕食者，而且变装甲要占用一次行动。已回退。
- **根本原因在战斗规则。** 防御只看被攻击细胞自己的能量，所以一个连接体并不比一盘散沙更强。

### 16.3 新的世界规则：`combat.bonded_support_percent`

```json
"combat": {"bonded_support_percent": 50}
```

被攻击细胞的防御 = 自身能量 + 装甲加成 + **相连邻居能量之和 × 百分比**。默认值是 0，现有世界的行为完全不变：模糊测试确认，默认世界中的仲裁结果和 0.1.3 版逐条一致。这个百分比在清单中公开；但捕食者看不到对方的连接，所以只能根据"条件不满足"的结果去试探。这本身也是一种隐藏信息。实现在 `shared/combat.py`，仲裁预检和攻击落地两处使用同一个函数。

**一对一对决（blob 对 stalker）：**

| 相连支援 | deep-dive：存活 / 被杀率 | 捕食有利：存活 / 被杀率 |
|---|---|---|
| 0%（现状） | 15 / 9.8 | 0 / 40.8 |
| 50% | 33 / 6.4 | 9 / 10.8 |
| 100% | 32 / 3.8 | 33 / 4.3 |

到 100% 时，连接体的被杀率（3.8–4.3）已经接近会跑的群体（2.6–3.7）。这个杠杆覆盖了从"身体是活靶子"到"身体和逃跑一样安全"的整个范围。

**四个物种同场（群体、blob、感知、stalker；6 个种子的胜者）：**

| 世界 | 胜者 |
|---|---|
| deep-dive（0%） | 群体 3、感知 2、blob 1、stalker 0 |
| **50%** | **感知 2、群体 2、blob 2**（最均衡） |
| 100% | blob 4（身体开始压制其他策略） |
| 饥荒（0%） | 四种都赢过（有捕食者时，blob 不再独占饥荒） |
| 感知免费 | 感知 4、stalker 2（信息便宜同样有利于捕食者） |

**决定：** `deep-dive` 的 `combat.bonded_support_percent` 已设为 50（`server/worlds/deep_dive.py`），由测试 `test_deep_dive_keeps_its_map_from_spectators` 固定。

**设定后用 8 个种子复核：**

| 相连支援 | 四种同场胜者（8 个种子） | blob 对 stalker：存活 / 被杀率 |
|---|---|---|
| 0% | 群体 4、感知 2、blob 2 | 15 / 9.8 |
| 30% | 感知 3、blob 3、群体 2 | 12 / 10.3 |
| **50%（现在的预设）** | **blob 4、感知 2、群体 2** | **33 / 6.4** |

- 用 8 个种子看，50% 没有 6 个种子时那么均衡：领先者从群体变成了 blob（8 局赢 4 局）。仍然没有哪一类"始终碾压"，但存在偏向 blob 的倾向，之后调整时要留意。
- 30% 在同场时更均衡，但对捕食者几乎没有保护作用（和 0% 差不多），所以保护效果的门槛在 30% 到 50% 之间。50% 是测试过的数值中，能让身体真正抵抗捕食的最低值。
- stalker 在 deep-dive 的同场对局里一局都没赢过，它的优势环境是感知便宜和饥荒。
- §15 的表格是在相连支援为 0 时测的；`tests/blanket_experiment.py` 中由 `deep-dive` 派生的其他世界变体，现在也都带有 50%。

**样本说明：** 6 个种子的胜者统计噪声较大，"2/2/2"和"3/2/1"之间的差别不一定显著。对决结果（被杀率相差 1.5 到 10 倍）是更可靠的证据。
