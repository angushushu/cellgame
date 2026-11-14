# CellGame 核心接口标准 1.0.0-rc.1

本文件规定第三方客户端、算法与世界规则如何对接参考内核。当前为第一版候选标准；候选期间的变动仍须修改版本并更新测试。包版本 `0.2.0` 与接口版本分别管理。动画、网页布局和 GUI 的 HTTP 状态接口不参与游戏规则。

## 1. 公开入口与版本

Python 集成统一从 `cellgame.api` 导入。导入不会打开网页、监听端口或启动进程，且不依赖 `cellgame.client`。原来的内部导入路径暂时保留兼容，新的集成应使用公开入口。

| 接口 | 当前版本 | 作用 |
| --- | --- | --- |
| 核心契约 | `1.0.0-rc.1` | 汇总本文件、注册表、样例与兼容约定 |
| 游戏消息协议 | `2`，兼容 `1` | WebSocket 消息封装与协商 |
| 世界清单 | `manifest_version=1` | 尺寸、感知、可见性、行动能力 |
| 观察格式 | `1` / `2` | 经典全图世界 / 有限感知世界 |
| 玩家 Python 接口 | `PLAYER_API_VERSION=1` | Cell、Entity、Unity 和批量规则 |
| 世界 Python 接口 | `WORLD_API_VERSION=1` | 服主规则钩子及受控命令 |
| 本地模型接口 | 外层 `version=1` | HTTP / stdio 请求与响应；内层观察可为 v2 |

规则文件可声明对应的 Python 接口版本；省略视为 1，未知版本会拒绝加载。版本声明不提供权限隔离，Python 文件始终是可信本地程序。

机器可读定义位于 `shared/contract-v1.json`；`describe_contract()` 返回同一内容。使用 `python -m cellgame contract` 查看，添加 `--schema` 输出 JSON Schema。客户端及服务端的 HTTP 页面均提供只读 `/api/contract` 与 `/api/protocol-schema`。

兼容原则：可以增加可选消息字段；接收者忽略不认识的字段与消息类型。不能在原版本中重排表格列、复用已有动作编号、改变未知信息的含义或扩大玩家权限。二进制表布局的变化需要新的观察格式；传输编码的变化需要新的协议版本。不支持的清单能力必须明确拒绝，不能静默当作已实现。`/api/state`、`/api/preview` 等 GUI 路由、可变世界数组的存储布局、私有下划线成员不属于稳定标准。

## 2. 游戏连接与行动窗口

游戏使用 WebSocket 根路径 `/`；一条消息一个 UTF-8 JSON 对象：

```json
{"type":"hello","payload":{"protocol_version":2,"protocol_versions":[2],"player_name":"Example"}}
```

`protocol_versions` 为客户端明确支持的正整数列表；存在时优先使用它。服务端选择双方明确支持的最高版本，不能假定 99 兼容 2。旧客户端仅提供 `protocol_version` 也可协商；完全不提供视为 v1，限经典世界。radius / blanket 世界必须协商 v2。

`welcome` 包含 `player_id`、`world_w`、`world_h`、`protocol_version`、`contract_version`、`interfaces`、`manifest`、`manifest_hash`、`intention_format`、`tick_rate_ms`、`intention_window_ms` 和 `max_silent_ticks`，以及玩家资料。新增字段在连接旧服务端时可能缺失；行动格式可从清单的观察版本推导。协议 v2 可以连接经典世界，此时仍使用观察 / 行动格式 v1。

清单哈希为 `sha256:` 加十六进制摘要。参考编码：清单按键排序、紧凑 JSON、保留 Unicode，UTF-8 后做 SHA-256。第三方可以直接保留服务端给出的哈希；观察的 `manifest` 应与它一致。目前清单在一次世界运行中固定，`revision=0`，尚未支持热更新和增量清单。

收到 `observation(tick=T)` 后，针对 T 提交至多一批：

