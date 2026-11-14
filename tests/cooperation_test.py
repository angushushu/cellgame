"""Cooperation works through the same arbitration, sense and delta as a live game."""
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client.executor import to_intentions
from client.preview import run_preview
from server.world import WorldState
from shared.arbiter import arbitrate
from shared.models import Action, WorldArrays
from shared.tick_utils import apply_delta
from species.simple import Cell
from species.composer import PRESETS, build_source, validate_config


def perform(world, rows, player_ids=None):
    actions = to_intentions(rows)
    ids = np.ones(len(actions), dtype=np.int32) if player_ids is None else np.asarray(player_ids, dtype=np.int32)
    accepted = arbitrate(actions, world, world.constraints, player_ids=ids)
    world.apply_intentions(accepted)
    return accepted


def main():
    world = WorldState(8, 8, seed=1)
    a = world.arrays
    a.owner[3, 3] = a.species[3, 3] = 1
    a.energy[3, 3] = 20
    a.owner[3, 5] = a.species[3, 5] = 2
    a.energy[3, 5] = 2
    world.delta_since_last_sent()
    assert len(perform(world, [[3,3,4,3,Action.REPRODUCE,0,1]])) == 1
    assert a.owner[3,4] == 1 and a.bonds[3,3] and a.bonds[3,4]
    batch = world.gather_sense(1)
    cell = Cell(batch['cells'][0], batch['neighborhood'][0], batch['env'][0], batch['constraints'])
    assert next(n for n in cell.surrounding() if (n.dx, n.dy) == (1,0)).is_bonded
    assert len(perform(world, [[3,3,3,2,Action.MOVE,0,0]])) == 0
    # Sharing and the recipient's own action can both succeed in one tick.
    a.env_food[3,4] = 4
    previous = int(a.energy[3,3]), int(a.energy[3,4])
    accepted = perform(world, [[3,3,4,3,Action.TRANSFER,0,3], [4,3,4,3,Action.EAT,0,0]])
    assert len(accepted) == 2 and int(a.energy[3,3]) == previous[0]-3
    assert int(a.energy[3,4]) == previous[1]+7
    # Opponents and unconnected cells cannot receive energy or bonds.
    assert len(perform(world, [[4,3,5,3,Action.BOND,0,0]])) == 0
    assert len(perform(world, [[4,3,5,3,Action.TRANSFER,0,3]])) == 0
    assert len(perform(world, [[3,3,4,3,Action.TRANSFER,0,101]])) == 0
    assert len(perform(world, [[3,3,4,3,Action.UNBOND,0,0]])) == 1
    assert not a.bonds[3,3] and not a.bonds[3,4]
    assert len(perform(world, [[3,3,4,3,Action.TRANSFER,0,1]])) == 0
    # A well-formed unconnected transfer has no effect.
    assert int(a.energy[3,4]) == previous[1]+7
    assert len(perform(world, [[3,3,4,3,Action.BOND,0,0]])) == 1
    # Death cleans both ends and propagates the updated bond field.
    assert len(perform(world, [[4,3,4,3,Action.DIE,0,0]])) == 1
    assert not a.bonds[3,3] and not a.bonds[3,4]
    a.owner[4,3] = a.species[4,3] = 1; a.energy[4,3] = 5
    perform(world, [[3,3,3,4,Action.BOND,0,0]])
    mirror = WorldArrays(8,8)
    delta = world.delta_since_last_sent()
    apply_delta(mirror, delta['changes'])
    for field, value in delta['environment'].items(): setattr(mirror, field, value.copy())
    assert np.array_equal(mirror.bonds, a.bonds)
    # Group movement is atomic, preserves links and charges every member.
    moving = WorldState(8, 8, seed=2)
    m = moving.arrays
    m.owner[2,2:4] = m.species[2,2:4] = 1
    m.energy[2,2:4] = [10, 11]
    perform(moving, [[2,2,3,2,Action.BOND,0,0]])
    before_masks = m.bonds[2,2:4].copy()
    assert len(perform(moving, [[2,2,3,2,Action.MOVE_GROUP,0,0]])) == 1
    assert list(m.owner[2,2:5]) == [0,1,1]
    assert list(m.energy[2,3:5]) == [8,9]
    assert np.array_equal(m.bonds[2,3:5], before_masks)
    m.owner[2,5] = m.species[2,5] = 2; m.energy[2,5] = 10
    before = m.owner.copy(), m.energy.copy(), m.bonds.copy()
    perform(moving, [[3,2,4,2,Action.MOVE_GROUP,0,0]])
    assert all(np.array_equal(current, old) for current, old in zip((m.owner,m.energy,m.bonds), before))
    m.owner[2,5] = m.species[2,5] = 0; m.energy[2,5] = 0
    m.energy[2,4] = 1
    before = m.owner.copy(), m.energy.copy(), m.bonds.copy()
    perform(moving, [[3,2,4,2,Action.MOVE_GROUP,0,0]])
    assert all(np.array_equal(current, old) for current, old in zip((m.owner,m.energy,m.bonds), before))
    world.kill_player(1)
    assert not a.bonds.any()
    cfg = validate_config({**PRESETS['balanced'], 'bond_newborn': True, 'share_energy': True, 'group_move': True})
    assert run_preview(build_source(cfg), ticks=20, size=16)['ticks'] == 20
    try:
        validate_config({**cfg, 'release_bonds': True})
    except ValueError:
        pass
    else:
        raise AssertionError('conflicting connection options accepted')
    print('COOPERATION TEST PASSED')

if __name__ == '__main__':
    main()
