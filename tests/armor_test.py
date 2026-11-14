"""Defense and movement cost use pre-tick authoritative cell types."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.arbiter import arbitrate
from shared.models import Action, INTENTION_DTYPE
from server.world import WorldState


def decide(world, rows, pids):
    intentions = np.empty(len(rows), dtype=INTENTION_DTYPE)
    for i, row in enumerate(rows):
        intentions[i] = row
    return arbitrate(intentions, world, world.constraints, player_ids=np.array(pids))


def main():
    w = WorldState(8, 8)
    a = w.arrays
    a.owner[2, 2], a.species[2, 2], a.energy[2, 2] = 1, 1, 12
    a.owner[2, 3], a.species[2, 3], a.energy[2, 3] = 2, 2, 10
    a.cell_type[2, 3] = 1
    attack = (2, 2, 3, 2, Action.ATTACK, 30000, 0)
    assert len(decide(w, [attack], [1])) == 0
    a.energy[2, 2] = 14
    resolved = decide(w, [attack], [1])
    assert len(resolved) == 1
    w.apply_intentions(resolved)
    assert a.owner[2, 3] == 0
    a.cell_type[2, 2] = 1
    a.energy[2, 2] = 2
    move = (2, 2, 2, 3, Action.MOVE, 0, 0)
    assert len(decide(w, [move], [1])) == 0
    a.energy[2, 2] = 4
    w.apply_intentions(decide(w, [move], [1]))
    assert a.owner[3, 2] == 1 and a.energy[3, 2] == 1
    print("ARMOR TEST PASSED")


if __name__ == "__main__":
    main()
