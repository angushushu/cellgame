"""Attack resolution shared by the arbiter (pre-tick check) and the world
(landing check): an attack lands when the attacker's energy is strictly
greater than the target's defence.

defence = energy + armour bonus (type 1)
          + bonded_support_percent % of the energy of the target's bonded neighbours

The support term (the world's ``combat.bonded_support_percent``, 0 by default)
lets a bonded body defend as a whole instead of cell by cell.
"""
from __future__ import annotations

import numpy as np

from .models import ARMOR_TYPE
from .world_parameters import DEFAULTS

_DIRECTIONS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0)]


def defense(energy: np.ndarray, cell_type: np.ndarray, bonds: np.ndarray, xs: np.ndarray,
            ys: np.ndarray, constraints: dict, support_percent: int = 0) -> np.ndarray:
    """Defence of the cells at (xs, ys), as int64."""
    xs, ys = np.asarray(xs, dtype=np.int64), np.asarray(ys, dtype=np.int64)
    bonus = constraints.get("armor_defense_bonus", DEFAULTS["armor_defense_bonus"])
    result = energy[ys, xs].astype(np.int64) + (cell_type[ys, xs] == ARMOR_TYPE) * bonus
    if support_percent:
        h, w = energy.shape
        support = np.zeros(len(xs), dtype=np.int64)
        own_bonds = bonds[ys, xs]
        for bit, (dx, dy) in enumerate(_DIRECTIONS):
            nx, ny = xs + dx, ys + dy
            linked = ((own_bonds >> bit) & 1).astype(bool) & (nx >= 0) & (nx < w) & (ny >= 0) & (ny < h)
            support[linked] += energy[ny[linked], nx[linked]]
        result += support * support_percent // 100
    return result
