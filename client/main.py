"""Client entry.

Console mode (default): local HTTP console on --http-port (default
8081) + game client in the asyncio loop. Open
http://localhost:8081/ in a browser.

Headless mode (--headless): no HTTP server; just connect with the
given rules file and play. Used by the end-to-end test.

    python -m client.main [--config client.properties] [--server ws://localhost:8765]
                         [--name player1] [--rules species/grazer.py]
                         [--http-port 8081] [--headless]

Settings come from the command line, then the --config file (client.properties,
created with commented defaults if missing), then defaults.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cellgame.client.executor import RuleExecutor
from cellgame.client.http_server import ConsoleServer
from cellgame.client.net import ClientState, GameClient
from cellgame.client.settings import CLIENT_OPTIONS, TITLE, resolve_client_settings
from cellgame.shared.properties import PropertiesError, load_properties
from pathlib import Path


def apply_config(ap, args):
    """Fill unset options from --config, then from defaults (in place)."""
    props, base = {}, Path.cwd()
    if args.config:
        path = Path(args.config).resolve()
        try:
            props, created = load_properties(path, CLIENT_OPTIONS, TITLE)
        except (PropertiesError, OSError) as exc:
            ap.error(f"设置文件 {path} 无效：{exc}")
        print(f"[client] {'已创建默认设置文件' if created else '使用设置文件'} {path}", flush=True)
        base = path.parent
    for key, value in resolve_client_settings(args, props, base).items():
        setattr(args, key, value)
    if not 1 <= args.http_port <= 65535:
        ap.error("web-port 需要 1–65535")


async def headless_main(args):
    state = ClientState()
    if args.agent:
        from cellgame.client.external_agent import ExternalAgentExecutor
        executor = ExternalAgentExecutor(args.agent)
    else:
        executor = RuleExecutor()
    if args.rules and not args.agent:
        with open(args.rules, encoding="utf-8") as f:
            source = f.read()
        executor.load(source)
        state.rules_source = source
        state.custom_rules_source = source
        state.rules_status = "规则已加载"
        state.controller_type = "自定义代码"
    elif args.agent:
        state.controller_type = "外部程序"
    client = GameClient(state, executor)
    try:
        await client.connect_and_run(args.server, args.name)
    finally:
        executor.close()


def main():
    ap = argparse.ArgumentParser(description="CellGame client")
    ap.add_argument("--config", help="client.properties file (created with defaults if missing)")
    ap.add_argument("--server")
    ap.add_argument("--name")
    ap.add_argument("--rules")
    ap.add_argument("--http-port", type=int)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--agent", nargs=argparse.REMAINDER,
                    help="local JSON-lines agent command (must be the last option; headless only)")
    args = ap.parse_args()
    apply_config(ap, args)
    if args.rules and not os.path.exists(args.rules):
        ap.error(f"找不到规则文件 {args.rules}")

    if args.agent is not None and not args.headless:
        ap.error("--agent requires --headless")
    if args.agent is not None and not args.agent:
        ap.error("--agent requires a command")

    if args.headless:
        asyncio.run(headless_main(args))
        return

    state = ClientState()
    executor = RuleExecutor()
    client = GameClient(state, executor)
    # Start with the same balanced configuration shown in the beginner UI.
    # --rules overrides this with the player's own local code.
    if args.rules and os.path.exists(args.rules):
        with open(args.rules, encoding="utf-8") as f:
            source = f.read()
        executor.load(source)
        state.rules_source = source
        state.custom_rules_source = source
        state.rules_status = "自定义规则已启用"
        state.controller_type = "自定义代码"
    elif not args.rules:
        from cellgame.species.composer import DEFAULT, build_source
        source = build_source(DEFAULT)
        executor.load(source)
        state.rules_source = source
        state.rules_status = "均衡物种已启用"
        state.controller_type = "组合模式"
        state.composition_config = DEFAULT
        example_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "species", "beginner.py")
        with open(example_path, encoding="utf-8") as f:
            state.custom_rules_source = f.read()

    async def runner():
        state.loop = asyncio.get_running_loop()
        # auto-connect if a server URL was given explicitly
        if args.server:
            task = asyncio.create_task(client.connect_and_run(args.server, args.name))
            task.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)
        await asyncio.Future()

    console = ConsoleServer(state, executor, client, port=args.http_port)
    console.start()
    try:
        asyncio.run(runner())
    finally:
        executor.close()


if __name__ == "__main__":
    main()
