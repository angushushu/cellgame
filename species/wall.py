"""wall -- never moves. Eats, reproduces, and switches to armored
cell_type=1 when an enemy is adjacent.

Type 1 has a defense bonus but costs more to move. Defense uses the
pre-tick type; a change takes effect against attacks on the next tick.
"""
import numpy as np

from cellgame.shared.models import Action
from cellgame.species.grazer import _neighbors


def decide(cells, neighborhood, env, constraints, tick):
    out = []
    for i in range(cells.shape[0]):
        x, y, ct, st, en = (int(v) for v in cells[i])
        nbs = _neighbors(neighborhood[i])
        enemies = [(dx, dy, e) for dx, dy, own, sp, e in nbs
                   if own == 0 and sp != 0]
        empties = [(dx, dy) for dx, dy, own, sp, e in nbs if sp == 0]
        # 1. armor up when threatened
        if enemies and ct != 1 and en >= 2:
            out.append([x, y, x, y, Action.CHANGE, 0, 1])
            continue
        # 2. eat
        if env[i, 1] > 0 and en < 20:
            out.append([x, y, x, y, Action.EAT, 0, 0])
            continue
        # 3. reproduce into an empty neighbor
        if en >= 10 and constraints.get("reproduce_enabled", True) and empties:
            dx, dy = empties[(tick + x * 7 + y * 13) % len(empties)]
            out.append([x, y, x + dx, y + dy, Action.REPRODUCE, 0, 0])
            continue
        # 4. otherwise: stay put (no action)
    return np.array(out, dtype=np.int32) if out else np.empty((0, 7), np.int32)
