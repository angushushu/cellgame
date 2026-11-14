"""Read a recorded world playback without executing player or world code."""
import argparse
import json
import numpy as np

from cellgame.shared.models import WorldArrays
from cellgame.shared.protocol import decode_msg
from cellgame.shared.tick_utils import apply_delta


def iter_replay(path):
    """Yield independent snapshots at the start and after each saved tick."""
    world = None
    tick = -1
    players = {}
    header = None
    with open(path, encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            kind, payload = decode_msg(line)
            if line_number == 1:
                if kind != "replay_header" or payload.get("version") != 1:
                    raise ValueError("unsupported replay header")
                header = payload
                continue
            data = payload.get("data", [])
            if kind == "snapshot":
                if world is not None:
                    raise ValueError("duplicate replay snapshot")
                arrays = data[0]
                world = WorldArrays.from_dict(arrays, header["world_w"], header["world_h"])
                yield world.copy(), tick, dict(players)
            elif kind == "delta":
                if world is None:
                    raise ValueError("world delta before snapshot")
                delta = data[0]
                if delta["tick"] <= tick:
                    raise ValueError("replay ticks are out of order")
                apply_delta(world, delta["changes"])
                for field, value in delta.get("environment", {}).items():
                    if field not in ("env_food", "env_temp", "blocks", "bonds", "organism"):
                        raise ValueError("unexpected environment field")
                    setattr(world, field, value.copy())
                tick = delta["tick"]
                yield world.copy(), tick, dict(players)
            elif kind == "player_joined":
                players[int(data[0])] = data[1]
            elif kind == "player_updated":
                if int(data[0]) in players:
                    players[int(data[0])] = data[1]
            elif kind == "player_died":
                players.pop(int(data[0]), None)
    if header is None or world is None:
        raise ValueError("recording has no header or snapshot")


def load_replay(path, until_tick=None):
    frame = None
    for frame in iter_replay(path):
        if until_tick is not None and frame[1] >= until_tick:
            break
    if frame is None:
        raise ValueError("recording has no frame")
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording")
    parser.add_argument("--tick", type=int, help="inspect the state at this tick")
    args = parser.parse_args()
    world, tick, players = load_replay(args.recording, args.tick)
    owners, counts = np.unique(world.owner, return_counts=True)
    print(json.dumps({
        "tick": tick, "players": players,
        "cells": {int(owner): int(count) for owner, count in zip(owners, counts) if owner},
        "total_food": float(world.env_food.sum()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
