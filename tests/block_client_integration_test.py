"""Exercise block observations and actions through both client protocol paths."""
import asyncio, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cellgame.client.net import ClientState, GameClient
from cellgame.server.world import WorldState
from cellgame.server.perception import gather_observation
from cellgame.server.kernel import resolve_tick
from cellgame.shared.manifest import build_manifest
from cellgame.shared.observation import expand_observation, to_legacy_batch
from cellgame.shared.models import Action
from cellgame.shared.protocol import encode_msg, decode_msg
from cellgame.species.runtime import load_rule, to_intentions
from cellgame.species.composer import DEFAULT, decide_with_config, build_source
from cellgame.species import grazer

SOURCE='''def decide_cell(cell):
    p = cell.sense(1, 0)
    return cell.attack((1, 0)) if p is not None and p.block == 1 else cell.wait()
'''
class Executor:
    ns = {'decide':True}
    last_duration_ms = 0
    last_error = None
    async def run(self, batch):
        self.batch = batch
        result = load_rule(SOURCE)(batch['cells'],batch['neighborhood'],batch['env'],batch['constraints'],batch['tick'],observation=batch.get('observation'))
        return to_intentions(result,batch['cells'],16,16)
class Socket:
    def __init__(self): self.sent=[]
    async def send(self,data): self.sent.append(decode_msg(data))

async def legacy_flow():
    w=WorldState(16,16,1);m=build_manifest({'world':{'width':16,'height':16}});w.configure(m)
    w.place_cell(1,4,4,20);w.arrays.blocks[4,5]=1
    batch=w.gather_sense(1);batch['local_observation']=gather_observation(w,1,m,'legacy-run')
    kind,payload=decode_msg(encode_msg('sense_batch',**batch))
    state=ClientState();state.manifest=m;state.player_id=1;state.ws=Socket();executor=Executor()
    await GameClient(state,executor).handle(kind,payload)
    assert executor.batch['observation']['blocks'].any()
    mtype,proposal=state.ws.sent[0];assert mtype=='intentions' and 'format' not in proposal
    action=proposal['data'];assert len(action)==1 and action['action'][0]==Action.ATTACK
    resolve_tick(w,{1:(action,np.array([1],dtype=np.int32))})
    assert w.arrays.blocks[4,5]==0

# All awaited test doubles complete synchronously; no OS sockets are needed.
coro = legacy_flow()
try:
    coro.send(None)
except StopIteration:
    pass
else:
    raise AssertionError("unexpected asynchronous suspension")
# Surrounded cells avoid spawning on blocks and can clear a way.
w=WorldState(16,16,2);m=build_manifest({'world':{'width':16,'height':16},'perception':{'model':'radius','radius':1}});w.configure(m)
w.arrays.env_food[:]=0;w.arrays.env_material[:]=0;w.place_cell(1,4,4,20)
w.arrays.blocks[3:6,3:6]=1;w.arrays.blocks[4,4]=0
obs=expand_observation(gather_observation(w,1,m),m);b=to_legacy_batch(obs)
args=(b['cells'],b['neighborhood'],b['env'],b['constraints'],b['tick'])
a=decide_with_config(DEFAULT,*args,observation=obs)
assert len(a)==1 and a[0,4]==Action.ATTACK
a2=grazer.decide(*args,observation=obs);assert len(a2)==1 and a2[0,4]==Action.ATTACK
ns={};exec(build_source(DEFAULT),ns);assert np.array_equal(a,ns['decide'](*args,observation=obs))
print('BLOCK CLIENT INTEGRATION TEST PASSED')
