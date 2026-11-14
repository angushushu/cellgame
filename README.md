# CellGame — multiplayer cellular species prototype

The server owns the world and validates each player's proposed actions. Player rules run locally. The stock client sends the species name and intentions, not Python source. Rules are ordinary Python code with the user's local permissions; run only code you trust.

## Install and start (planned PyPI release)

The project is packaged as **one distribution**, providing both the server and the player client, so that the protocol and local preview use matching versions. The name `cellgame` is provisional until availability and ownership are verified on PyPI. The following PyPI command works only **after** the package has been published:

```bash
python -m pip install cellgame
cellgame-server
# In a second terminal:
cellgame-client
```

Open the server dashboard at http://localhost:8080/ and the player console at http://localhost:8081/. Equivalent commands are `python -m cellgame server` and `python -m cellgame client`. To choose a world, use `cellgame-server --world-preset lush` (also `balanced` or `challenging`). Players on another computer can enter the server's WebSocket address in the client console.

To install the locally built wheel before publication, use `python -m pip install path/to/cellgame-0.2.0-py3-none-any.whl`. Dependencies must be available through pip. Python 3.10 or newer is required. The default server listens on all interfaces; use `--host 127.0.0.1` for local-only play. The current prototype has no authentication or encrypted transport; use it on a trusted network.

For programming, the supported import namespace is `cellgame`, for example `from cellgame.species.simple import Cell`. Older custom code that imports `species`, `server`, `client`, or `shared` directly should change those imports to `cellgame.species`, `cellgame.server`, `cellgame.client`, or `cellgame.shared` before using the installed package. Single-cell rules that only define `decide_cell(cell)` need no import change.

## Start from source on Windows

Double-click `server/start.bat`, then `client/start.bat`. Open the player console at http://localhost:8081/ and the spectator page at http://localhost:8080/. Python 3.10+ is required; the scripts create a virtual environment and install dependencies on first use. Enter another server's WebSocket address in the console to join it.

Manual startup from the project directory:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m server.main
.\venv\Scripts\python.exe -m client.main
```

On Unix use `venv/bin/python`. Server options include `--host`, `--port`, `--http-port`, `--tick-ms`, `--seed`, and `--world-rules`. This prototype has no authentication or encrypted transport; use it on a trusted network.

## World chat

Connected players can use “世界公屏” in the player console. The server dashboard shows the same conversation read-only. The server keeps the latest 100 messages in memory until it restarts, and sends them to players who join or reconnect. Messages are limited to 200 characters and one per second per player. Both the client and server must be updated to use chat; a new client connected to an older server will show that chat is unavailable. Player messages are displayed as text, not HTML.

## World rules and organisms

The server authoritatively sets movement, reproduction, feeding, combat and armor costs and effects. In the server dashboard, expand the next-world settings to choose values and generate a launch command. Advanced hosts can edit and download a Python world-rule file in that panel; its `on_epoch` can change validated world parameters as the world runs. See `docs/world_rules_zh.md` for the rule interface and the meaning of identity, offspring, split and merge.

Hover over a cell in either world map to inspect its bonded organism, including cell count, total energy, direct offspring, parent and origin. IDs and lineage are scoped to one server run.

## Make a species

The player console starts in combination mode with a balanced species. Pick a
template, enable or disable behaviors, adjust priority and thresholds, then
preview or apply it. The built-in balanced species starts automatically when
the client connects. Use the collapsed advanced section to edit Python or
connect a local model service. Switching to combination mode preserves the
last custom code in the current client session.

The server page shows the running world, players, environment and activity.
Under “准备下一个世界”, choose balanced, lush or challenging conditions,
speed, seed and ports to generate the next startup command. The page does not
change a running world: stop the server and run that command from the project
directory in PowerShell. Custom world rules remain available through
`--world-rules`.

Use “连接与玩家资料” in the player console to update your nickname and color
without disconnecting. The server confirms changes to all connected players.
Profiles are kept for the current client session, not in a persistent account.
Both maps support +/− controls, the mouse wheel, dragging, and keyboard
navigation. Player colors appear in the player list; green empty tiles are
food, and armored cells have a pale inner border when zoomed in. Movement,
births, eating, sharing and deaths have visual effects. The client starts with
breathing and event animations enabled; use the “动态 开/关” button to toggle them.
The server viewer follows reduced-motion system preferences by default.
Effects are visual only and do not change the
simulation. Older servers still work but do not send the new animation events.

The public core contract is documented in [CORE_STANDARD_zh.md](docs/CORE_STANDARD_zh.md)
(`1.0.0-rc.1`). Third-party integrations can import `cellgame.api` without loading
the GUI, or implement the WebSocket protocol directly. Run `python -m cellgame contract`
for the machine-readable registry, or add `--schema` for JSON Schema. The review and
remaining extensions are in [CORE_REVIEW_zh.md](docs/CORE_REVIEW_zh.md).

The simplest Python rule is a single `decide_cell(cell)` function; see
`docs/automaton_zh.md` or the “五分钟入门” link in the player console. For example:

```python
def decide_cell(cell):
    if cell.food_here > 0:
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= 13:
        return cell.reproduce(empty[0])
    return cell.wait()
