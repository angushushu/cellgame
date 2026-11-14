"""Shape presets grow through real, server-arbitrated connected births."""
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cellgame.server.world import WorldState
from cellgame.shared.arbiter import arbitrate
from cellgame.client.executor import to_intentions
from cellgame.species.composer import PRESETS, FORMATIONS, decide_with_config, validate_config

for name in ("spider", "cross"):
    world = WorldState(16, 16, seed=2)
    a = world.arrays
    a.owner[8,8] = a.species[8,8] = 1
    config = validate_config(PRESETS[name])
    config["enabled"] = {key:key == "reproduce" for key in config["enabled"]}
    for t in range(len(FORMATIONS[name]) + 3):
        a.energy[a.owner == 1] = 30
        b = world.gather_sense(1)
        rows = decide_with_config(config,b["cells"],b["neighborhood"],b["env"],b["constraints"],t)
        if not len(rows): break
        actions = to_intentions(rows,b["cells"])
        assert len(actions) == 1 and actions[0]["param"] == 1
        world.apply_intentions(arbitrate(actions, world, world.constraints, player_ids=np.ones(len(actions),dtype=np.int32)))
    positions = {(int(x),int(y)) for y,x in zip(*np.where(a.owner == 1))}
    assert len(positions) == len(FORMATIONS[name]), (name, positions)
    assert any(positions == {(ax+dx,ay+dy) for dx,dy in FORMATIONS[name]}
               for ax,ay in positions for dx0,dy0 in [(0,0)]), (name,positions)
    assert all(a.bonds[y,x] for x,y in positions)
print("FORMATION TEST PASSED")
