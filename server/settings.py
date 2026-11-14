"""server.properties: the options a host can set without touching code.

Simple worlds are configured here; anything beyond these options goes in a
Python world-rules file (``world-rules=``) that defines MANIFEST, on_epoch
and on_event (docs/world_rules_zh.md, docs/WORLD_MANIFEST_zh.md).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cellgame.shared.manifest import METRICS, PERCEPTION_MODELS
from cellgame.shared.properties import Option, resolve
from cellgame.shared.world_parameters import BOUNDS, DEFAULTS

PRESETS = ("balanced", "lush", "challenging", "deep-dive", "go")
TITLE = "CellGame 服务器设置（server.properties）"

_ECONOMY_HELP = {
    "move_cost": "移动一格消耗的能量", "attack_cost": "攻击消耗的能量",
    "reproduce_cost": "繁殖时父细胞消耗的能量", "change_cost": "改变细胞类型（如变装甲）消耗的能量",
    "reproduce_min_energy": "繁殖所需的最低能量（物种设置无法低于它）", "child_energy": "新生细胞的初始能量",
    "eat_gain": "每次进食最多获得的能量", "attack_reward_percent": "击败敌方细胞后获得其能量的百分比",
    "armor_defense_bonus": "装甲细胞的额外防御", "armor_move_surcharge": "装甲细胞移动的额外消耗",
}

SERVER_OPTIONS = (
    Option("server-ip", "host", "str", "0.0.0.0", "监听地址；0.0.0.0 允许局域网玩家加入，127.0.0.1 只允许本机", "网络"),
    Option("server-port", "port", "int", 8765, "游戏端口，玩家连接 ws://服务器IP:这个端口", "网络", low=1, high=65535),
    Option("web-port", "http_port", "int", 8080, "服务器观察页面的端口：http://localhost:这个端口/", "网络", low=1, high=65535),
    Option("world-preset", "world_preset", "choice", "balanced",
           "内置世界：balanced 均衡 / lush 丰饶 / challenging 挑战 / deep-dive 深潜 / go 围棋生态",
           "世界", choices=PRESETS),
    Option("go-rules", "go_rules", "choice", "off", "旧版兼容：on 将均衡世界迁移到 go 预设；推荐使用 world-preset=go", "世界", choices=("on", "off")),
    Option("world-rules", "world_rules", "path", None,
           "可选：Python 世界规则文件（相对于本文件的路径）；填写后取代 world-preset。"
           "文件可定义 MANIFEST、on_epoch、on_event", "世界"),
    Option("tick-ms", "tick_ms", "int", 3000, "每个时刻的毫秒数，越小世界越快", "世界", low=100, high=600000),
    Option("seed", "seed", "int", None, "世界种子；留空时公开地图的世界为 0，地图不公开的世界随机", "世界",
           low=0, high=4294967295),
    Option("record", "record", "path", None, "可选：把世界回放保存到这个新文件（不会覆盖已有文件）", "世界"),
    Option("perception", "perception", "choice", None,
           "感知方式，留空则用世界本身的设置：legacy 全图 / radius 半径 / blanket 毯感知", "感知与可见性",
           choices=PERCEPTION_MODELS),
    Option("sense-radius", "sense_radius", "int", None, "radius 的感知半径，或 blanket 边界细胞的外部感知半径",
           "感知与可见性", low=1, high=8),
    Option("perception-metric", "perception_metric", "choice", None, "感知范围形状：chebyshev 方形 / euclidean 圆形",
           "感知与可见性", choices=METRICS),
    Option("spectator-map", "spectator_map", "choice", None, "观察页面是否显示地图：full 显示 / none 不显示（防止看全图作弊）",
           "感知与可见性", choices=("full", "none")),
    Option("bonded-support-percent", "bonded_support_percent", "int", None,
           "相连细胞的整体防御：防御额外加上相连邻居能量的百分比（0 关闭）", "战斗", low=0, high=100),
    *(Option(key.replace("_", "-"), key, "int", DEFAULTS[key], _ECONOMY_HELP[key], "经济参数",
             low=BOUNDS[key][0], high=BOUNDS[key][1]) for key in DEFAULTS),
)


def resolve_server_settings(args: Any, props: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Command line > server.properties > defaults.

    A world chosen on the command line (--world-preset or --world-rules) wins
    over the file's choice; in the file, world-rules wins over world-preset.
    """
    settings = resolve(args, props, SERVER_OPTIONS, base_dir, skip=("world_rules", "world_preset"))
    cli_rules, cli_preset = getattr(args, "world_rules", None), getattr(args, "world_preset", None)
    if cli_rules is not None or cli_preset is not None:
        settings["world_rules"], settings["world_preset"] = cli_rules, cli_preset or "balanced"
    else:
        file_rules = props.get("world-rules")
        settings["world_rules"] = str((Path(base_dir) / file_rules).resolve()) if file_rules else None
        settings["world_preset"] = props.get("world-preset", "balanced")
    return settings
