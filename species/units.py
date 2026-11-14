"""Client-side control units constructed from the server's owned-cell observations.

These are decision helpers, not authoritative server-side Unity membership.
A Unity here contains all of the current player's observed bonded components.
"""
import numpy as np
from cellgame.shared.observation import EVENT_RESULT
from cellgame.shared.protocol import integer_rows
from cellgame.species.simple import RESULT_NAMES, ROLE_NAMES, Cell, prune_memory, use_world_run


class Unit:
    @property
    def tick(self):
        return self.cells[0].tick if self.cells else None

    @property
    def cell_count(self):
        return len(self.cells)

    @property
    def energy(self):
        return sum(cell.energy for cell in self.cells)

    @property
    def boundary(self):
        return tuple(cell for cell in self.cells if cell.is_boundary)


class Entity(Unit):
    def __init__(self, cells):
        self.cells = tuple(cells)
        self.members = self.cells
        ids = {c.entity_id for c in self.cells}
        self.id = next(iter(ids)) if len(ids) == 1 else None
        self.world_run = self.cells[0].world_run if self.cells else ""
        positions = {(c.x, c.y) for c in self.cells}
        for cell in self.cells:
            cell._entity_positions = positions


class Unity(Unit):
    def __init__(self, members):
        self.id = None  # no server-authoritative Unity membership yet
        self.members = tuple(members)
        self.cells = tuple(cell for member in self.members
                           for cell in ((member,) if isinstance(member, Cell) else member.cells))
        positions = [(c.x, c.y) for c in self.cells]
        if len(positions) != len(set(positions)):
            raise ValueError("Unity members must not overlap")
        self._positions = set(positions)

    def boundary_directions(self, cell):
        positions = self._positions
        if (cell.x, cell.y) not in positions:
            raise ValueError("cell is not a Unity member")
        return [(n.dx, n.dy) for n in cell.surrounding()
                if (cell.x + n.dx, cell.y + n.dy) not in positions]

    @property
    def boundary(self):
        return tuple(cell for cell in self.cells if self.boundary_directions(cell))


def _last_results(observation):
    results = {}
    for event in observation.get("events", ()):
        if int(event["kind"]) == EVENT_RESULT and 0 <= int(event["code"]) < len(RESULT_NAMES):
            results[int(event["cell_id"])] = RESULT_NAMES[int(event["code"])]
    return results


def _per_cell_views(observation, n):
    """Keyword arguments for each observed Cell (empty in legacy worlds)."""
    if observation is None:
        return [{}] * n
    use_world_run(observation.get("world_run", ""))
    cells = observation["cells"]
    ids = [int(cid) for cid in cells["cell_id"]]
    roles = cells["role"].tolist() if "role" in cells.dtype.names else [0] * n
    percepts = observation["percepts"]
    bounds = np.searchsorted(percepts["observer"], np.arange(n + 1))
    results = _last_results(observation)
    tiles, layers = observation["tiles"], {}
    for i, tile in enumerate(tiles):
        if not tile["env_visible"]:
            continue
        values = []
        for key in ("materials", "biomes", "blocks"):
            source = observation.get(key)
            values.append(int(source[i]) if source is not None and len(source) == len(tiles) else None)
        layers[(int(tile["x"]), int(tile["y"]))] = tuple(values)
    prune_memory(ids)
    return [{"cell_id": ids[i], "percepts": percepts[bounds[i]:bounds[i + 1]],
             "entity_id": int(cells[i]["entity"]) or None,
             "world_run": observation.get("world_run", ""), "layers": layers,
             "role": ROLE_NAMES.get(roles[i]), "last_result": results.get(ids[i])}
            for i in range(n)]


def make_entities(cells, neighborhood, env, constraints, tick, observation=None):
    views = _per_cell_views(observation, len(cells))
    observed = [Cell(row, near, local, constraints, tick, **view)
                for row, near, local, view in zip(cells, neighborhood, env, views)]
    by_pos = {(c.x, c.y): c for c in observed}
    unvisited = set(by_pos)
    entities = []
    while unvisited:
        start = min(unvisited)
        unvisited.remove(start)
        stack, component = [start], []
        while stack:
            pos = stack.pop()
            cell = by_pos[pos]
            component.append(cell)
            for n in cell.surrounding():
                other = (cell.x + n.dx, cell.y + n.dy)
                if n.is_bonded and other in unvisited:
                    unvisited.remove(other)
                    stack.append(other)
        entities.append(Entity(component))
    return entities


def _actions(result):
    if result is None:
        return []
    if isinstance(result, np.ndarray):
        result = result.tolist()
    if len(result) == 7 and all(np.isscalar(x) for x in result):
        return [result]
    return list(result)


def run_units(rule, scale, cells, neighborhood, env, constraints, tick, observation=None):
    entities = make_entities(cells, neighborhood, env, constraints, tick, observation)
    if scale == "entity":
        units = entities
    elif scale == "unity":
        units = [Unity(entities)] if entities else []
    else:
        raise ValueError("unknown unit scale")
    actions = []
    for unit in units:
        actions.extend(_actions(rule(unit)))
    return integer_rows(actions, 7, constraints["world_w"] * constraints["world_h"])
