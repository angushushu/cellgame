"""Beginner rule entry, neighborhood helpers, and persistent public state."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.executor import RuleExecutor, to_intentions
from client.preview import run_preview
from client.rule_loader import load_rule
from server.world import WorldState
from shared.arbiter import arbitrate
from shared.models import Action
from species.simple import Cell


SOURCE = """
def decide_cell(cell):
    assert cell.tick is not None and cell.tick >= 0
    return cell.set_state((cell.state + 1) % 3)
"""


def main():
    world = WorldState(8, 8, seed=1)
    world.arrays.owner[0, 0] = world.arrays.species[0, 0] = 1
    world.arrays.energy[0, 0] = 15
    world.arrays.owner[0, 1] = world.arrays.species[0, 1] = 2
    world.arrays.energy[0, 1] = 3
    batch = world.gather_sense(1)
    cell = Cell(batch["cells"][0], batch["neighborhood"][0], batch["env"][0],
                batch["constraints"], batch["tick"])
    neighbors = cell.surrounding()
    assert len(neighbors) == 8 and sum(n.in_bounds for n in neighbors) == 3
    assert any(n.is_enemy and (n.dx, n.dy) == (1, 0) for n in neighbors)
    assert not any(n.is_empty for n in neighbors if not n.in_bounds)
    decide = load_rule(SOURCE)
    arr = to_intentions(decide(batch["cells"], batch["neighborhood"], batch["env"],
                               batch["constraints"], batch["tick"]), batch["cells"])
    assert int(arr[0]["action"]) == Action.SET_STATE
    world.delta_since_last_sent()
    resolved = arbitrate(arr, world, world.constraints, player_ids=np.array([1]))
    world.apply_intentions(resolved)
    assert world.arrays.state[0, 0] == 1
    changes = world.delta_since_last_sent()["changes"]
    assert len(changes) == 1 and int(changes[0, 7]) & 8
    batch = world.gather_sense(1)
    assert batch["cells"][0, 3] == 1
    assert int(decide(batch["cells"], batch["neighborhood"], batch["env"],
                      batch["constraints"], 1)[0, 6]) == 2
    executor = RuleExecutor()
    try:
        executor.load(SOURCE)
        assert int(executor._call(batch)[0]["param"]) == 2
    finally:
        executor.close()
    move = to_intentions([[0, 0, 0, 1, Action.MOVE, 0, 0]], batch["cells"])
    world.apply_intentions(arbitrate(move, world, world.constraints, player_ids=np.array([1])))
    assert world.arrays.owner[1, 0] == 1 and world.arrays.state[1, 0] == 1
    batch = world.gather_sense(1)
    birth = to_intentions([[0, 1, 1, 1, Action.REPRODUCE, 0, 0]], batch["cells"])
    world.apply_intentions(arbitrate(birth, world, world.constraints, player_ids=np.array([1])))
    assert world.arrays.owner[1, 1] == 1 and world.arrays.state[1, 1] == 0
    assert run_preview(SOURCE, ticks=5, size=16)["ticks"] == 5
    print("SINGLE CELL TEST PASSED")


if __name__ == "__main__":
    main()
