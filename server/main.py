"""Server entry: start the sim process + asyncio network layer + HTTP
spectator page. Usage:
    python -m server.main [--config server.properties] [--port 8765] [--http-port 8080]
                          [--tick-ms 3000] [--world-preset NAME | --world-rules FILE] ...

Settings come from the command line, then the --config file (Minecraft-style
server.properties, created with commented defaults if missing), then defaults.
Without --config only the command line and defaults are used.
"""
import argparse
import asyncio
import multiprocessing as mp
import os
import secrets
import signal
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cellgame.server.net import GameServer
from cellgame.server.settings import PRESETS, SERVER_OPTIONS, TITLE, resolve_server_settings
from cellgame.server.sim_process import sim_loop
from cellgame.server.world_rules import WorldRuleEngine
from cellgame.shared.manifest import ManifestError, PERCEPTION_MODELS, METRICS, build_manifest
from cellgame.shared.properties import PropertiesError, load_properties
from cellgame.shared.world_parameters import DEFAULTS, BOUNDS

HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_FILES = {
    "balanced": os.path.join(HERE, "default_world_rules.py"),
    "lush": os.path.join(HERE, "worlds", "lush.py"),
    "challenging": os.path.join(HERE, "worlds", "challenging.py"),
    "deep-dive": os.path.join(HERE, "worlds", "deep_dive.py"),
    "go": os.path.join(HERE, "worlds", "go.py"),
}


def resolve_manifest(world_rules_path, perception=None, radius=None, metric=None,
                     spectator=None, support=None):
    """The world rule file's MANIFEST, then the host's overrides."""
    declared = WorldRuleEngine(world_rules_path).ns.get("MANIFEST", {})
    if not isinstance(declared, dict):
        raise ManifestError("世界规则文件中的 MANIFEST 必须是字典")
    overrides = {key: (dict(value) if isinstance(value, dict) else value)
                 for key, value in declared.items()}
    section = overrides.get("perception", {})
    if not isinstance(section, dict):
        raise ManifestError("MANIFEST 中的 perception 必须是字典")
    if (radius is not None or metric is not None) and perception is None:
        perception = section.get("model")
        if perception in (None, "legacy"):
            raise ManifestError("sense-radius / perception-metric 需要 radius 或 blanket 感知")
    if perception is not None:
        new = dict(section) if section.get("model") == perception else {}
        new["model"] = perception
        if radius is not None:
            new["external_radius" if perception == "blanket" else "radius"] = radius
        if metric is not None:
            new["metric"] = metric
        overrides["perception"] = {"model": "legacy"} if perception == "legacy" else new
    if spectator is not None:
        overrides["visibility"] = {**overrides.get("visibility", {}), "spectator": spectator}
    if support is not None:
        overrides["combat"] = {**overrides.get("combat", {}), "bonded_support_percent": support}
    return build_manifest(overrides)


def world_rules_path(settings):
    return settings["world_rules"] or PRESET_FILES[settings["world_preset"]]


def manifest_for(settings):
    return resolve_manifest(world_rules_path(settings), settings["perception"], settings["sense_radius"],
                            settings["perception_metric"], settings["spectator_map"],
                            settings["bonded_support_percent"])


def build_parser():
    """Every option defaults to None so that unset options can come from --config."""
    ap = argparse.ArgumentParser(description="CellGame server")
    ap.add_argument("--config", help="server.properties file (created with defaults if missing)")
    ap.add_argument("--check-config", action="store_true",
                    help="validate the settings, print the resulting world and exit")
    ap.add_argument("--port", type=int)
    ap.add_argument("--http-port", type=int)
    ap.add_argument("--host")
    ap.add_argument("--tick-ms", type=int)
    ap.add_argument("--go-rules", choices=("on", "off"), help="围棋式四邻域与无气消亡")
    world_options = ap.add_mutually_exclusive_group()
    world_options.add_argument("--world-rules", help="path to a custom world rules file")
    world_options.add_argument("--world-preset", choices=PRESETS, help="choose a bundled world preset")
    ap.add_argument("--seed", type=int,
                    help="world seed; defaults to 0, or to a random seed when the map is private")
    ap.add_argument("--record", help="save world playback as a new JSONL file")
    ap.add_argument("--perception", choices=PERCEPTION_MODELS, help="perception model; legacy keeps 0.1.x behavior")
    ap.add_argument("--sense-radius", type=int, help="radius (radius model) or external radius (blanket model)")
    ap.add_argument("--perception-metric", choices=METRICS)
    ap.add_argument("--spectator-map", choices=("full", "none"), help="show the map on the spectator page")
    ap.add_argument("--bonded-support-percent", type=int, help="bonded neighbours' energy added to defence (0-100)")
    for key in DEFAULTS:
        low, high = BOUNDS[key]

        def bounded(value, low=low, high=high):
            try:
                number = int(value)
            except ValueError:
                raise argparse.ArgumentTypeError("需要整数")
            if not low <= number <= high:
                raise argparse.ArgumentTypeError(f"需要 {low}–{high} 的整数")
            return number
        ap.add_argument("--" + key.replace("_", "-"), type=bounded)
    return ap