```json
{"type":"intentions","payload":{"tick":3,"format":2,"data":[[1,3,0,0,0]]}}
```

这个例子请求编号 1 的细胞原地进食。没有动作也要提交 `data:[]`，它同时表示本轮仍在线。连续 3 个窗口没有有效提交会导致本局细胞死亡。`tick` 必须是 JSON 整数，并等于服务端最后发出的观察时刻。已接受时刻的重复提交会被丢弃；格式错误或未来时刻的提议不会占用后续合法提交的位置。过期消息不顺延到下一轮。

`intention_window_ms` 是从服务端 tick 开始计算的收集窗口上限，包含结算与发送耗时，不是从客户端收到观察起重新计时。默认约为 `tick_rate_ms × 5/6`；本地推理应留出网络和调度余量。T 的行动通常在下一次结算生效，结果出现在后续观察。错误为 `error` 消息，提供 `code`、`message`，主要代码包括 `protocol_unsupported`、`bad_message`、`bad_intentions`、`bad_tick`。`ping` 返回 `pong`。未知扩展消息可以忽略。

协议消息以 `shared/schemas/transport-v2.schema.json` 为结构参考。该 Schema 校验封装、主要头字段和数组元数据；base64 解码后的长度、字段类型、范围、所有权和游戏合法性仍由运行时检查，不能只依赖 Schema。

## 3. 数组与坐标

NumPy / 跨语言数组使用保留包装对象：

```json
{"__ndarray__":{"dtype":"int16","shape":[2],"data":"AQACAA==","byteorder":"little","order":"C"}}
```

固定使用小端、C 顺序、紧密排列，无对象、嵌套结构、子数组、对齐填充或指针。支持 bool，以及 8/16/32/64 位有符号和无符号整数、32/64 位浮点数。结构化表以 `descr:[[字段名, NumPy类型码], ...]` 指定准确顺序；有 `descr` 时按它解码，`dtype` 仅作说明。省略 `byteorder` / `order` 的旧消息按 little / C 解释；显式大端消息会被拒绝。

形状至多四维，维度为非负整数。字节数必须严格等于所有维度乘积 × 每行字节数。每条消息最多 32 MiB，每个解码数组最多 24 MiB；普通 JSON 数字不能是 NaN 或 Infinity。bool 占一字节。各个表的准确字段、类型和枚举以注册表为准；不能根据字段名猜测位宽。JS 等语言应以 DataView / BigInt 读取 64 位整数。

当前几何为二维有界方格：左上角 `(0,0)`，x 向右、y 向下；世界数组为 `[y,x]`，表坐标为 `(x,y)`。连接位从 bit0 到 bit7 是左上、上、右上、左、右、左下、下、右下。清单支持边长 16–512、感知半径至多 8。3D 不属于本版本；未来不能直接给 v2 表塞入 z 列。

`shared/fixtures/` 提供 hello、清单和真实二进制观察样例。`tests/protocol_fixture_test.js` 不使用 Python / NumPy，独立验证字节布局与哈希，可作为其他语言实现的起点。

## 4. 观察与身份

v2 `observation` 包含 `version=2`、`tick`、清单哈希 `manifest`、`world_run`、`cells`、`tiles`、`events`、`constraints`；另有可选的 `materials`、`biomes`。`cells` 只含玩家自有细胞；`tiles` 将所有自有细胞允许感知的格子去重发送一次。`validate_observation()` 检查表布局、身份重复、坐标与层对齐；`expand_observation()` 自动执行该检查，再根据清单、角色、连接和半径重建逐细胞 `percepts`。

| 情形 | 含义 | SDK 判断 |
| --- | --- | --- |
| 未返回的范围内格子 | 未知，不能当作空地 | `cell.sense(dx,dy) is None` |
| occupant 0 | 已观察到的空格 | `p.is_empty` |
| occupant 1 / 2 | 与观察者相连的自己人 / 自己人 | `p.is_bonded` / `p.is_mine` |
| occupant 3 / 4 | 敌方 / 细节隐藏的敌方占据 | `p.is_enemy` / `p.is_hidden` |
| occupant 5 | 世界外部，客户端展开时产生 | `not p.in_bounds` |
| `env_visible=false` | 资源和环境没有被该观察者感知 | 不使用该格食物、温度、材料、群系 |

