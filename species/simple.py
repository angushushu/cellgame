"""Small per-cell adapter. Each method returns an intention, not an effect."""
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from cellgame.shared import observation as obs_format
from cellgame.shared.models import Action
from cellgame.shared.protocol import integer_rows

# Per-cell memory for worlds that provide stable cell IDs. Lives as long as the
# local rule process; entries are dropped when their cell is no longer observed.
_MEMORY = {}
_MEMORY_RUN = [None]


def use_world_run(run):
    """Cell IDs restart with each server run; forget memory from an older run."""
    if _MEMORY_RUN[0] != run:
        _MEMORY.clear()
        _MEMORY_RUN[0] = run


def prune_memory(live_ids):
    for cid in set(_MEMORY) - set(live_ids):
        del _MEMORY[cid]


@dataclass(frozen=True)
class Percept:
    """One perceived tile, relative to the observing cell (observation v2)."""
    EMPTY: ClassVar[int] = obs_format.EMPTY
    MINE_BONDED: ClassVar[int] = obs_format.MINE_BONDED
    MINE: ClassVar[int] = obs_format.MINE
    ENEMY: ClassVar[int] = obs_format.OTHER
    HIDDEN: ClassVar[int] = obs_format.HIDDEN
    OUTSIDE: ClassVar[int] = obs_format.OUTSIDE

    dx: int
    dy: int
    occupant: int
    species: int
    cell_type: int
    state: int
    energy: int
    food: float
    temp: float
    env_visible: bool = True
    material: int | None = None
    biome: int | None = None
    # None is reserved to the legacy adapter, which lacks visibility metadata.

    @property
    def direction(self):
        return (self.dx, self.dy)

    @property
    def in_bounds(self):
        return self.occupant != self.OUTSIDE

    @property
    def is_empty(self):
        return self.occupant == self.EMPTY

    @property
    def is_mine(self):
        return self.occupant in (self.MINE, self.MINE_BONDED)

    @property
    def is_bonded(self):
        return self.occupant == self.MINE_BONDED

    @property
    def is_enemy(self):
        return self.occupant == self.ENEMY

    @property
    def is_hidden(self):
        """Occupied by another player's cell whose details are hidden."""
        return self.occupant == self.HIDDEN


RESULT_NAMES = ("ok", "invalid", "no_energy", "duplicate", "disabled", "blocked",
                "contested", "interrupted", "role")
ROLE_NAMES = {obs_format.BOUNDARY: "boundary", obs_format.INTERIOR: "interior"}


def _percept(row, layers=None):
    layers = layers if bool(row["env_visible"]) and layers is not None else (None, None)
    return Percept(int(row["dx"]), int(row["dy"]), int(row["occupant"]), int(row["species"]),
                   int(row["type"]), int(row["state"]), int(row["energy"]),
                   float(row["food"]), float(row["temp"]), bool(row["env_visible"]), *layers)


@dataclass(frozen=True)
class Neighbor:
    dx: int
    dy: int
    in_bounds: bool
    is_mine: bool
    species: int
    cell_type: int
    state: int
    energy: int
    food: float
    is_bonded: bool = False
    material: int | None = None
    biome: int | None = None
    observed: bool = True

    @property
    def is_empty(self):
        return self.observed and self.in_bounds and self.species == 0

    @property
    def is_enemy(self):
        return self.in_bounds and self.species != 0 and not self.is_mine


