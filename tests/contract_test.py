"""Public contract conformance, malformed-input boundaries and SDK semantics."""
import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cellgame.api import *
from cellgame.shared.protocol import integer_rows
from cellgame.server.perception import gather_observation
from cellgame.shared.observation import to_legacy_batch
from cellgame.species.units import make_entities
from cellgame.client.rule_loader import load_rule
from cellgame.client.local_service import response_actions


def rejects(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"invalid input accepted by {fn.__name__}")


def main():
    assert negotiate_protocol(2) == 2
    assert negotiate_protocol(None, legacy=True) == 1
    assert negotiate_protocol(99, [99, 2]) == 2
    rejects(negotiate_protocol, 99)
    rejects(negotiate_protocol, True)
    rejects(negotiate_protocol, 2, [True])
    rejects(build_manifest, {'manifest_version':True})
    rejects(build_manifest, {'manifest_version':1.0})
    encoded = array_to_b64(np.array([0x1234, 0x5678], dtype='>u2'))
    assert base64.b64decode(encoded['data']) == bytes.fromhex('34127856')
    assert b64_to_array(encoded).tolist() == [0x1234, 0x5678]
    scalar = np.array(7, dtype=np.int16)
    assert b64_to_array(array_to_b64(scalar)).shape == ()
    structured = np.array([(12, -8)], dtype=[('id','>u4'), ('value','>i2')])
    assert b64_to_array(array_to_b64(structured)).tolist() == [(12, -8)]
    rejects(array_to_b64, np.array([object()], dtype=object))
    rejects(array_to_b64, np.array([1.0], dtype=np.float16))
    rejects(array_to_b64, np.zeros(1, dtype=np.dtype([('a','u1'),('b','i4')], align=True)))
    for malformed in (
        {**encoded, 'shape': [-1]}, {**encoded, 'shape': [True]},
        {**encoded, 'shape': [100000000]}, {**encoded, 'data': '!!!!'},
        {**encoded, 'shape': [3]}, {**encoded, 'byteorder': 'big'},
        {**encoded, 'dtype': 'object'},
    ):
        rejects(b64_to_array, malformed)
    for raw in ('[]', '{"type":"x","payload":[]}', '{"type":"x","payload":{"n":NaN}}'):
        rejects(decode_msg, raw)
    assert decode_msg(encode_msg('vendor.example', value=True)) == ('vendor.example', {'value': True})
    for data in ([[1.0, 2, 3, 4, 5]], [[True, 2, 3, 4, 5]], [[1,2]], [[1,2,3,4,2**64]]):
        rejects(integer_rows, data, 5, 16)
    assert integer_rows([], 5, 16).shape == (0,5)

    for fixture in ('observation-v2.json', 'hello.json'):
        kind, payload = decode_msg((ROOT/'shared/fixtures'/fixture).read_text(encoding='utf8'))
        assert kind in ('observation', 'hello') and isinstance(payload, dict)
    assert json.loads((ROOT/'shared/contract-v1.json').read_text(encoding='utf8')) == describe_contract()
    assert json.loads((ROOT/'shared/schemas/transport-v2.schema.json').read_text(encoding='utf8')) == protocol_schema()
    # The executable embedding example must stay valid as the public facade evolves.
    standard = (ROOT/'docs/CORE_STANDARD_zh.md').read_text(encoding='utf8')
    example = standard.split('```python\nfrom cellgame.api import (',1)[1].split('```',1)[0]
    exec('from cellgame.api import ('+example, {})

    world = WorldState(16,16,seed=5)
    manifest = build_manifest({'world':{'width':16,'height':16},'perception':{'model':'radius','radius':1}})
    world.configure(manifest)
    world.place_cell(1,4,4,20)
    world.arrays.env_material[4,4]=2
    world.arrays.env_biome[4,4]=3
    world.delta_since_last_sent()
    obs = expand_observation(gather_observation(world,1,manifest,'test-run'),manifest)
    rejects(validate_observation, {**obs,'version':99},manifest)
    rejects(validate_observation, {**obs,'manifest':'sha256:bad'},manifest)
    rejects(validate_observation, {**obs,'materials':np.zeros(len(obs['tiles'])+1,dtype=np.uint8)},manifest)
    rejects(validate_observation, {**obs,'cells':np.concatenate([obs['cells'],obs['cells']])},manifest)
    batch = to_legacy_batch(obs)
    entities = make_entities(batch['cells'],batch['neighborhood'],batch['env'],batch['constraints'],batch['tick'],obs)
    cell = entities[0].cells[0]
    assert cell.material_here == 2 and cell.biome_here == 3
    assert cell.world_run == 'test-run' and cell.entity_id == entities[0].id
    assert cell.sense(7,7) is None
    assert observation_to_json(obs)['world_run'] == 'test-run'
    for name in ('decide_cell', 'decide_entity', 'decide_unity'):
        bad_row = '[4,4,4,4,3.1,0,0]'
        source = f'def {name}(unit): return ' + (bad_row if name == 'decide_cell' else '['+bad_row+']')
        rejects(load_rule(source),batch['cells'],batch['neighborhood'],batch['env'],batch['constraints'],batch['tick'],observation=obs)
    assert not len(to_intentions([[4,4,4,4,3,0,0]], np.empty((0,5),dtype=np.int32),16,16))
    rejects(world.intentions_from_v2, 1, [[True,3,0,0,0]])
    rejects(response_actions, {'tick':True,'actions':[]}, {**batch,'tick':1})
    rejects(response_actions, {'tick':batch['tick'],'actions':[[4,4,4,4,3.1,0,0]]},batch)
    rejects(load_rule,'PLAYER_API_VERSION=99\ndef decide_cell(c): return None')
    assert WorldView(world.arrays).get_region(-100,-100,1,1)['owner'].size == 0
    rejects(WorldView(world.arrays).get_region,0,0,-1,2)
    # Identity is reconciled before the next observation, including bond merges.
    world.place_cell(1,5,4,20)
    action = to_intentions([[4,4,5,4,int(Action.BOND),0,0]],world_w=16,world_h=16)
    resolve_tick(world, {1:(action,np.array([1],dtype=np.int32))})
    assert world.arrays.organism[4,4] == world.arrays.organism[4,5]
    # An interior cell cannot recover hidden material through pooled boundary tiles.
    blanket = build_manifest({'world':{'width':16,'height':16},'perception':{'model':'blanket','external_radius':1}})
    inner = WorldState(16,16,seed=4); inner.configure(blanket)
    for y in range(3,6):
        for x in range(3,6): inner.place_cell(1,x,y,20)
    for y in range(3,6):
        for x in range(3,6):
            for dx,dy in ((1,0),(0,1),(1,1),(-1,1)):
                if 3 <= x+dx < 6 and 3 <= y+dy < 6: inner._set_bond(x,y,x+dx,y+dy,True)
    inner.arrays.env_material[:]=2
    inner.refresh_entities()
    hidden = expand_observation(gather_observation(inner,1,blanket,'inner'),blanket)
    hbatch = to_legacy_batch(hidden)
    group = make_entities(hbatch['cells'],hbatch['neighborhood'],hbatch['env'],hbatch['constraints'],hbatch['tick'],hidden)
    center = next(c for entity in group for c in entity.cells if (c.x,c.y)==(4,4))
    assert center.role == 'interior' and center.material_here is None
    assert not center.sense(0,0).env_visible
    subprocess.run([sys.executable,'-c',
        "import sys; import cellgame.api; assert not any(n.startswith('cellgame.client') for n in sys.modules); assert 'cellgame.server.net' not in sys.modules"],cwd=ROOT,check=True)
    print('CORE CONTRACT TEST PASSED')


if __name__ == '__main__':
    main()