```

The Python adapter in `species/simple.py` provides `Cell.eat()`,
`move(direction)`, `reproduce(direction)`, `empty_neighbors()` and
`wait()`. They return proposals; the server decides whether they succeed.

### Local HTTP model service

In the advanced section, enter a loopback HTTP URL such as
`http://127.0.0.1:9000/decide` and enable it. The client sends a POST once
per received observation. The JSON request has `version`, `tick`, `cells`,
`neighborhood`, `env` and `constraints`; the response must contain the same
`tick` and an `actions` list as described below. Only loopback HTTP addresses
are accepted and redirects are rejected. Enabling the URL does not establish a
connection immediately; the interface reports the result after a game tick.
The local preview tests a composition or code, not the HTTP service.

`examples/local_agent_service.py` is a working HTTP adapter with a trivial
hand-written policy, not a machine-learning model. Replace its
`choose_actions` function with your own model inference. For example:

```powershell
.\venv\Scripts\python.exe -m cellgame.examples.local_agent_service
```

Ordinary language-model chat endpoints need an adapter that converts game
observations to actions; they cannot be used directly as this endpoint.

Advanced rules can implement `decide(cells, neighborhood, env, constraints, tick)` and return rows `[src_x, src_y, tgt_x, tgt_y, action, strength, param]`. `cells` is `(n,5)` with x, y, type, state, energy; `neighborhood` is `(n,45)`, a flattened 3x3 grid of five cell attributes; `env` is `(n,12)`, with temperature, food on the cell, nine food values in the 3x3 neighborhood, and a connection bitmask. Strength is ignored: the server computes it from the source cell's energy. Existing rules using the first two env columns continue to work.

An independent local program can act as a headless agent. Put the command
after `--agent` (it must be the last option):

```powershell
.\venv\Scripts\python.exe -m client.main --headless --name external --agent .\venv\Scripts\python.exe -u species\stdio_example.py
```

The client sends one UTF-8 JSON line per tick to stdin with `version`, `tick`,
`cells`, `neighborhood`, `env`, and `constraints`. The program must return
one JSON line on stdout, e.g. `{"tick": 3, "actions": [[1,2,1,2,3,0,0]]}`.
Write diagnostic messages to stderr, not stdout. The agent may keep private
state in its process. If it fails or exceeds the local execution timeout,
the client sends no actions for that tick and restarts it on a later tick.
The example demonstrates the protocol using Python; any language capable of
reading and writing JSON lines can be used.

Each cell may propose one action per tick. MOVE, ATTACK and REPRODUCE must target an adjacent cell; EAT, CHANGE, SET_STATE and DIE target the source itself. `cell.set_state(n)` changes an integer in the range 0–2147483647, consumes the cell's action for that tick, and costs no energy. State follows a moving cell, newborns start at zero, and the value is public. The server checks ownership, bounds, energy and tick, then resolves contested targets deterministically. Attacking a cell and that cell eating are distinct interactions. Actions use the pre-tick state and are applied in the order DIE, CHANGE, SET_STATE, EAT, REPRODUCE, MOVE, ATTACK; attacks against a cell that has moved or died do not land.

Cell type 1 is armored: its defense is its energy plus 3, and moving costs
3 energy instead of 2. Changing type costs 1 energy. A type change in the
current tick affects defense starting with the next tick because attack
eligibility is evaluated against the previous snapshot. The built-in wall
uses this type.

Python rules run in a persistent local child process. Variables held in that
process survive between successful ticks. A rule timeout terminates the worker,
so its private state is lost and it is restarted on the next tick. Loading a
replacement first validates it in a new worker; an invalid replacement leaves
the previous rule running. This process is not a security sandbox. Because it
is a daemon process, Python's multiprocessing module cannot create child
processes from it; use the external-agent interface for that use case.

## Default world and preview