class Cell:
    def __init__(self, row, neighbors, env, constraints, tick=None, cell_id=None, percepts=None,
                 role=None, last_result=None, layers=None, entity_id=None, world_run=""):
        self.x, self.y, self.cell_type, self.state, self.energy = map(int, row)
        self.id = cell_id
        self.entity_id = entity_id
        self.world_run = world_run
        self._layers = layers or {}
        self.role = role                # "boundary" / "interior" in blanket worlds, else None
        self.last_result = last_result  # outcome of this cell's previous action, e.g. "blocked"
        self._percept_rows = percepts
        self._percept_cache = None
        self.food_here = float(env[1])
        self.bonds = int(env[11]) if len(env) > 11 else 0
        self.neighbors = neighbors
        self.env = env
        self.constraints = constraints
        self.tick = tick
        self._entity_positions = {(self.x, self.y)}

    def percepts(self):
        """Perceived in-bounds tiles (observation v2); [] in legacy worlds."""
        if self._percept_rows is None:
            return []
        if self._percept_cache is None:
            self._percept_cache = {(int(r["dx"]), int(r["dy"])): _percept(
                r, self._layers.get((self.x + int(r["dx"]), self.y + int(r["dy"])))) for r in self._percept_rows}
        return [p for p in self._percept_cache.values() if p.in_bounds]

    def sense(self, dx, dy):
        """The Percept at an offset, or None if that tile was not perceived."""
        self.percepts()
        if self._percept_cache is None:
            return None
        return self._percept_cache.get((dx, dy))

    @property
    def material_here(self):
        percept = self.sense(0, 0)
        return percept.material if percept is not None else None

    @property
    def biome_here(self):
        percept = self.sense(0, 0)
        return percept.biome if percept is not None else None

    @property
    def memory(self):
        """A dict that persists for this cell across ticks (needs cell IDs)."""
        if self.id is None:
            raise RuntimeError("cell.memory 需要提供 cell_id 的世界（非 legacy 感知）")
        return _MEMORY.setdefault(self.id, {})

    def surrounding(self):
        result = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == dy == 0:
                    continue
                x, y = self.x + dx, self.y + dy
                valid = 0 <= x < self.constraints["world_w"] and 0 <= y < self.constraints["world_h"]
                k = ((dy + 1) * 3 + dx + 1) * 5
                own, species, kind, state, energy = map(int, self.neighbors[k:k+5])
                food = float(self.env[2 + (dy + 1) * 3 + dx + 1]) if len(self.env) >= 11 and valid else 0.0
                direction_index = (dy + 1) * 3 + dx + 1
                bit = direction_index if direction_index < 4 else direction_index - 1
                p = self.sense(dx, dy)
                result.append(Neighbor(dx, dy, valid, bool(own), species, kind, state, energy, food,
                                       bool(self.bonds & (1 << bit)), p.material if p else None, p.biome if p else None,
                                       self._percept_rows is None or p is not None))
        return result

    @property
    def boundary_directions(self):
        """Directions leading outside this bonded component (including the world edge)."""
        return [(n.dx, n.dy) for n in self.surrounding()
                if (self.x + n.dx, self.y + n.dy) not in self._entity_positions]

    @property
    def is_boundary(self):
        return bool(self.boundary_directions)

    def empty_neighbors(self):
        result = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == dy == 0:
                    continue
                x, y = self.x + dx, self.y + dy
                if not (0 <= x < self.constraints['world_w'] and 0 <= y < self.constraints['world_h']):
                    continue
                if self._percept_rows is not None:
                    perceived = self.sense(dx, dy)
                    if perceived is None or not perceived.is_empty:
                        continue
                if self.neighbors[((dy + 1) * 3 + dx + 1) * 5 + 1] == 0:
                    result.append((dx, dy))
        return result

    def eat(self):
        return [self.x, self.y, self.x, self.y, Action.EAT, 0, 0]

    def reproduce(self, direction, bond=False):
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.REPRODUCE, 0, int(bond)]

    def bond(self, direction):
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.BOND, 0, 0]

    def unbond(self, direction):
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.UNBOND, 0, 0]

    def transfer(self, direction, amount):
        if type(amount) is not int or not 1 <= amount <= 100:
            raise ValueError("传递能量须为 1–100 的整数")
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.TRANSFER, 0, amount]

    def move(self, direction):
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.MOVE, 0, 0]

    def move_group(self, direction):
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.MOVE_GROUP, 0, 0]

    def attack(self, direction):
        dx, dy = direction
        return [self.x, self.y, self.x + dx, self.y + dy, Action.ATTACK, 0, 0]

    def change_type(self, cell_type):
        if type(cell_type) is not int or not 0 <= cell_type <= 32767:
            raise ValueError("细胞类型需为 0–32767 的整数")
        return [self.x, self.y, self.x, self.y, Action.CHANGE, 0, cell_type]

    def set_state(self, state):
        if type(state) is not int or not 0 <= state <= 2147483647:
            raise ValueError("细胞状态需为 0–2147483647 的整数")
        return [self.x, self.y, self.x, self.y, Action.SET_STATE, 0, state]

    def extend_sense(self, radius):
        """Pay energy now to perceive this radius in the next observation
        (worlds that enable the sense action)."""
        if type(radius) is not int or not 1 <= radius <= 8:
            raise ValueError("感知半径需为 1–8 的整数")
        return [self.x, self.y, self.x, self.y, Action.SENSE, 0, radius]

    def wait(self):
        return None


def run_cells(rule, cells, neighborhood, env, constraints, tick=None, observation=None):
    actions = []
    from cellgame.species.units import make_entities
    for entity in make_entities(cells, neighborhood, env, constraints, tick, observation):
        for cell in entity.cells:
            action = rule(cell)
            if action is not None:
                actions.append(action)
    return integer_rows(actions, 7, constraints["world_w"] * constraints["world_h"])
