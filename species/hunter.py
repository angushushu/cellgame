"""hunter -- attacks adjacent foreign cells, otherwise lives like a grazer.

ATTACK succeeds when strength > victim energy; strength here is our own
energy. After a kill the attacker gains half the victim's energy.
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
        # 1. attack the weakest adjacent enemy we can beat
        bonus = constraints.get("armor_defense_bonus", 3)
        beatable = [(dx, dy, e) for dx, dy, e in enemies
                    if en > e + (bonus if neighborhood[i, ((dy + 1) * 3 + dx + 1) * 5 + 2] == 1 else 0)
                    and en > 3]
        if beatable:
            dx, dy, e = min(beatable, key=lambda t: t[2])
            out.append([x, y, x + dx, y + dy, Action.ATTACK, en, 0])
            continue
        # 2. eat
        if env[i, 1] > 0 and en < 20:
            out.append([x, y, x, y, Action.EAT, 0, 0])
            continue
        # 3. reproduce
        if en >= 13 and constraints.get("reproduce_enabled", True) and empties:
            dx, dy = empties[(tick + x * 7 + y * 13) % len(empties)]
            out.append([x, y, x + dx, y + dy, Action.REPRODUCE, 0, 0])
            continue
        # 4. move toward an enemy, else wander
        if en > 4 and enemies:
            dx, dy, e = enemies[(tick + x) % len(enemies)]
            # step toward it if the step cell is empty
            sx = 0 if dx == 0 else (1 if dx > 0 else -1)
            sy = 0 if dy == 0 else (1 if dy > 0 else -1)
            if (sx, sy) in empties:
                out.append([x, y, x + sx, y + sy, Action.MOVE, 0, 0])
                continue
        if en > 4 and empties:
            dx, dy = empties[(tick * 3 + x * 5 + y * 11) % len(empties)]
            out.append([x, y, x + dx, y + dy, Action.MOVE, 0, 0])
    return np.array(out, dtype=np.int32) if out else np.empty((0, 7), np.int32)