def load_settings(ap, args):
    props, base = {}, Path.cwd()
    if args.config:
        path = Path(args.config).resolve()
        try:
            props, created = load_properties(path, SERVER_OPTIONS, TITLE)
        except (PropertiesError, OSError) as exc:
            ap.error(f"设置文件 {path} 无效：{exc}")
        if created:
            print(f"[server] 已创建默认设置文件 {path}", flush=True)
        else:
            print(f"[server] 使用设置文件 {path}", flush=True)
        base = path.parent
    settings = resolve_server_settings(args, props, base)
    if settings["go_rules"] == "on":
        if settings["world_rules"] or settings["world_preset"] not in ("balanced", "go"):
            ap.error("旧设置 go-rules=on 只能与均衡预设一起使用；请改为 world-preset=go 或自定义规则文件")
        settings["world_preset"] = "go"
        print("[server] go-rules 已迁移到 world-preset=go；请更新设置文件。", flush=True)
    if settings["world_rules"] and not os.path.exists(settings["world_rules"]):
        ap.error(f"找不到世界规则文件 {settings['world_rules']}")
    return settings


def describe(settings, manifest):
    rules = settings["world_rules"] or f"预设 {settings['world_preset']}"
    perception = manifest["perception"]
    return "\n".join([
        f"  世界      {manifest['name']} ({rules})",
        f"  感知      {perception}",
        f"  观察页地图 {manifest['visibility']['spectator']}",
        f"  相连支援   {manifest['combat']['bonded_support_percent']}%",
        f"  速度      每 {settings['tick_ms']} 毫秒一个时刻",
        f"  地址      ws://{settings['host']}:{settings['port']}   观察页 http://localhost:{settings['http_port']}/",
    ])


def main():
    ap = build_parser()
    args = ap.parse_args()
    settings = load_settings(ap, args)
    for key in ("port", "http_port"):
        if not 1 <= settings[key] <= 65535:
            ap.error(f"{key} 需要 1–65535")
    if settings["port"] == settings["http_port"]:
        ap.error("游戏端口和观察页端口不能相同")
    if settings["record"] and os.path.exists(settings["record"]):
        ap.error("--record must name a new file; existing recordings are not overwritten")
    try:
        manifest = manifest_for(settings)
    except ManifestError as exc:
        ap.error(f"世界清单无效: {exc}")
    if settings["seed"] is None:
        # A known seed would let players rebuild a private world's food map.
        private = manifest["visibility"]["spectator"] != "full"
        settings["seed"] = secrets.randbelow(2 ** 31) if private else 0
    if args.check_config:
        print("[server] 设置有效：\n" + describe(settings, manifest), flush=True)
        return
    run_server(settings, manifest)


def run_server(settings, manifest):
    rules_path = world_rules_path(settings)
    # "fork" does not exist on Windows; "spawn" works on both.
    ctx = mp.get_context("spawn" if sys.platform == "win32" else "fork")
    cmd_queue = ctx.Queue()
    event_queue = ctx.Queue()
    world_parameters = {key: settings[key] for key in DEFAULTS}
    config = {
        "world_w": manifest["world"]["width"], "world_h": manifest["world"]["height"],
        "manifest": manifest,
        "tick_ms": settings["tick_ms"],
        # deadline is 2500/3000 of the tick, whatever the tick length is
        "deadline_ms": int(settings["tick_ms"] * 2500 / 3000),
        "epoch_interval": 10,
        "world_rules_path": rules_path,
        "seed": settings["seed"],
        "record_path": settings["record"],
        "world_parameters": world_parameters,
    }
    sim = ctx.Process(target=sim_loop, args=(cmd_queue, event_queue, config), daemon=True)
    sim.start()

    selected = os.path.normcase(os.path.abspath(rules_path))
    preset = next((name for name, path in PRESET_FILES.items()
                   if os.path.normcase(os.path.abspath(path)) == selected), "custom")
    server = GameServer(cmd_queue, event_queue, host=settings["host"],
                        port=settings["port"], http_port=settings["http_port"],
                        sim_proc=sim, world_config={
                            "tick_ms": settings["tick_ms"], "seed": settings["seed"],
                            "world_rule": os.path.basename(rules_path),
                            "world_preset": preset, "world_parameters": world_parameters,
                            "perception": manifest["perception"],
                        }, manifest=manifest)

    def shutdown(*_):
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        asyncio.run(server.run())
    finally:
        cmd_queue.put(("shutdown",))
        sim.join(timeout=2)
        if sim.is_alive():
            sim.terminate()
            sim.join(timeout=2)


if __name__ == "__main__":
    main()