隐藏属性用 `-1`；隐藏环境的食物为 `-1`、温度为 0，这个 0 不表示实测温度。materials / biomes 缺失不表示全是普通地面；存在时是与 tiles 逐行对应的 uint8 数组，未感知行填 0。SDK 的 `p.material`、`p.biome`、`cell.material_here`、`cell.biome_here` 在不可用时返回 `None`。`Neighbor.observed` 区分未感知，`empty_neighbors()` 只返回已知空格。

参考世界材料：0 普通、1 浆果、2 熔岩、3 尖刺；群系：0 未知、1 草地、2 森林、3 沙漠、4 冻原。数字效果由世界规则决定，不能把“材料 2 一定造成 5 点伤害”写进协议。目前没有通用的材料 / 环境层注册机制，这些层是参考实现的可选扩展。

身份用 `(world_run, cell_id)` 与 `(world_run, entity_id)`，不能只按坐标或裸 ID 缓存。细胞移动保持 ID，出生获得新 ID，服务器重启换 world_run。Entity 按显式连接划分；分裂时主要片段保留编号，融合时贡献最多的原个体保留编号，平局取较小编号。结算后在发出下一次观察前更新身份。`cell.entity_id` / `entity.id` 来自服务端；legacy 适配器没有身份时为 `None`。Unity 目前没有服务端权威编号。

事件种类为 result=0、born=1、died=2；born 的 other 是父细胞 ID。result 码为 ok=0、invalid=1、no_energy=2、duplicate=3、disabled=4、blocked=5、contested=6、interrupted=7、role=8。事件只关于自身细胞；无法归属的非法行不保证有单独事件。当前 died=2 的 code 2 汇总代谢 / 环境死亡，不细分熔岩等原因。

有限感知世界的玩家不接收全图 snapshot / delta。历史地图记忆属于客户端推断，不能显示为实时感知。注意：同一玩家的观察在本地会合并，Entity / Unity 可以读取本玩家的整批信息；协议限制玩家能获得什么，不验证玩家程序内部是否只做局部计算，也不证明严格的条件独立性。

## 5. 玩家接口

新手只需选择一个入口，省略版本声明也能运行：

```python
PLAYER_API_VERSION = 1

def decide_cell(cell):
    if cell.food_here > 0 and cell.energy < 20:
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= 13:
        return cell.reproduce(empty[0], bond=True)
    return cell.wait()
```

| 入口 | 调用单位 | 返回 |
| --- | --- | --- |
| `decide_cell(cell)` | 每个自有细胞 | 一条动作或 None |
| `decide_entity(entity)` | 每个显式连接体 | 动作列表、一条动作或 None |
| `decide_unity(unity)` | 当前玩家的全部 Entity | 动作列表、一条动作或 None |
| `decide(cells, neighborhood, env, constraints, tick, observation=None)` | 整批观察 | n×7 整数表或 None |

同一文件若有多个入口，按 decide → decide_cell → decide_entity → decide_unity 选择。旧版五参数 decide 继续支持；只有声明 observation 或 **kwargs 的函数才收到第六项关键字参数。

Cell 的基础读写方法见 `automaton_zh.md`。新增稳定读取为 `id`、`entity_id`、`world_run`、`tick`、`role`、`last_result`、`material_here`、`biome_here`。`cell.memory` 是本地持久字典，跟随细胞 ID，死亡、换世界或规则进程重启时丢失，不是服务器存储。Entity / Unity 提供 `cells`、`members`、`cell_count`、`energy`、`boundary`、`tick`；Entity 另有 id、world_run。对象每轮重建，不能以 Python 对象地址作持久身份。Unity 可组合本玩家的 Cell / Entity / Unity，成员不能重叠；默认入口提供全部 Entity。它尚不代表持久群体身份、跨玩家连接或受服务端约束的通讯网络。

