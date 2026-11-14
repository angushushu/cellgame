"""Authoritative block pushing, reactions, observation and world replication."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from cellgame.server.world import WorldState
from cellgame.server.kernel import resolve_tick
from cellgame.server.perception import gather_observation
from cellgame.shared.models import Action, INTENTION_DTYPE, WorldArrays
from cellgame.shared.manifest import build_manifest
from cellgame.shared.observation import expand_observation, observation_to_world, to_legacy_batch
from cellgame.shared.protocol import encode_msg, decode_msg
from cellgame.species.units import make_entities


def action(x,y,tx,ty,kind=Action.MOVE):
    return np.array([(x,y,tx,ty,kind,0,0)],dtype=INTENTION_DTYPE)

def run(w, rows, pid=1):
    return resolve_tick(w, {pid:(rows,np.full(len(rows),pid,dtype=np.int32))})

w=WorldState(8,8,0); w.arrays.env_material[:]=0
w.place_cell(1,1,2,20); w.arrays.blocks[2,2:4]=[1,3]
assert run(w,action(1,2,2,2))['move']==1
assert w.arrays.owner[2,2]==1 and w.arrays.blocks[2,3:5].tolist()==[1,3]
assert w.arrays.env_material[2,2]==0
# Blocked chains do not consume energy or partially move.
w.place_cell(2,5,2,20); before=w.arrays.blocks.copy(); energy=w.arrays.energy[2,2]
assert run(w,action(2,2,3,2))['move']==0
assert np.array_equal(before,w.arrays.blocks) and w.arrays.energy[2,2]==energy
# Reproduction and founder placement cannot overlap blocks.
assert run(w,action(2,2,3,2,Action.REPRODUCE))['reproduce']==0
try: w.place_cell(1,3,2)
except ValueError: pass
else: raise AssertionError('founder overlapped a block')
# Group pushes parallel chains as one transaction.
g=WorldState(8,8,0);g.arrays.env_material[:]=0
g.place_cell(1,1,2,20);g.place_cell(1,1,3,20);g._set_bond(1,2,1,3,True)
g.arrays.blocks[2,2]=1;g.arrays.blocks[3,2:4]=[2,3];g.place_cell(2,4,3,20)
assert run(g,action(1,2,2,2,Action.MOVE_GROUP))['move']==0
assert g.arrays.blocks[2,2]==1 and g.arrays.owner[2,1]==1
g._clear_cell(4,3)
assert run(g,action(1,2,2,2,Action.MOVE_GROUP))['move']==2
assert g.arrays.blocks[2,3]==1 and g.arrays.blocks[3,3:5].tolist()==[2,3]
# Reactions take effect after actions, independently of fixed terrain.
w.arrays.env_material[0,0:3]=2;w.arrays.blocks[0,0:3]=[1,2,3]; w.ecology()
assert w.arrays.blocks[0,0:3].tolist()==[0,2,2]
# Client and full snapshots preserve the layer, while hidden tiles remain hidden.
m=build_manifest({'world':{'width':16,'height':16},'perception':{'model':'radius','radius':1}})
v=WorldState(16,16,1);v.configure(m);v.place_cell(1,3,3,20);v.arrays.blocks[3,4]=3;v.arrays.blocks[10,10]=2
obs=gather_observation(v,1,m,'test'); kind, decoded=decode_msg(encode_msg('observation',**obs));assert kind=='observation'
obs=expand_observation(decoded,m); batch=to_legacy_batch(obs)
c=make_entities(batch['cells'],batch['neighborhood'],batch['env'],batch['constraints'],batch['tick'],obs)[0].cells[0]
assert c.sense(1,0).block==3 and c.sense(2,0) is None
assert observation_to_world(obs,1,16,16).blocks[10,10]==0
assert WorldArrays.from_dict(v.snapshot_arrays(),16,16).blocks[3,4]==3
v.delta_since_last_sent();v.arrays.blocks[3,4]=0
assert v.delta_since_last_sent()['environment']['blocks'][3,4]==0
# Seeded maps are reproducible and avoid dangerous ground.
a=WorldState(64,64,42); b=WorldState(64,64,42);a.seed_blocks(42);b.seed_blocks(42)
assert np.array_equal(a.arrays.blocks,b.arrays.blocks) and np.count_nonzero(a.arrays.blocks)>0
assert not np.any((a.arrays.blocks!=0) & (a.arrays.env_material>=2))
print('BLOCKS TEST PASSED')
