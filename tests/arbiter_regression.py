"""Regression test for the arbiter lexsort crash (found in round 8):
a rule that does NOT pre-check its targets (e.g. REPRODUCE into an
occupied neighbor, MOVE onto an occupied cell) used to crash
arbitrate() with "all keys need to be the same shape" -- the `strength`
array was not filtered by the precondition mask, so the lexsort keys
had mismatched lengths. One sloppy player's rules could kill the sim.
Also covers: zero rows (idle cells in a full (n,7) return) and
intentions from cells the player does not own.
Usage: python tests/arbiter_regression.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.world import WorldState
from shared.arbiter import arbitrate
from shared.models import INTENTION_DTYPE


def mk(rows):
    arr = np.empty(len(rows), dtype=INTENTION_DTYPE)
    for i, r in enumerate(rows):
        arr[i] = tuple(r)
    return arr


def main():
    world = WorldState(seed=1)
    world.spawn_player(1, 1, count=5)
    world.spawn_player(2, 2, count=5)
    # guarantee food on player 1's first cell so the EAT row is valid
    y0, x0 = np.argwhere(world.arrays.owner == 1)[0]
    world.arrays.env_food[y0, x0] = 10
    # find one owned cell per player
    y1, x1 = np.argwhere(world.arrays.owner == 1)[0]
    y2, x2 = np.argwhere(world.arrays.owner == 2)[0]
    # a neighbor of player 1's cell that is occupied by player 1
    # (REPRODUCE/MOVE into it must fail the precondition)
    owned_neighbor = None
    for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        nx, ny = int(x1) + dx, int(y1) + dy
        if 0 <= nx < 256 and 0 <= ny < 256 and world.arrays.owner[ny, nx] == 1:
            owned_neighbor = (nx, ny)
            break
    rows = [
        # valid: eat on own cell (if food) or move to an empty neighbor
        (int(x1), int(y1), int(x1), int(y1), 3, 0, 0),
        # invalid target: REPRODUCE into an occupied cell (must be dropped,
        # must NOT crash the arbiter)
        (int(x1), int(y1),
         int(owned_neighbor[0]) if owned_neighbor else int(x1),
         int(owned_neighbor[1]) if owned_neighbor else int(y1), 2, 0, 0),
        # zero row (idle cell in a full (n,7) return): src (0,0) not owned
        (0, 0, 0, 0, 0, 0, 0),
        # src not owned by the submitting player
        (int(x2), int(y2), int(x2), int(y2), 3, 0, 0),
        # out of bounds
        (int(x1), int(y1), 999, 999, 0, 0, 0),
    ]
    resolved = arbitrate(mk(rows), world, world.constraints, tick=0,
                         player_ids=np.array([1, 1, 1, 1, 1], dtype=np.int32))
    # only the first row can survive (eat on own cell); the rest are
    # dropped by validity/precondition/ownership checks
    assert len(resolved) == 1, f"expected exactly the valid EAT to resolve: {len(resolved)}"
    print(f"arbiter regression: {len(rows)} mixed intentions -> "
          f"{len(resolved)} resolved, no crash")
    # and the same set with a second player's intentions interleaved
    world.arrays.env_food[y2, x2] = 10
    rows2 = rows + [(int(x2), int(y2), int(x2), int(y2), 3, 0, 0)]
    ids2 = np.array([1, 1, 1, 1, 1, 2], dtype=np.int32)
    resolved2 = arbitrate(mk(rows2), world, world.constraints, tick=0,
                          player_ids=ids2)
    assert len(resolved2) == 2, f"expected 2 valid EATs: {len(resolved2)}"
    # (player 2's cell may have no food; make it valid explicitly)

    print(f"two-player mixed intentions -> {len(resolved2)} resolved, no crash")
    print("ARBITER REGRESSION PASSED")


if __name__ == "__main__":
    main()
