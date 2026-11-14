"""Checks server-enforced action boundaries and environment sync."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from shared.models import Action, INTENTION_DTYPE
from shared.arbiter import arbitrate
from server.world import WorldState
from server.net import GameServer
from server.world_rules import apply_world_params, apply_world_events


def intentions(*rows):
    a = np.empty(len(rows), dtype=INTENTION_DTYPE)
    for i, row in enumerate(rows):
        a[i] = row
    return a


def main():
    w = WorldState(8, 8, seed=3)
    a = w.arrays
    a.owner.fill(0); a.species.fill(0); a.energy.fill(0); a.env_food.fill(0)
    a.owner[1, 1] = a.species[1, 1] = 1
    a.energy[1, 1] = 5
    a.owner[1, 2] = a.species[1, 2] = 2
    a.energy[1, 2] = 20
    a.env_food[1, 2] = 10
    def resolve(rows, ids):
        return arbitrate(intentions(*rows), w, w.constraints, player_ids=np.array(ids))
    assert len(resolve([(300, 1, 1, 1, Action.MOVE, 0, 0)], [1])) == 0
    assert len(resolve([(1, 1, 7, 7, Action.MOVE, 0, 0)], [1])) == 0
    assert len(resolve([(1, 1, 1, 1, Action.CHANGE, 0, 2147483647)], [1])) == 0
    assert len(resolve([(1, 1, 2, 1, Action.ATTACK, 30000, 0)], [1])) == 0
    a.energy[1, 1] = 25
    result = resolve([(1, 1, 2, 1, Action.ATTACK, 0, 0),
                      (2, 1, 2, 1, Action.EAT, 0, 0)], [1, 2])
    assert len(result) == 2
    w.apply_intentions(result)
    assert a.owner[1, 2] == 0
    a.energy[1, 1] = 32767
    a.env_food[1, 1] = 10
    eating = resolve([(1, 1, 1, 1, Action.EAT, 0, 0)], [1])
    w.apply_intentions(eating)
    assert a.energy[1, 1] == 32767
    mirror = GameServer(None, None)
    mirror.apply_snapshot(w.snapshot_arrays())
    a.env_food[3, 3] = 42
    mirror.apply_delta_to_mirror(w.delta_since_last_sent())
    assert mirror.world.env_food[3, 3] == 42
    worlds = [WorldState(8, 8, seed=8), WorldState(8, 8, seed=8)]
    for world in worlds:
        apply_world_params(world, {'food_regrow': 30})
    assert np.array_equal(worlds[0].arrays.env_food, worlds[1].arrays.env_food)
    apply_world_events(w, [
        {"type": "add_food", "x": 3, "y": 3, "amount": 4},
        {"type": "add_food", "x": 999, "y": 3, "amount": 4},
        {"type": "add_food", "x": 3, "y": 3, "amount": float("nan")},
        {"type": "set_reproduction", "enabled": False},
    ])
    assert a.env_food[3, 3] == 46
    assert not w.constraints["reproduce_enabled"]
    print('BOUNDARY TEST PASSED')


if __name__ == '__main__':
    main()
