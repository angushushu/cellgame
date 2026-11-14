"""Minimal GUI-free v2 agent, demonstrating the public transport contract.

Start a radius world, then run:
  python -m cellgame.examples.protocol_agent --server ws://127.0.0.1:8765

Only eats known food. Replace choose() to implement another policy or frontend.
It intentionally supports observation v2, not legacy full-map worlds.
"""
import argparse
import asyncio

from websockets.asyncio.client import connect
from cellgame.api import Action, decode_msg, encode_msg, validate_observation


def choose(observation):
    tiles = {(int(t["x"]), int(t["y"])): t for t in observation["tiles"]}
    actions = []
    for c in observation["cells"]:
        tile = tiles.get((int(c["x"]), int(c["y"])))
        if tile is not None and tile["env_visible"] and tile["food"] > 0:
            actions.append([int(c["cell_id"]), int(Action.EAT), 0, 0, 0])
    return actions


async def play(url, name, ticks=None):
    async with connect(url, max_size=32 * 1024 * 1024) as ws:
        await ws.send(encode_msg("hello", protocol_version=2, protocol_versions=[2], player_name=name))
        count = 0
        manifest = None
        async for raw in ws:
            kind, payload = decode_msg(raw)
            if kind == "welcome":
                if payload.get("intention_format", 2) != 2 or payload.get("manifest", {}).get("perception", {}).get("model") == "legacy":
                    raise ValueError("This example needs a radius or blanket world")
                manifest = payload["manifest"]
            elif kind == "observation":
                if manifest is None:
                    raise ValueError("Observation arrived before the world manifest")
                validate_observation(payload, manifest)
                await ws.send(encode_msg("intentions", tick=payload["tick"], format=2, data=choose(payload)))
                count += 1
                if ticks is not None and count >= ticks:
                    return
            elif kind == "error":
                raise ValueError(payload.get("message", "server error"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="ws://127.0.0.1:8765")
    parser.add_argument("--name", default="protocol-agent")
    parser.add_argument("--ticks", type=int, default=None, help="exit after this many observations")
    args = parser.parse_args()
    asyncio.run(play(args.server, args.name, args.ticks))


if __name__ == "__main__":
    main()
