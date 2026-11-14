"""Check tick matching through the real simulation command queues."""
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sim_process import sim_loop
from shared.models import Action, INTENTION_DTYPE


def main():
    commands, events = queue.Queue(), queue.Queue()
    commands.put(("join", 1, "test"))
    config = {"world_w": 32, "world_h": 32, "seed": 0, "tick_ms": 500,
              "deadline_ms": 400, "epoch_interval": 10,
              "world_rules_path": str(ROOT / "server" / "default_world_rules.py")}
    threading.Thread(target=sim_loop, args=(commands, events, config), daemon=True).start()

    def next_sense():
        until = time.monotonic() + 4
        while time.monotonic() < until:
            item = events.get(timeout=2)
            if item[0] == "sense":
                return item[2]
        raise AssertionError("no sense batch")

    first = next_sense()
    action = None
    for row, neighbors in zip(first["cells"], first["neighborhood"]):
        x, y = map(int, row[:2])
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                tx, ty = x + dx, y + dy
                if (dx or dy) and 0 <= tx < 32 and 0 <= ty < 32:
                    if neighbors[((dy + 1) * 3 + dx + 1) * 5 + 1] == 0:
                        action = (x, y, tx, ty, Action.MOVE, 0, 0)
                        break
            if action:
                break
        if action:
            break
    assert action is not None
    arr = np.empty(1, dtype=INTENTION_DTYPE)
    arr[0] = action
    commands.put(("intentions", 1, first["tick"] - 1, arr))
    second = next_sense()
    positions = {tuple(map(int, row[:2])) for row in second["cells"]}
    assert action[:2] in positions and action[2:4] not in positions
    commands.put(("intentions", 1, second["tick"], arr))
    third = next_sense()
    positions = {tuple(map(int, row[:2])) for row in third["cells"]}
    assert action[:2] not in positions and action[2:4] in positions
    print("SIM TICK TEST PASSED")


if __name__ == "__main__":
    main()
