"""Server-authoritative materials and optional four-neighbor liberties."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cellgame.server.world import WorldState
from cellgame.server.world_rules import WorldRuleEngine
from cellgame.server.sim_process import resolve_tick
from cellgame.shared.models import Action, INTENTION_DTYPE
from cellgame.shared.arbiter import arbitrate
from cellgame.server.perception import gather_observation
from cellgame.shared.manifest import build_manifest
from cellgame.shared.observation import observation_to_world

def row(x,y,tx,ty,act,param=0):
    return np.array([(x,y,tx,ty,act,0,param)],dtype=INTENTION_DTYPE)

base=WorldRuleEngine(str(Path(__file__).resolve().parents[1] / "server/default_world_rules.py"))
go=WorldRuleEngine(str(Path(__file__).resolve().parents[1] / "server/worlds/go.py"))

def decide(world, a, owner=1):
    return arbitrate(a,world,world.constraints,player_ids=np.array([owner]))

def run(world, rules, action=None):
    pending = {} if action is None else {1:(action,np.ones(len(action),dtype=np.int32))}
    return resolve_tick(world,pending,rules)

w=WorldState(8,8,seed=8); w.arrays.env_material[:]=0
w.place_cell(1,3,3,energy=20); w.arrays.env_food[3,3]=10;w.arrays.env_material[3,3]=1
run(w,base,row(3,3,3,3,Action.EAT))
assert w.arrays.energy[3,3]==27 and w.arrays.env_food[3,3]==5
w.arrays.env_material[3,3]=2;run(w,base);assert w.arrays.energy[3,3]==22
w.arrays.env_material[3,3]=3;run(w,base);assert w.arrays.energy[3,3]==20
w.place_cell(1,4,4,energy=20)
assert run(w,go,row(3,3,4,4,Action.BOND))["move"]==0 and not w.arrays.bonds[3,3]
assert run(w,go,row(3,3,2,2,Action.REPRODUCE,1))["reproduce"]==0
assert run(w,go,row(3,3,2,2,Action.REPRODUCE,0))["reproduce"]==1
w.arrays.env_material[:]=0
# An unbonded orthogonal friendly pair shares liberties; then the group has none.
w=WorldState(5,5,seed=3);w.arrays.env_material[:]=0
for x,y,owner in [(2,2,1),(3,2,1),(1,2,2),(2,1,2),(2,3,2),(4,2,2),(3,1,2)]:w.place_cell(owner,x,y,20)
run(w,go);assert w.arrays.owner[2,2]==1 and w.arrays.owner[2,3]==1
w.place_cell(2,3,3,20);run(w,go);assert w.arrays.owner[2,2]==0 and w.arrays.owner[2,3]==0
# Optional mode off leaves the isolated cell alive despite no liberties.
w=WorldState(3,3,seed=3);w.arrays.env_material[:]=0
for y in range(3):
 for x in range(3):w.place_cell(1 if (x,y)==(1,1) else 2,x,y,20)
run(w,base);assert w.arrays.owner[1,1]==1
manifest=build_manifest({"world":{"width":16,"height":16},"perception":{"model":"radius","radius":1}})
w=WorldState(16,16,seed=1);w.configure(manifest);w.place_cell(1,2,2,20);w.arrays.env_material[:]=2
obs=gather_observation(w,1,manifest);assert len(obs['materials'])==len(obs['tiles'])
view=observation_to_world(obs,1,16,16);assert np.count_nonzero(view.env_material)<=9
print("MATERIALS AND GO TEST PASSED")
