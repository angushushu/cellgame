"""Scale adapters and boundaries preserve server action validation."""
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cellgame.server.world import WorldState
from cellgame.species.units import Unity, make_entities
from cellgame.client.rule_loader import load_rule
from cellgame.client.executor import to_intentions
from cellgame.shared.models import Action

world = WorldState(8, 8, seed=1)
a = world.arrays
for x, y in [(2, 2), (3, 2), (4, 2)]:
    a.owner[y, x] = a.species[y, x] = 1
    a.energy[y, x] = 10
# First two cells form an entity. Third cell is adjacent but disconnected.
a.bonds[2, 2] = 1 << 4
a.bonds[2, 3] = 1 << 3
b = world.gather_sense(1)
args = (b['cells'], b['neighborhood'], b['env'], b['constraints'], b['tick'])
entities = make_entities(*args)
assert sorted(len(e.cells) for e in entities) == [1, 2]
first = next(e for e in entities if len(e.cells) == 2)
left = next(c for c in first.cells if c.x == 2)
right = next(c for c in first.cells if c.x == 3)
assert (1, 0) not in left.boundary_directions
assert (1, 0) in right.boundary_directions  # same owner, different entity
unity = Unity(entities)
assert len(unity.cells) == 3 and unity.energy == 30
assert (1, 0) not in unity.boundary_directions(right)
assert len(Unity([first, entities[1] if entities[1] is not first else entities[0]]).cells) == 3
try:
    Unity([first, first.cells[0]])
    raise AssertionError('overlapping members accepted')
except ValueError:
    pass
for name in ('entity_example', 'unity_example'):
    result = load_rule((ROOT / 'species' / (name + '.py')).read_text(encoding='utf8'))(*args)
    assert result.shape[1] == 7
source = 'def decide_entity(e):\n return [c.set_state(7) for c in e.cells]\n'
result = to_intentions(load_rule(source)(*args), b['cells'])
assert len(result) == 3 and all(row['action'] == Action.SET_STATE for row in result)
source = 'def decide_unity(u):\n return [u.cells[0].set_state(len(u.members))]\n'
result = to_intentions(load_rule(source)(*args), b['cells'])
assert len(result) == 1 and result[0]['param'] == 2
print('MULTISCALE TEST PASSED')