The default ecology consumes one energy per occupied cell every 10 ticks; cells at zero energy die and leave two food units. World rules can set `metabolism_interval` (0 disables it), `food_regrow`, `food_regrow_near_cells`, `temp_delta`, and `reproduce_enabled` in `on_epoch`. The default world distributes 30 additional food deposits near occupied cells per epoch. This is a configurable game mechanic. The default temperature changes over time. Food and temperature changes are included in live world updates.

World rules may also define `on_event(event, world_view)`. It receives a
`tick` event with action and death counts after ecology, before epoch rules,
plus a region-reading view. It can return a list such as
`[{"type": "add_food", "x": 3, "y": 4, "amount": 2}]` or
`[{"type": "set_reproduction", "enabled": false}]` (use Python `False` in
Python source). Commands are validated and bounded; epoch rules run afterward
and may override the reproduction setting. Python world rules are trusted code,
not sandboxed.

The 32x32 preview uses the default world rules, seeded environment and the same arbiter and ecology, but its map size, spawn and opponents differ from a live server. It does not automatically import a server's custom world rules. Player rules may themselves use randomness or outside information; a world seed alone cannot reproduce those decisions. The ecology is an experimental baseline, not yet balanced.

Browser previews run in a terminable child process with a 20-second timeout.
Rule exceptions are reported to the console instead of silently turning into
empty actions. The direct Python `run_preview` function can also take
`world_rules_path` for trusted custom world rules.

## Record and inspect a game

To save a world playback, supply a new filename when starting the server:

```powershell
.\venv\Scripts\python.exe -m server.main --record match.jsonl
.\venv\Scripts\python.exe -m server.replay match.jsonl
.\venv\Scripts\python.exe -m server.replay match.jsonl --tick 10
```

Recordings contain the initial snapshot, subsequent cell and environment
changes, and player names/events; they do not contain player rule source.
Existing files are never overwritten. The replay command reconstructs and
summarizes the saved state; `server.replay.iter_replay` exposes individual
frames to Python code. This is a state playback rather than a re-execution of
player programs. The current version does not include a graphical replay viewer.

## Tests

```powershell
.\venv\Scripts\python.exe tests\boundary_test.py
.\venv\Scripts\python.exe tests\arbiter_regression.py
.\venv\Scripts\python.exe tests\smoke_test.py
.\venv\Scripts\python.exe tests\sim_tick_test.py
.\venv\Scripts\python.exe tests\external_agent_test.py
.\venv\Scripts\python.exe tests\world_event_test.py
.\venv\Scripts\python.exe tests\armor_test.py
.\venv\Scripts\python.exe tests\rule_executor_test.py
.\venv\Scripts\python.exe tests\preview_test.py
.\venv\Scripts\python.exe tests\replay_test.py
.\venv\Scripts\python.exe tests\composer_test.py
.\venv\Scripts\python.exe tests\service_controller_test.py
.\venv\Scripts\python.exe tests\console_api_test.py
.\venv\Scripts\python.exe tests\dashboard_api_test.py
.\venv\Scripts\python.exe tests\ui_contract_test.py
.\venv\Scripts\python.exe tests\world_presets_test.py
.\venv\Scripts\python.exe tests\profile_test.py
.\venv\Scripts\python.exe tests\single_cell_test.py
.\venv\Scripts\python.exe tests\ecology_benchmark.py --seeds 5 --ticks 200
.\venv\Scripts\python.exe tests\e2e_test.py
.\venv\Scripts\python.exe tests\gui_check.py
```

`ui_contract_test.py` uses Node.js to check the page scripts; the game itself
does not require Node.js.

## Known limitations

- Players receive a full world snapshot and spectator data is public. The server enforces action locality, but cannot prove local sensing or local internal computation.
- The server kills a player's cells upon disconnect. Reconnect grace and persistent world saves are not implemented.
- World rules use Python threads, not a security sandbox; a timed-out world rule thread cannot be forcibly stopped. The direct Python preview function also executes rules in its caller's process.
- The event API currently covers tick events, food additions and the reproduction switch.
- Environment changes send full food or temperature arrays. Larger worlds and many players need incremental updates and rate limits.



### 细胞连接与协作

物种实验室的“细胞协作与连接”可启用父子自动连接、相邻自己人连接和向低能量邻居分享能量；先预览再应用。连接组可选择整体移动；要求所有目标可用且每个细胞有足够能量，最多 256 个细胞。关闭自动连接不会解除现有连接。客户端和服务端均需更新并重启。

编程玩家可从进阶模式载入 `species/cooperative.py`；接口及连接约束见 [docs/automaton_zh.md](docs/automaton_zh.md)。地图上的边界是空间提示，并不保证严格马尔可夫毯。


