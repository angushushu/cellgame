"""Animation events reflect applied actions and do not change the game protocol."""
import asyncio
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cellgame.client.executor import to_intentions
from cellgame.client.net import ClientState, GameClient
from cellgame.server.world import WorldState
from cellgame.shared.arbiter import arbitrate
from cellgame.shared.models import Action, WorldArrays
from cellgame.shared.protocol import encode_msg, decode_msg


def apply(world, row, pid=1):
    actions = to_intentions([row])
    resolved = arbitrate(actions, world, world.constraints, player_ids=np.array([pid]))
    world.apply_intentions(resolved)


def main():
    world = WorldState(8, 8, seed=3)
    a = world.arrays
    a.owner[2, 2] = a.species[2, 2] = 1
    a.energy[2, 2] = 20
    a.env_food[2, 2] = 5
    world.delta_since_last_sent()
    apply(world, [2,2,2,2,Action.EAT,0,0])
    apply(world, [2,2,3,2,Action.MOVE,0,0])
    apply(world, [3,2,3,3,Action.REPRODUCE,0,0])
    apply(world, [3,3,3,3,Action.DIE,0,0])
    delta = world.delta_since_last_sent()
    assert [row[0] for row in delta['visual_events']] == ['eat', 'move', 'birth', 'death']
    assert delta['visual_events'][1][1:6] == [2,2,3,2,1]
    assert world.delta_since_last_sent()['visual_events'] == []
    kind, decoded = decode_msg(encode_msg('world_delta', **delta))
    assert kind == 'world_delta' and decoded['visual_events'] == delta['visual_events']
    state = ClientState()
    state.world = WorldArrays(8, 8)
    game = GameClient(state, None)
    asyncio.run(game.handle('world_delta', decoded))
    assert state.visual_seq == 1 and state.visual_events[0]['events'] == delta['visual_events']
    # Older servers omit visual_events; the client remains compatible.
    asyncio.run(game.handle('world_delta', {'tick': 2, 'changes': np.empty((0,8), dtype=np.int32)}))
    assert state.visual_seq == 1
    # Bound effects prevent oversized network messages during large die-offs.
    large = WorldState(32, 32, seed=2)
    large.spawn_player(1, 1, count=270, seed=2)
    assert len(large.delta_since_last_sent()['visual_events']) == 48
    for _ in range(300):
        large._visual('eat', 1, 1, 1, 1, 1)
        large._visual('move', 1, 1, 2, 1, 1)
    effects = large.delta_since_last_sent()['visual_events']
    assert len(effects) == 112 and {row[0] for row in effects} == {'eat', 'move'}
    print('VISUAL EVENTS TEST PASSED')

if __name__ == '__main__':
    main()
