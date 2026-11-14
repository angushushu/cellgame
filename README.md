<div align="center">

# 🧬 CellGame

**Build a species. Shape its behavior. See what emerges.**

An experimental multiplayer world for programmable cellular life.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-alpha-E6A23C?style=flat-square)
![World](https://img.shields.io/badge/simulation-2D-38A169?style=flat-square)

English · [简体中文](README_zh.md)

</div>

---

## Explore

Create a species and watch it live alongside others in a shared world. Cells can forage, reproduce, connect, cooperate, and compete. Compose behaviors visually, write Python rules, or connect a local agent. The server validates actions and applies the world’s rules.

- 🧩 **Build:** combine behavior modules or write your own strategies.
- 🦠 **Grow:** connect cells into organisms and coordinate them across scales.
- 🌍 **Experiment:** choose a world preset, perception mode, or custom rules.
- 🔌 **Extend:** build agents and interfaces with the Python API and protocol.

## Quick start

Requires Python **3.10+**. On Windows, run `Start-Server.bat`, then `Start-Client.bat`. Open the [player console](http://localhost:8081/) or [server dashboard](http://localhost:8080/). To join another host, enter its WebSocket address in the player console.

<details>
<summary>Manual setup</summary>

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Run in separate terminals
.\venv\Scripts\python.exe -m server.main
.\venv\Scripts\python.exe -m client.main
```

On macOS/Linux, use `venv/bin/python`. See the [full overview](docs/overview_en.md) for configuration and other entry points.

</details>

## Documentation

| Explore | Guide |
| :--- | :--- |
| Species and local agents | [Programming guide](docs/automaton_zh.md) · [HTTP agent example](examples/local_agent_service.py) |
| Cell, Entity and Unity | [Multiscale interfaces](docs/MULTISCALE.md) |
| Worlds and perception | [World rules](docs/world_rules_zh.md) · [Perception](docs/WORLD_MANIFEST_zh.md) · [Blocks](docs/BLOCKS_zh.md) |
| Integrations | [Core standard](docs/CORE_STANDARD_zh.md) · [Core review](docs/CORE_REVIEW_zh.md) |
| More | [Full overview](docs/overview_en.md) · [Examples](examples/) · [Tests](tests/) |

Most detailed guides are currently in Chinese.

> **Alpha:** The world is a 2D simulation with visual depth effects. Unity is currently a local coordination view, not a persistent server-side group. The prototype has no authentication or encrypted transport; use trusted networks and run only trusted Python rules.

---
<div align="center"><sub>Small rules. Living systems. New possibilities.</sub></div>
