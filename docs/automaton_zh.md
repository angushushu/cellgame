# 五分钟编写一个物种自动机

打开客户端，在“进阶模式 · 代码与本地模型”里将以下代码放入编辑器，先点“预览代码”，再点“启用代码”。也可以将它保存为 `my_species.py`，用 `client\start.bat --rules my_species.py` 启动。

```python
def decide_cell(cell):
    if cell.food_here > 0 and cell.energy < 20:
        return cell.eat()

    empty = cell.empty_neighbors()
    if empty and cell.energy >= 13:
        return cell.reproduce(empty[0])

    if empty and cell.energy > 4:
        return cell.move(empty[0])

    return cell.wait()
```

每个时刻，程序对自己拥有的每个细胞调用一次 `decide_cell(cell)`。每个细胞返回至多一个动作，服务器会检查这个动作是否合法，目标被占用等情况可能使动作失败。没有动作时返回 `cell.wait()` 或 `None`。两个方向分量分别是横向和纵向的偏移；例如 `(1, 0)` 表示向右一格。

## 细胞可读取的信息

| 属性或方法 | 含义 |
| --- | --- |
| `cell.x`, `cell.y` | 当前位置 |
| `cell.energy` | 当前能量 |
| `cell.food_here` | 脚下食物量 |
| `cell.material_here`, `cell.biome_here` | 感知世界中的脚下材料和群系；未知或旧世界为 None |
| `cell.id`, `cell.entity_id`, `cell.world_run` | 细胞、连接体及本次世界运行的身份；旧世界 ID 为 None |
| `cell.cell_type` | 细胞类型；0 为普通，1 为装甲 |
| `cell.state` | 本细胞的公开整数状态 |
| `cell.tick` | 当前时刻编号 |
| `cell.constraints` | 世界条件，例如 `reproduce_enabled` |
| `cell.empty_neighbors()` | 地图内空邻格的 `(dx, dy)` 列表 |
| `cell.surrounding()` | 八个邻格的对象，含地图边界信息 |

每个邻格对象提供 `dx`、`dy`、`in_bounds`、`is_empty`、`is_mine`、`is_enemy`、`species`、`cell_type`、`state`、`energy`、`food`、`material`、`biome`、`block` 和 `observed`。地图外的邻格 `in_bounds` 为假，不是空格；有限感知中 observed 为假表示未知，也不是空格。

`cell.sense(dx, dy).block` 和邻格的 `block` 使用 0 空、1 木头、2 石头、3 沙子；不可见或旧版服务器无此数据时为 `None`。`is_empty` 只表示没有细胞，繁殖时还需确认方块为空。向方块移动会尝试推动，向方块攻击会尝试破坏。

## 可返回的动作

| 动作 | 用法 |
| --- | --- |
| 进食 | `return cell.eat()` |
| 移动 | `return cell.move((dx, dy))` |
| 繁殖 | `return cell.reproduce((dx, dy))` |
| 攻击 | `return cell.attack((dx, dy))`；目标可以是敌方细胞或方块 |
| 修改类型 | `return cell.change_type(1)`；1 是装甲 |
| 修改状态 | `return cell.set_state(1)` |
| 等待 | `return cell.wait()` |

例如，用公开状态让细胞每个时刻在 0 和 1 之间切换：

```python
def decide_cell(cell):
    return cell.set_state(1 - cell.state)
```

状态是 0 至 2,147,483,647 的整数。设置状态也占用该时刻的一个动作；移动会保留状态，繁殖出的新细胞从 0 开始。状态由服务器存储，并可被邻近细胞与世界观察者读取；不要把秘密信息存入状态。

高级玩家仍可以编写批量 `decide(cells, neighborhood, env, constraints, tick)`，或者从进阶模式连接本地 HTTP 模型服务。每次收到的是同一物种的整批观察；只允许局部作用，但游戏不强制验证本地程序内部是否只使用单个细胞的邻域。预览采用默认世界规则，服务器自定义的世界可能不同。

如果同一份文件同时定义了 `decide` 和 `decide_cell`，游戏会优先使用高级批量函数 `decide`。想使用单细胞接口时，请删除或重命名旧的 `decide` 函数。


## 细胞连接与协作

需要新版客户端和服务端。默认没有连接，旧规则无需修改。相邻细胞不等于已连接；连接双方必须属于同一玩家。`is_mine` 代表玩家归属，不代表同一生物。

