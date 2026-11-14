"""Record a real tick loop and compare playback with its emitted state."""
import queue
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.replay import iter_replay, load_replay
from server.sim_process import sim_loop
from shared.models import WorldArrays, WORLD_FIELDS, INTENTION_DTYPE, Action
from shared.tick_utils import apply_delta


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "match.jsonl"
        commands, events = queue.Queue(), queue.Queue()
        commands.put(("join", 1, "test"))
        config = {"world_w": 32, "world_h": 32, "seed": 5, "tick_ms": 500,
                  "deadline_ms": 400, "epoch_interval": 10,
                  "world_rules_path": str(ROOT / "server" / "default_world_rules.py"),
                  "record_path": str(path)}
        worker = threading.Thread(target=sim_loop, args=(commands, events, config), daemon=True)
        worker.start()
        collected = []
        destination = None
        while sum(e[0] == "tick" for e in collected) < 2:
            item = events.get(timeout=4)
            collected.append(item)
            if item[0] == "tick" and item[1] == 0:
                commands.put(("profile", 1, "new name", "#ABCDEF"))
            if item[0] == "sense":
                batch = item[2]
                action = None
                if destination is None:
                    for cell, neighbors in zip(batch["cells"], batch["neighborhood"]):
                        x, y = map(int, cell[:2])
                        for dy in (-1, 0, 1):
                            for dx in (-1, 0, 1):
                                tx, ty = x + dx, y + dy
                                if (dx or dy) and 0 <= tx < 32 and 0 <= ty < 32 and neighbors[((dy + 1) * 3 + dx + 1) * 5 + 1] == 0:
                                    action = (x, y, tx, ty, Action.MOVE, 0, 0)
                                    destination = (tx, ty)
                                    break
                            if action:
                                break
                        if action:
                            break
                actions = np.empty(1 if action else 0, dtype=INTENTION_DTYPE)
                if action:
                    actions[0] = action
                commands.put(("intentions", 1, batch["tick"], actions))
        commands.put(("shutdown",))
        worker.join(timeout=5)
        assert not worker.is_alive()
        while not events.empty():
            collected.append(events.get_nowait())
        snapshot = next(e[1] for e in collected if e[0] == "snapshot")
        expected = WorldArrays.from_dict(snapshot, 32, 32)
        expected_tick = -1
        for item in collected:
            if item[0] == "delta":
                delta = item[1]
                apply_delta(expected, delta["changes"])
                for field, value in delta["environment"].items():
                    setattr(expected, field, value.copy())
                expected_tick = delta["tick"]
        actual, tick, players = load_replay(path)
        assert tick == expected_tick
        assert players == {1: "new name"}
        assert destination is not None
        assert actual.owner[destination[1], destination[0]] == 1
        for field in WORLD_FIELDS:
            assert np.array_equal(getattr(actual, field), getattr(expected, field)), field
        frames = list(iter_replay(path))
        assert frames[0][1] == -1
        assert frames[-1][1] == tick
        earlier, early_tick, early_players = load_replay(path, until_tick=0)
        assert early_tick == 0 and early_players == {1: "test"}
        assert int((earlier.owner == 1).sum()) == 20
    print("REPLAY TEST PASSED")


if __name__ == "__main__":
    main()