Python 动作 / 本地模型响应沿用七列 `[src_x,src_y,tgt_x,tgt_y,action,0,param]`。第六列保留以兼容旧程序，不能决定攻击强度。`to_intentions()` 检查形状和整数类型，丢弃越界、未知行动、无权源格等行；客户端 SDK 不将小数或 bool 自动转成动作整数。`intentions_to_v2()` 转为网络五列 `[cell_id,action,dx,dy,param]`。不要把七列本地动作直接发送给 v2 世界。

| ID | 动作 | ID | 动作 |
| --- | --- | --- | --- |
| 0 | move | 6 | set_state |
| 1 | attack | 7 | bond |
| 2 | reproduce | 8 | unbond |
| 3 | eat | 9 | transfer |
| 4 | change | 10 | move_group |
| 5 | die | 11 | sense |

动作不存在独立 WAIT 编号，等待用 None / 空列表。param 为 0–2147483647 整数；动作另有更窄限制，例如 transfer 1–100、change 0–32767、sense 1–8。移动、攻击、繁殖等实际目标仍限一格；sense 用自身目标、半径放在 param。网络层允许偏移 -8..8 只是输入边界，不能让移动跨八格。每个细胞每轮至多一个行动，所有权、距离、能量、角色、世界开关、并发冲突和最终影响均由服务器裁决。

批量适配器 cells 为 n×5 `[x,y,type,state,energy]`；neighborhood 为 n×45，九个格子按从左上到右下展开，每格 `[is_mine,species,type,state,energy]`；env 为 n×12 `[temp,food_here,九格食物,bonds]`。旧表不能表达全部隐藏 / 未知语义，高级程序应使用 observation 或 Cell.sense。

## 6. 本地 ML 接口

HTTP 使用本机 `POST /decide`（路径可自行配置）；stdio 每行一份相同 JSON。请求外层 `version=1`、`contract_version`、`tick`、旧批量表和 `constraints`；非 legacy 另附 `observation`，其 version=2，cells / tiles / events 是字段名到值的普通 JSON 对象列表，材料 / 群系为普通列表。

响应格式不变：

```json
{"tick":3,"actions":[[4,4,4,4,3,0,0]]}
```

tick 必须与请求相同且为整数；actions 必须是列表，最多等于本次自有细胞数；HTTP 和 stdio 使用同一校验器。客户端将合法动作转换为网络提议。超时或异常时客户端显示错误，本轮返回空动作。模型进程可自行使用 PyTorch、AIF、搜索或其他运算，接口不限制算法。示例 `python -m cellgame.examples.local_agent_service`，详细接入说明见 `automaton_zh.md`。这些响应不赋予模型改世界能量参数的权限。

## 7. 服务端世界接口

规则文件声明 `WORLD_API_VERSION=1`（可省略），至少提供 on_epoch。可选 MANIFEST 交给现有清单校验器编译。server.properties 用 `world-rules=my_world.py` 或 `world-preset=go` 选择；它选择代码，不把围棋等具体玩法写死成内核开关。

| 钩子 | 输入 / 输出 | 时机 |
| --- | --- | --- |
| `filter_actions(intentions, players, world_view, tick)` | 结构化意图 + 等长玩家 ID；返回等长 bool 掩码 | 基础裁决前，False 表示禁止 |
| `after_actions(events, world_view, tick)` | 成功行动事件；返回命令列表 | 行动应用后，目前事件只覆盖成功进食 |
| `before_ecology(world_view, tick)` | 世界快照；返回命令列表 | 代谢及死亡处理前 |
| `on_event(event, world_view)` | 本轮 counts、summary；返回事件命令 | 生态处理及玩家进出之后 |
| `on_epoch(summary, tick)` | 返回参数字典 | on_event 之后，默认每 10 tick |