```python
def decide_cell(cell):
    for n in cell.surrounding():
        if n.is_bonded and n.energy < 6 and cell.energy >= 10:
            return cell.transfer((n.dx, n.dy), 3)
    if cell.food_here > 0 and cell.energy < 20:
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= 13:
        return cell.reproduce(empty[0], bond=True)
    return cell.wait()
```

- `cell.reproduce(direction, bond=True)`：成功出生时自动连接父子。
- `cell.bond(direction)` / `cell.unbond(direction)`：连接或断开一个同玩家的相邻细胞。
- `n.is_bonded`：该邻格是否与自己连接；`cell.bonds` 为八方向位掩码，0 表示没有连接。
- `cell.transfer(direction, amount)`：向连接的邻居分享 1–100 能量，最多保留发送者 1 点，接收方不超过 32767；实际数量受两者当前状态约束。
- 连接、断开、分享各占一次行动。普通 `move` 不能移动已连接细胞；`cell.move_group(direction)` 尝试让整个连接组同时平移。每个细胞按普通移动规则各自扣除能量，任意一个细胞的目标受阻或能量不足则整体不动；最多 256 个细胞，本轮受攻击的细胞组不移动。一个组有多个移动提议时，选坐标从上到下、从左到右最靠前的提议。一次整体移动是游戏提供的便利操作，会在一个时刻影响整个连接组，不等同于严格逐边传播的局部规则。
- 细胞死亡时连接自动断开。
- 信号可用已有 `cell.set_state(value)` 和邻居的 `n.state`；该状态公开，并且设置状态占用一次行动。
- 界面中“连接相邻的自己人”可能合并原本独立的细胞团。关闭自动连接不会解除已建立的连接；可在界面开启“断开已有连接”，或用代码逐一断开。

批量接口的 `env` 最后一列 `env[:, 11]` 是当前细胞的连接位掩码；方向顺序为左上、上、右上、左、右、左下、下、右下。`env[:, 2:11]` 仍是 3×3 食物数据。更多示例见 `species/cooperative.py`。

地图中的边界表示与空地、其他玩家或地图边缘相接，并非形式化的马尔可夫毯，也不限制外部信息绕过边界。


## 感知世界中的新接口（0.2）

在用 `--perception radius` 启动的世界里，每个细胞有稳定的编号，还能看到半径内的格子：

```python
def decide_cell(cell):
    cell.memory["age"] = cell.memory.get("age", 0) + 1   # 跟随这个细胞，直到它死亡
    for p in cell.percepts():                             # 感知范围内、地图内的格子
        if p.is_enemy and p.energy < cell.energy:
            if max(abs(p.dx), abs(p.dy)) == 1:
                return cell.attack(p.direction)
    here = cell.sense(0, 0)                               # 没有感知到的格子返回 None
    if here and here.food > 0:
        return cell.eat()
    return cell.wait()
```

| 接口 | 含义 |
| --- | --- |
| `cell.id` | 稳定的细胞编号；legacy 世界中为 `None` |
| `cell.percepts()` | 感知到的格子列表，每项有 `dx`、`dy`、`direction`、`occupant`、`is_empty`、`is_mine`、`is_bonded`、`is_enemy`、`species`、`cell_type`、`state`、`energy`、`food`、`temp` |
| `cell.sense(dx, dy)` | 指定偏移的格子；没有被感知到时返回 `None` |
| `cell.memory` | 只属于这个细胞的字典，跨 tick 保留，细胞死亡后清除；规则进程重启时丢失 |

行动仍只能作用于相邻格子，感知半径更大并不改变这一点。`empty_neighbors()`、`surrounding()` 等旧接口继续可用，读取的是内圈 3×3。

## 毯感知世界（`--world-preset deep-dive`）

| 接口 | 含义 |
| --- | --- |
| `cell.role` | `"boundary"`（边界）或 `"interior"`（内部）；其他世界中为 `None` |
| `cell.last_result` | 这个细胞上一个行动的结果：`"ok"`、`"blocked"`、`"no_energy"`、`"contested"`、`"role"` 等；没有行动时为 `None` |
| `cell.extend_sense(r)` | 花费 `r ×` 每格成本的能量，下一份观察中看到半径 `r` |
| `p.env_visible` | 这个格子的资源层是否可见；不可见时 `p.food` 为 `-1` |
| `p.is_hidden` | 其他玩家的内部细胞：看得出有东西，但看不到属性（都为 `-1`） |

内部细胞看不到外部，在深潜世界里也不能进食，只能靠相连的同伴通过 `cell.transfer` 传能量；但内部细胞的代谢更便宜，也不会被攻击（攻击只能打到相邻的格子，而有敌人相邻的细胞一定是边界细胞）。