### 多尺度控制（实验版）

在保留细胞规则的同时，可用 `decide_entity(entity)` 控制连接的细胞，或用 `decide_unity(unity)` 协调当前玩家观察到的全部个体。群体当前是客户端视图，不是服务器持久群体；详细范围与示例见 [多尺度接口](docs/MULTISCALE.md)。界面支持搜索、拖动和按钮调整行为模块。世界仍是二维模拟，地图上的立体方块是视觉效果。


### 感知模型与世界清单（0.2 实验版）

服务器可以用 `--perception radius --sense-radius 2` 启动"半径感知"世界：每个细胞只能感知半径内的格子，服务器不再向玩家发送全图，只发送各自的观察（观察格式 v2）。默认仍是 `legacy`，行为与 0.1.x 相同。半径感知世界需要 0.2 及以上的客户端；旧客户端连接时会收到明确的更新提示。规则代码可以使用 `cell.id`、`cell.sense(dx, dy)`、`cell.percepts()` 和 `cell.memory`。完整设计、当前实现范围和已知限制（服务器观察页仍公开全图）见 [docs/WORLD_MANIFEST_zh.md](docs/WORLD_MANIFEST_zh.md)。

`--world-preset deep-dive`（深潜）是第一个"毯感知"世界：细胞只能通过边界感知外部，内部细胞只看得到相连的同伴；`cell.extend_sense(半径)` 可以花能量看得更远；食物主要长在一个看不见、绕地图转圈的肥沃区。示例物种 `species/swarm.py`（盲目群体）、`species/blob.py`（长出内部的连接体）、`species/sensing_forager.py`（付费感知 + 记忆）和 `species/predator.py`（被动捕食者）使用同一套经济规则，只在策略上不同；`species/stalker.py` 是会囤积能量、感知并追击猎物的主动捕食者；`python tests/blanket_experiment.py` 可以比较它们在不同世界规则下的胜负。M2 的实现范围、验证实验、平衡和捕食实验见 [docs/WORLD_MANIFEST_zh.md](docs/WORLD_MANIFEST_zh.md) §14–§16；世界规则可以用 `combat.bonded_support_percent` 让相连的身体整体防御。

**繁殖规则由世界决定。** 繁殖的最低能量、消耗和新生细胞的能量都是服务器的世界参数（`reproduce_min_energy`、`reproduce_cost`、`child_energy`），客户端无法改变。玩家页面中的 "breed at ≥" 只决定物种在能量达到多少时**尝试**繁殖；设定值低于世界下限时，组合物种会自动按下限执行，界面也会显示实际值（例如 `10 → 25`）。面板下方的 "world" 一行显示当前世界的这些规则。

**地图显示。** 放大后，细胞画成圆形液滴，相连的细胞融合成一整块液体（就是一个 entity）；移动、出生、死亡、进食、攻击和分享能量都有动画。深潜等感知世界里，动画由客户端根据自己的细胞前后两次观察的变化推算出来，不会泄露看不到的信息。

### 设置文件：server.properties 与 client.properties

双击 `Start-Server.bat` / `Start-Client.bat` 时，游戏使用游戏目录里的 `server.properties` / `client.properties`。文件不存在时会自动创建，每一项都附有中文说明。命令行参数优先于设置文件，设置文件优先于默认值；值留空表示使用默认值，或者使用所选世界自身的设置。

- `server.properties` 包括：监听地址和端口（`server-ip`、`server-port`、`web-port`）、世界（`world-preset`，或者用 `world-rules=` 指向一个 Python 世界规则文件，可以定义 `MANIFEST`、`on_epoch`、`on_event`）、速度、种子、回放、感知方式和半径、观察页是否显示地图、相连支援，以及全部经济参数。
- `client.properties` 包括：要连接的服务器、玩家页面端口、昵称，以及启动时载入的规则文件。
- 用 `python -m cellgame server --config server.properties --check-config` 可以只检查设置并打印最终的世界，不会启动服务器。
- 不带 `--config` 直接运行 `python -m server.main` 时不读取任何设置文件，所以测试和脚本的行为不会被本地的设置文件改变。
- 服务器观察页的"准备下一个世界"除了生成启动命令，也会生成可以直接复制的 `server.properties` 内容。


世界规则预设可在 `server.properties` 里选择：`world-preset=go` 启用 `server/worlds/go.py`；也可用 `world-rules=路径.py` 加载自定义规则。行动过滤、行动后效果与生态结算钩子见 `docs/world_rules_zh.md`。旧 `go-rules=on` 会在均衡预设下迁移为 `go`。
