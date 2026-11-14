"""client.properties: where to connect and how to start the player console."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cellgame.shared.properties import Option, resolve

TITLE = "CellGame 客户端设置（client.properties）"

CLIENT_OPTIONS = (
    Option("server", "server", "str", "ws://localhost:8765",
           "要连接的服务器；局域网里填 ws://服务器的IP:游戏端口", "连接"),
    Option("web-port", "http_port", "int", 8081, "玩家页面的端口：http://localhost:这个端口/", "连接", low=1, high=65535),
    Option("name", "name", "str", "player1", "玩家昵称（也可以在玩家页面里修改）", "玩家"),
    Option("rules", "rules", "path", None, "可选：启动时载入的 Python 物种规则文件（相对于本文件的路径）", "玩家"),
)


def resolve_client_settings(args: Any, props: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Command line > client.properties > defaults."""
    return resolve(args, props, CLIENT_OPTIONS, base_dir)
