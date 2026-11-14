"""grazer -- eats resources and reproduces. The baseline species.

Neighborhood layout: (n, 45) flattened 3x3 Moore, each neighbor
(owner_is_self, species, cell_type, state, energy).
Neighbor (dx, dy) is at index ((dy+1)*3 + (dx+1)) * 5.
Empty neighbor <=> species == 0.
"""
import numpy as np

from cellgame.shared.models import Action


def _neighbors(row):
    """Return list of (dx, dy, owner_is_self, species, energy) for the
    8 surrounding cells (center excluded)."""
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            k = ((dy + 1) * 3 + (dx + 1)) * 5
            out.append((dx, dy, int(row[k]), int(row[k + 1]), int(row[k + 4])))
    return out


def decide(cells, neighborhood, env, constraints, tick):
    out = []
    for i in range(cells.shape[0]):
        x, y, ct, st, en = (int(v) for v in cells[i])
        nbs = _neighbors(neighborhood[i])
        empties = [(dx, dy) for dx, dy, own, sp, e in nbs if sp == 0]
        # 1. eat food on our own cell (but keep some room to grow)
        if env[i, 1] > 0 and en < 20:
            out.append([x, y, x, y, Action.EAT, 0, 0])
            continue
        # 2. reproduce into an empty neighbor
        if en >= 13 and constraints.get("reproduce_enabled", True) and empties:
            dx, dy = empties[(tick + x * 7 + y * 13) % len(empties)]
            out.append([x, y, x + dx, y + dy, Action.REPRODUCE, 0, 0])
            continue
        # 3. wander to an empty neighbor
        if en > 4 and empties:
            food = env[i, 2:] if env.shape[1] >= 11 else None
            if food is not None and any(food[(dy + 1) * 3 + dx + 1] > 0 for dx, dy in empties):
                dx, dy = max(empties, key=lambda p: food[(p[1] + 1) * 3 + p[0] + 1])
            else:
                dx, dy = empties[(tick * 3 + x * 5 + y * 11) % len(empties)]
            out.append([x, y, x + dx, y + dy, Action.MOVE, 0, 0])
    return np.array(out, dtype=np.int32) if out else np.empty((0, 7), np.int32)
