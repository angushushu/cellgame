"""Headless smoke test (verification step 1).

Two hard-coded species (grazer + hunter) in a 256x256 world, run the
sim tick logic in-process for 30 ticks (no networking): gather sense,
call decide(), arbitrate, apply, ecology. Pass = no crash, and cells
actually eat, reproduce and die.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from server.world import WorldState
from shared.arbiter import arbitrate
from client.executor import to_intentions
from species.grazer import decide as grazer_decide
from species.hunter import decide as hunter_decide


def main(ticks=30):
    world = WorldState(256, 256, seed=0)
    world.spawn_player(1, 1, count=30, seed=1)
    world.spawn_player(2, 2, count=30, seed=2)
    total = {"eat": 0, "reproduce": 0, "attack": 0, "move": 0, "die": 0}
    died_ecology = 0
    for t in range(ticks):
        intents, pids = [], []
        for pid, fn in ((1, grazer_decide), (2, hunter_decide)):
            batch = world.gather_sense(pid)
            assert batch["cells"].shape[1] == 5
            assert batch["neighborhood"].shape[1] == 45
            assert batch["env"].shape[1] == 12  # v1 batch: 11 original columns + bond mask
            arr = to_intentions(fn(batch["cells"], batch["neighborhood"],
                                   batch["env"], batch["constraints"], t))
            if len(arr):
                intents.append(arr)
                pids.append(np.full(len(arr), pid, dtype=np.int32))
        if intents:
            all_intents = np.concatenate(intents)
            all_pids = np.concatenate(pids)
            resolved = arbitrate(all_intents, world, world.constraints,
                                 tick=t, player_ids=all_pids)
            counts = world.apply_intentions(
                resolved, world.arrays.owner[resolved["src_y"], resolved["src_x"]]
                if len(resolved) else None)
            for k in total:
                total[k] += counts.get(k, 0)
        died_ecology += world.ecology()
        world.tick += 1
        if t % 10 == 0 or t == ticks - 1:
            s = world.summary()
            print(f"tick {t:2d}: cells={s['total_cells']:4d} "
                  f"per-player={s['cells_per_player']} food={s['total_food']:.0f}")
    print("actions:", total, "| ecology deaths:", died_ecology)
    assert total["eat"] > 0, "no EAT happened"
    assert total["reproduce"] > 0, "no REPRODUCE happened"
    assert total["move"] > 0, "no MOVE happened"
    assert world.summary()["total_cells"] > 0, "everyone died"
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