玩家意图经过 filter 后仍须通过内核校验。WorldView 提供 width、height、get_region(x,y,w,h)；区域与世界交集返回二维数组副本，完全越界为空，负宽高拒绝，包含 cell_id 方便防止误作用到替代细胞。修改副本不会修改世界。

after_actions / before_ecology 的命令为 kill 或 adjust_energy，支持可选 cell_id；能量变动为 -100..100 的整数。整批最多 2×世界面积条，全部验证成功才执行；失效 cell_id 直接跳过。on_event 独立支持 add_food（0..100）和 set_reproduction，最多处理前 1000 条，非法条目忽略。on_epoch 参数范围见 `world_rules_zh.md`。这些现有命令集合分别保留，不能互换。

当前默认钩子时间预算为 100ms。filter / after_actions / before_ecology 超时、异常或返回格式错误会停止模拟；on_event / on_epoch 的回调异常或超时记录后丢弃该次结果。线程超时不能终止仍在运行的 Python 代码；这不是安全沙箱。不要把不可信远程脚本作为世界规则加载。参数处理仍保留部分旧式忽略行为，不能将内部函数返回格式当成无限通用的修改世界 API。

参考服务器的一轮顺序：上轮提议 → filter → 基础裁决和行动 → after_actions → before_ecology → 代谢 / 死亡 → Entity 身份更新 → 玩家进出 → on_event → 周期参数更新 → 观察 → 收集本轮行动 → 处理静默玩家 → delta → tick 加一。收集期间也可处理新玩家加入、资料和离开，迟到动作不挪用到下一轮。

`resolve_tick(world, pending, rules=None)` 是不依赖网络的“行动结算 + 生态”阶段。pending 为 `{player_id:(INTENTION_DTYPE数组,等长玩家ID数组)}`；返回行动计数。它不推进 tick、不管理连接，也不调用 on_event / on_epoch。省略 rules 不会自动加载默认材料规则。嵌入式宿主需要自行安排外围阶段：

```python
from cellgame.api import (
    WorldState, build_manifest, gather_observation, expand_observation,
    resolve_tick, load_rule, to_legacy_batch, to_intentions,
)
import numpy as np

manifest = build_manifest({"perception": {"model": "radius", "radius": 1}})
world = WorldState(256, 256, seed=0)
world.configure(manifest)
world.place_cell(1, 40, 40, energy=20)
rule = load_rule("def decide_cell(cell): return cell.eat()")
obs = expand_observation(gather_observation(world, 1, manifest, "example-run"), manifest)
batch = to_legacy_batch(obs)
actions = to_intentions(rule(batch["cells"], batch["neighborhood"], batch["env"],
                             batch["constraints"], batch["tick"], observation=obs),
                        batch["cells"], world.w, world.h)
world.end_observation_window()
counts = resolve_tick(world, {1: (actions, np.full(len(actions), 1, dtype=np.int32))})
world.tick += 1
```

开发其他语言或独立界面时可以只使用协议；无需使用这个 Python 内存宿主。可运行的无 GUI 示例为 `python -m cellgame.examples.protocol_agent --server ws://127.0.0.1:8765`，连接 radius / blanket 世界。

## 8. 标准的当前边界

已经固定的候选范围是消息编码、现有观察表、动作编号与提议、三个玩家入口、现有世界钩子、权限及身份范围。参考内核仍是二维 NumPy 实现；本轮没有拆出或发布单独的 core wheel。

后续需要独立设计并增加版本的内容：持久 Unity 身份及成员关系、跨个体通讯限制、通用材料 / 环境层注册、完整生命周期订阅、跨实现确定性重放及重新同步、可替换的全部基础物理规则、3D 几何。现有 GUI HTTP、聊天与资料扩展、动画和存档细节不作为这份核心标准的冻结范围。新界面应依赖协议和公开入口，避免绑定网页内部状态。
