"""World economics are server-authoritative; identities follow bond topology."""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cellgame.server.world import WorldState
from cellgame.server.world_rules import apply_world_params
from cellgame.shared.arbiter import arbitrate
from cellgame.shared.models import Action
from cellgame.client.executor import to_intentions

def apply(w, row):
    a=to_intentions([row]); result=arbitrate(a,w,w.constraints,player_ids=np.array([1]));w.apply_intentions(result);return len(result)

def main():
    w=WorldState(12,12,seed=7);a=w.arrays
    a.owner[4,4]=a.species[4,4]=1;a.energy[4,4]=30
    apply_world_params(w,{'move_cost':7,'reproduce_cost':9,'reproduce_min_energy':12,'child_energy':4,'eat_gain':3,'attack_reward_percent':25})
    assert w.constraints['move_cost']==7
    apply_world_params(w,{'move_cost':-5,'eat_gain':True})
    assert w.constraints['move_cost']==7 and w.constraints['eat_gain']==3
    snap=w.delta_since_last_sent();parent=int(a.organism[4,4]);assert parent>0
    a.env_food[4,4]=10;assert apply(w,[4,4,4,4,Action.EAT,32000,0]);assert int(a.energy[4,4])==33 and a.env_food[4,4]==7
    a.energy[4,4]=3;assert not apply(w,[4,4,5,4,Action.MOVE,32000,0]);assert a.owner[4,4]==1
    a.energy[4,4]=33
    assert apply(w,[4,4,5,4,Action.MOVE,0,0]);assert int(a.energy[4,5])==26 and int(a.organism[4,5])==parent
    assert apply(w,[5,4,6,4,Action.REPRODUCE,0,1]);w.delta_since_last_sent();assert int(a.organism[4,6])==parent
    assert apply(w,[5,4,5,5,Action.REPRODUCE,0,0]);snap=w.delta_since_last_sent();child=int(a.organism[5,5]);assert child!=parent
    assert w.organisms.live[str(child)]['parent']==parent and w.organisms.live[str(parent)]['children']==1
    assert apply(w,[5,4,6,4,Action.UNBOND,0,0]);snap=w.delta_since_last_sent();split=int(a.organism[4,6]);assert split not in (parent,child)
    assert w.organisms.live[str(split)]['origin']=='split' and w.organisms.live[str(split)]['parent']==parent
    assert w.organisms.live[str(parent)]['children']==2
    assert apply(w,[5,4,5,5,Action.BOND,0,0]);snap=w.delta_since_last_sent();assert a.organism[5,5]==a.organism[4,5]
    assert len(w.organisms.live[str(int(a.organism[4,5]))]['merged_from'])==1
    a.owner[4,4]=a.species[4,4]=2;a.energy[4,4]=4
    before=int(a.energy[4,5]);assert apply(w,[5,4,4,4,Action.ATTACK,32000,0])
    assert int(a.energy[4,5]) == before - 3 + 1 and a.owner[4,4]==0
    print('WORLD ECONOMY AND ORGANISM TEST PASSED')
if __name__=='__main__': main()
