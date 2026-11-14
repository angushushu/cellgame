"""Block attacks and separately configured push / destruction energy."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from cellgame.server.world import WorldState
from cellgame.server.kernel import resolve_tick
from cellgame.server.world_rules import apply_world_params
from cellgame.shared.models import Action, INTENTION_DTYPE
from cellgame.shared.manifest import build_manifest
from cellgame.shared.observation import EVENT_RESULT, R_OK, R_CONTESTED, R_INTERRUPTED, R_NO_ENERGY

def make_world():
    w = WorldState(16,16,1)
    w.configure(build_manifest({'world':{'width':16,'height':16},'perception':{'model':'radius','radius':1}}))
    w.arrays.env_material[:] = 0
    apply_world_params(w, {'move_cost':2,'push_cost':4,'block_attack_cost':7,'attack_cost':3})
    return w

def run(w, entries):
    a=np.array([e[:7] for e in entries], dtype=INTENTION_DTYPE)
    return resolve_tick(w, {1:(a,np.array([e[7] for e in entries],dtype=np.int32))})

def row(x,y,tx,ty,act,pid=1): return (x,y,tx,ty,act,0,0,pid)
def result(w,pid): return [int(e['code']) for e in w.events_for(pid) if e['kind']==EVENT_RESULT]

w=make_world(); w.place_cell(1,1,1,20); w.arrays.blocks[1,2]=1
assert run(w,[row(1,1,2,1,Action.ATTACK)])['attack']==1
assert w.arrays.blocks[1,2]==0 and w.arrays.energy[1,1]==13 and result(w,1)==[R_OK]
assert w.last_rule_events[0]['type']=='break_block'
w=make_world();w.place_cell(1,1,1,6);w.arrays.blocks[1,2]=2
assert run(w,[row(1,1,2,1,Action.ATTACK)])['attack']==0
assert w.arrays.energy[1,1]==6 and w.arrays.blocks[1,2]==2 and result(w,1)==[R_NO_ENERGY]
w=make_world();w.place_cell(1,1,1,20);w.arrays.blocks[1,2]=1
run(w,[row(1,1,2,1,Action.MOVE)])
assert w.arrays.energy[1,2]==14 and w.arrays.blocks[1,3]==1
w=make_world();w.place_cell(1,1,1,20);w.place_cell(1,1,2,20);w._set_bond(1,1,1,2,True);w.arrays.blocks[1,2]=1
assert run(w,[row(1,1,2,1,Action.MOVE_GROUP)])['move']==2
assert w.arrays.energy[1,2]==14 and w.arrays.energy[2,2]==18
# Two simultaneous attacks have one winner and only one energy payment.
w=make_world();w.place_cell(1,1,1,20);w.place_cell(2,3,1,20);w.arrays.blocks[1,2]=1
run(w,[row(1,1,2,1,Action.ATTACK),row(3,1,2,1,Action.ATTACK,2)])
assert sorted(result(w,1)+result(w,2))==sorted([R_OK,R_CONTESTED])
assert sorted([w.arrays.energy[1,1],w.arrays.energy[1,3]])==[13,20]
# A block pushed away earlier in the tick cannot be attacked at its old position.
w=make_world();w.place_cell(1,1,1,20);w.place_cell(2,2,2,20);w.arrays.blocks[1,2]=1
run(w,[row(1,1,2,1,Action.MOVE),row(2,2,2,1,Action.ATTACK,2)])
assert w.arrays.blocks[1,3]==1 and w.arrays.owner[1,2]==1
assert result(w,2)==[R_INTERRUPTED] and w.arrays.energy[2,2]==20
print('BLOCK ACTIONS TEST PASSED')
