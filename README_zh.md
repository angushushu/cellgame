<div align="center">

# 🧬 CellGame

**创造物种，定义行为，观察生命的涌现。**

一个可编程的多人细胞生命实验世界。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-alpha-E6A23C?style=flat-square)
![World](https://img.shields.io/badge/simulation-2D-38A169?style=flat-square)

[English](README.md) · 简体中文

</div>

---

## 探索生命世界

创造你的物种，让它与其他玩家共享同一个世界。细胞可以觅食、繁殖、连接、合作与竞争。你可以通过界面组合行为、编写 Python 规则，或接入本地智能体；所有行动由服务端按照世界规则裁决。

- 🧩 **构建策略：**组合行为模块，或编写自己的行为代码。
- 🦠 **生长与协作：**将细胞连接成有机体，在不同尺度上协调行动。
- 🌍 **创造世界：**选择世界预设、感知模式，或自定义世界规则。
- 🔌 **自由扩展：**通过 Python 接口和协议开发智能体或其他界面。

## 快速开始

需要 **Python 3.10 或更高版本**。Windows 用户依次运行 `Start-Server.bat` 和 `Start-Client.bat`，然后打开[玩家控制台](http://localhost:8081/)或[服务端控制台](http://localhost:8080/)。加入其他服务器时，在玩家控制台输入其 WebSocket 地址。

<details>
<summary>手动启动</summary>

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 在两个终端分别运行
.\venv\Scripts\python.exe -m server.main
.\venv\Scripts\python.exe -m client.main
```

macOS/Linux 使用 `venv/bin/python`。更多配置和启动方式见[完整说明](docs/overview_en.md)。

</details>

## 文档

| 内容 | 指南 |
| :--- | :--- |
| 物种与本地智能体 | [物种编程指南](docs/automaton_zh.md) · [HTTP 智能体示例](examples/local_agent_service.py) |
| Cell、Entity 与 Unity | [多尺度接口](docs/MULTISCALE.md) |
| 世界与感知 | [世界规则](docs/world_rules_zh.md) · [感知与世界清单](docs/WORLD_MANIFEST_zh.md) · [可移动方块](docs/BLOCKS_zh.md) |
| 核心与协议 | [核心标准](docs/CORE_STANDARD_zh.md) · [核心评估](docs/CORE_REVIEW_zh.md) |
| 更多 | [完整说明（英文）](docs/overview_en.md) · [示例](examples/) · [测试](tests/) |

> **Alpha 阶段：**世界采用二维模拟，立体效果是视觉呈现。Unity 目前是客户端本地协调视图，不是服务端持久群体。当前版本没有身份验证和传输加密，请在可信网络中使用，并只运行可信的 Python 规则。

---
<div align="center"><sub>简单规则，生命系统，无限可能。</sub></div>
