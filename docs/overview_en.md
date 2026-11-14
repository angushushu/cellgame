<div align="center">

# 🧬 CellGame

**Build a species. Shape its behavior. See what emerges.**

A multiplayer cellular world where programmable organisms live, explore, and interact.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-alpha-E6A23C?style=flat-square)
![World](https://img.shields.io/badge/world-2D%20simulation-38A169?style=flat-square)
![Core](https://img.shields.io/badge/core%20contract-1.0.0--rc.1-2C7A7B?style=flat-square)

[Getting Started](#-getting-started) · [Create a Species](#-create-a-species) · [World Rules](#-world-rules) · [Core & Protocol](#-core--protocol) · [Documentation](#-documentation)

</div>

---

## 🌱 What is CellGame?

CellGame is an experimental multiplayer simulation about building life from simple parts. Create a species, choose how its cells act, and let it share a changing world with other players. Cells can gather food, move, reproduce, connect, cooperate, or compete. Connected cells can form larger organisms; local strategies can coordinate them at different scales.

The **server owns the world** and validates every proposed action. Player rules run locally, so you can experiment with visual behavior modules, Python code, or an external agent without uploading your source code to the server.

> **Project status:** CellGame is an alpha prototype. The simulation is two-dimensional; the apparent depth, breathing, and particles are visual effects. Some interfaces and mechanics remain experimental.

## ✨ Explore the world

| | What you can do |
| :--- | :--- |
| 🧩 **Compose a species** | Combine and reorder behavior modules, preview a strategy, or edit its generated Python code. |
| 🦠 **Grow an organism** | Connect cells, share energy, move together, and experiment with different body shapes. |
| 🕸️ **Control multiple scales** | Write rules for individual cells, connected entities, or a local unity view of your organisms. |
| 🌍 **Host a world** | Choose a world preset, adjust its parameters, or write custom server-side rules in Python. |
| 👁️ **Experiment with perception** | Try full, radius-limited, or boundary-based observation depending on the world. |
| 🤖 **Connect an agent** | Use Python, a local HTTP model adapter, or a process communicating through JSON lines. |
| 🔌 **Build your own interface** | Use the headless Python API or the WebSocket protocol independently of the bundled GUI. |

## 🚀 Getting started

### Requirements

- Python **3.10 or newer**
- A browser for the server dashboard and player console
- Dependencies listed in [`requirements.txt`](../requirements.txt)

### Windows: start from source

From the project directory, double-click **`Start-Server.bat`** and then **`Start-Client.bat`**. The startup scripts use `server.properties` and `client.properties` respectively. The scripts under `server/` and `client/` can also start the applications from source.

Open:

- **Player console:** [localhost:8081](http://localhost:8081/)
- **Server dashboard:** [localhost:8080](http://localhost:8080/)

On first use, the startup scripts may create a virtual environment and install dependencies. To join another host, enter its WebSocket address in the player console.

### Start manually

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Terminal 1: server
.\venv\Scripts\python.exe -m server.main

# Terminal 2: player client
.\venv\Scripts\python.exe -m client.main
```

On macOS or Linux, use `venv/bin/python` instead. For an installed local package, the entry points are `cellgame-server` and `cellgame-client`, or `python -m cellgame server` and `python -m cellgame client`. **PyPI installation is planned; do not assume the package is published.**

> **Network and code safety:** The prototype does not provide authentication or encrypted transport. Use it on a trusted network; bind the server to `127.0.0.1` for local-only play. Player and world rules are Python code and are not security sandboxes—run only code you trust.

## 🧩 Create a species

Start with the player console’s behavior composer: choose a template, toggle modules, change their order and thresholds, and preview the result. The advanced panel lets you edit the generated code or supply your own rules.

A minimal single-cell rule can look like this:

```python
def decide_cell(cell):
    if cell.food_here > 0:
        return cell.eat()

    empty = cell.empty_neighbors()
    if empty and cell.energy >= 13:
        return cell.reproduce(empty[0])

    return cell.wait()
```

Rules **propose** actions; the server checks whether they are legal and can afford their costs. World settings may impose a higher reproduction threshold than the one in your rule.

### From cells to groups

| Scale | Entry point | Scope |
| :--- | :--- | :--- |
| **Cell** | `decide_cell(cell)` | One cell’s observations and action. |
| **Entity** | `decide_entity(entity)` | A connected organism and its cells. |
| **Unity** | `decide_unity(unity)` | A local view coordinating the current player’s observed organisms. |

Unity is currently a **client-side view**, not a persistent server-side group identity. See [multiscale control](../docs/MULTISCALE.md), the [species guide](../docs/automaton_zh.md), and the examples in [`species/`](../species/).

### Bring your own model

The advanced panel can connect to a local HTTP adapter such as `http://127.0.0.1:9000/decide`. The adapter receives observations and returns actions for the same tick. [`examples/local_agent_service.py`](../examples/local_agent_service.py) provides a working starting point: replace its hand-written policy with your own inference code. A general chat API needs an adapter to translate observations and actions.

For an independent process, use the headless client’s `--agent` option and exchange one JSON line per tick over standard input and output. See [`species/stdio_example.py`](../species/stdio_example.py) and [the core standard](../docs/CORE_STANDARD_zh.md).

## 🌍 World rules

Hosts can select a preset in `server.properties` or start the server with command-line options. For example:

```properties
world-preset=go
```

The `go` preset uses orthogonal connections and a simultaneous, tick-based liberty rule; it is **not** a complete implementation of standard Go. Other presets include `balanced`, `lush`, `challenging`, and `deep-dive`. Custom Python rules can be selected with `world-rules=path/to/rules.py` or the `--world-rules` option. Command-line options take precedence over configuration files when using the packaged entry point.

The world can include biomes, food, berries, lava, and spikes. Their effects and available rule hooks are described in the [world rules guide](../docs/world_rules_zh.md). The server validates and applies the results of rule hooks; some underlying mechanics remain part of the engine.

### Perception and privacy

The default legacy mode provides broad world information. Radius and deep-dive modes restrict what player observations contain; their exact behavior and limits depend on the world. The server host may access more information, and local player programs are not isolated from the machine on which they run. See [world manifest and perception](../docs/WORLD_MANIFEST_zh.md) before using the game for controlled experiments.

## 🔌 Core & protocol

CellGame separates the world engine, the player-side rule interface, and the network protocol from the bundled web interface. The candidate **`1.0.0-rc.1` core contract** describes observation, action, identity, version negotiation, and encoding. The GUI’s HTTP endpoints are implementation details, not the stable public protocol.

```python
import cellgame.api
```

After installing the project, print the machine-readable registry or schema with:

```bash
python -m cellgame contract
python -m cellgame contract --schema
```

Read [Core Standard](../docs/CORE_STANDARD_zh.md) for integration details and [Core Review](../docs/CORE_REVIEW_zh.md) for current limits and future work.

## 🗂️ Project layout

| Path | Purpose |
| :--- | :--- |
| [`cellgame/`](../cellgame/) | Public package entry points and API |
| [`server/`](../server/) | World simulation, networking, rules, and dashboard |
| [`client/`](../client/) | Player console, local rules, and agent adapters |
| [`shared/`](../shared/) | Protocol, data models, contracts, and shared logic |
| [`species/`](../species/) | Built-in species and programmable rule examples |
| [`examples/`](../examples/) | Headless protocol and local HTTP agent examples |
| [`tests/`](../tests/) | Simulation, protocol, interface, and integration checks |
| [`docs/`](../docs/) | Detailed guides and interface specifications |

## 🧪 Testing and replay

From the project directory, after installing dependencies:

```powershell
.\venv\Scripts\python.exe tests\smoke_test.py
.\venv\Scripts\python.exe tests\contract_test.py
.\venv\Scripts\python.exe tests\world_hooks_test.py
.\venv\Scripts\python.exe tests\e2e_test.py
```

More focused checks live in [`tests/`](../tests/). Some interface checks require Node.js; the game itself does not.

To record a game and inspect a saved tick:

```powershell
.\venv\Scripts\python.exe -m server.main --record match.jsonl
.\venv\Scripts\python.exe -m server.replay match.jsonl --tick 10
```

Recordings reconstruct saved world state; they do not re-execute player programs. The current replay command is text-based.

## 📚 Documentation

Most detailed guides are currently in Chinese.

- [Core interface standard](../docs/CORE_STANDARD_zh.md) and [review](../docs/CORE_REVIEW_zh.md)
- [World rules and hooks](../docs/world_rules_zh.md)
- [Cell, entity, and unity interfaces](../docs/MULTISCALE.md)
- [Species programming](../docs/automaton_zh.md)
- [World manifest and perception](../docs/WORLD_MANIFEST_zh.md)
- [Publishing notes](../docs/publishing_zh.md)

## 🧭 Current limitations

- The game is an alpha prototype; mechanics and balance can change.
- Unity is a local coordination view; persistent groups and cross-player membership are not implemented.
- Observation restrictions do not prove that a local program uses only the supplied information.
- Players’ cells are removed on disconnect; persistent world saves and reconnect grace are not implemented.
- World and player Python rules execute trusted code; they are not isolated security sandboxes.
- The world is 2D, and replay is currently a state playback without a graphical viewer.

---

<div align="center">
  <sub>Small rules. Living systems. New possibilities.</sub>
</div>
