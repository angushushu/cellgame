# 多尺度控制接口（实验版）

世界仍是二维，所有行动由服务器裁决。原有 `decide_cell(cell)` 和批量 `decide(...)` 保持可用；还可以定义 `decide_entity(entity)` 或 `decide_unity(unity)`，任选一个入口。规则在本地进程运行，进程重启时 Python 内存会丢失；每个 tick 的对象都会重新构建。

`Entity` 根据服务器观察提供的物理连接重建。`entity.cells` / `entity.members` 是细胞元组，`entity.energy` 是总能量，`entity.boundary` 是外边界细胞。`cell.is_boundary` 和 `cell.boundary_directions` 基于同一连接组件；它们把不属于组件的空间（包括空腔和世界边缘）视作外部。

```python
def decide_entity(entity):
    actions = []
    for cell in entity.boundary:
        if cell.food_here > 0 and cell.energy < 20:
            actions.append(cell.eat())
    return actions
```

`decide_unity(unity)` 当前把该玩家观察到的所有 Entity 汇总为一个客户端群体，`unity.members` 为 Entity，`unity.cells` 为所有细胞，`unity.energy` 为总能量，`unity.boundary` 和 `unity.boundary_directions(cell)` 基于成员并集。开发者也可用 `Unity([...])` 组合互不重叠的 Cell、Entity 或 Unity；这是本地计算视图。它不会创建服务器上的持久群体、跨玩家连接或有限距离通信，也不是服务端对信息隔离的保证。

```python
def decide_unity(unity):
    actions = []
    for entity in unity.members:
        for cell in entity.boundary:
            if cell.food_here > 0 and cell.energy < 20:
                actions.append(cell.eat())
    return actions
```

所有入口返回单个细胞动作、动作列表或 `None`；服务端仍验证所有权、行动和资源。客户端可访问其他数据，故这些接口不保证严格马尔可夫毯或隐私隔离。Unity 在客户端没有持久身份，组件分裂合并后应自行处理记忆归属。未来的群体成员协议、共享限制、跨层冲突与服务器权威身份仍需独立实现。

## 界面：边界与形态示例

世界地图中可切换 Entity 边界、我的 Unity（本地）边界或关闭。Entity 使用服务器同步的连接组件编号；Unity 边界是当前玩家所有细胞的本地并集，并非服务器认证的群体成员。边界画出各占用格的外边，不表示不相连个体之间存在一条物理围墙。放大地图可更清楚地观察。

“组合你的行为”提供蜘蛛形态、十字生物和群体觅食。两种形态按模板选择相邻空位，以带连接的普通繁殖慢慢生长，服务器决定动作能否成功。它们不会凭空生成、移动或删除细胞；障碍、能量不足、细胞死亡、其他行为和现有形状不匹配可能导致暂停或形变。形态是二维格子示意而非真实蜘蛛。

群体觅食示例把本地所有自有细胞看到的最强食物方向共享给其他成员，仍按细胞逐个提出行动。这不是距离有限通信，也不会创建服务器端持久 Unity。拖动模块或使用箭头可以改变行为优先级；修改后需点击“应用这个物种”。
