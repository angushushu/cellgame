"""Observation format v2: table layouts and client-side adapters.

On the wire the server sends ``cells`` (one row per owned cell) and ``tiles``
(each perceived tile once, with absolute coordinates). ``expand_observation``
rebuilds ``percepts``: one row per (observing cell, perceived offset), grouped
by observer row. A tile that was not perceived has no row, so "unknown" and
"empty" differ.

``to_legacy_batch`` turns an expanded observation into the 0.1.x batch shapes
so every existing rule entry point keeps working; ``intentions_to_v2`` maps
the rules' coordinate-based rows back to cell IDs.
"""
from __future__ import annotations

from typing import Any

import numpy as np

# Occupant codes for percept rows.
EMPTY = 0          # in bounds, no cell
MINE_BONDED = 1    # own cell bonded to the observer
MINE = 2           # own cell, not bonded to the observer (includes the observer itself)
OTHER = 3          # another player's cell
HIDDEN = 4         # occupied by another player's cell whose details are hidden
OUTSIDE = 5        # beyond the world edge

# Topological roles of a cell within its bonded component.
ROLE_NONE = 0      # roles not computed for this world
BOUNDARY = 1       # has at least one neighbor tile outside its component
INTERIOR = 2       # every neighbor tile belongs to its component

# Values a hidden attribute takes in a percept or tile row.
HIDDEN_VALUE = -1

CELL_DTYPE = np.dtype([
    ("cell_id", np.uint32), ("x", np.int16), ("y", np.int16), ("type", np.int16),
    ("state", np.int64), ("energy", np.int32), ("bonds", np.uint8),
    ("entity", np.int32), ("role", np.int8), ("sense_radius", np.int8),
])

# env_visible is false when the tile's resource layers were not perceived
# (food is then -1 and temp 0).
PERCEPT_DTYPE = np.dtype([
    ("observer", np.int32), ("dx", np.int8), ("dy", np.int8), ("occupant", np.int8),
    ("species", np.int16), ("type", np.int16), ("state", np.int64), ("energy", np.int32),
    ("food", np.float32), ("temp", np.float32), ("env_visible", np.bool_),
])

# Events about the player's own cells since the previous observation.
EVENT_RESULT, EVENT_BORN, EVENT_DIED = 0, 1, 2
# Result codes for EVENT_RESULT (one per proposal the server could attribute).
R_OK = 0           # accepted and applied
R_INVALID = 1      # malformed: not owned, not adjacent, bad parameter
R_NO_ENERGY = 2    # not enough energy
R_DUPLICATE = 3    # another proposal for the same cell came first
R_DISABLED = 4     # the action is disabled in this world or right now
R_BLOCKED = 5      # precondition failed: target occupied, no food, too strong...
R_CONTESTED = 6    # another proposal won the same target
R_INTERRUPTED = 7  # accepted, but the world changed before it applied
R_ROLE = 8         # this cell's role may not perform the action
# Causes for EVENT_DIED.
DIED_ATTACK, DIED_STARVED, DIED_SELF = 1, 2, 3

EVENT_DTYPE = np.dtype([
    ("kind", np.int8), ("cell_id", np.uint32), ("action", np.int8), ("code", np.int8),
    ("other", np.uint32),   # BORN: the parent's cell_id
])

# Wire form: each perceived tile once. occupant is EMPTY, MINE or OTHER here;
# MINE_BONDED and OUTSIDE depend on the observer and are derived on expansion.
TILE_DTYPE = np.dtype([
    ("x", np.int16), ("y", np.int16), ("occupant", np.int8),
    ("species", np.int16), ("type", np.int16), ("state", np.int64), ("energy", np.int32),
    ("food", np.float32), ("temp", np.float32), ("env_visible", np.bool_),
])

V2_ROW_WIDTH = 5  # [cell_id, action, dx, dy, param]

# Bond bit for each Moore offset, matching the server's direction order.
_BOND_BITS = {(dx, dy): bit for bit, (dx, dy) in enumerate(
    (dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0))}
# _BIT_TABLE[dy + 1, dx + 1] is the bond bit of a Moore offset (-1 for the centre).
_BIT_TABLE = np.array([[_BOND_BITS.get((dx, dy), -1) for dx in (-1, 0, 1)] for dy in (-1, 0, 1)],
                      dtype=np.int64)
_TILE_COLUMNS = ("species", "type", "state", "energy", "food", "temp", "env_visible")


def _cell_offsets(cells: np.ndarray, metric: str, blanket: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(observer, dx, dy) for every offset each cell perceives, grouped by
    observer in row-major offset order.

    Interior cells perceive themselves and their bonded neighbors; every other
    cell perceives its window of ``sense_radius``.
    """
    from .manifest import window_offsets

    parts = []
    interior = (cells["role"] == INTERIOR) if blanket else np.zeros(len(cells), dtype=bool)
    radii = cells["sense_radius"].astype(np.int64)
    for radius in np.unique(radii[~interior]):
        rows = np.where(~interior & (radii == radius))[0]
        offsets = np.array(window_offsets(int(radius), metric), dtype=np.int64).reshape(-1, 2)
        k = len(offsets)
        parts.append((np.repeat(rows, k), np.tile(offsets[:, 0], len(rows)), np.tile(offsets[:, 1], len(rows))))
    rows = np.where(interior)[0]
    if len(rows):
        moore = np.array(window_offsets(1), dtype=np.int64)
        bits = np.array([_BOND_BITS.get((int(dx), int(dy)), -1) for dx, dy in moore])
        observer = np.repeat(rows, 9)
        bit = np.tile(bits, len(rows))
        bonds = cells["bonds"].astype(np.int64)[observer]
        keep = (bit < 0) | (((bonds >> np.maximum(bit, 0)) & 1) == 1)
        parts.append((observer[keep], np.tile(moore[:, 0], len(rows))[keep], np.tile(moore[:, 1], len(rows))[keep]))
    if not parts:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty, empty
    observer, dx, dy = (np.concatenate(column) for column in zip(*parts))
    order = np.argsort(observer, kind="stable")
    return observer[order], dx[order], dy[order]


def validate_observation(obs: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Validate decoded v2 tables before a frontend or controller uses them.

    Extra top-level fields are allowed; existing table layouts cannot change
    within an observation version. This checks structure, not server honesty.
    """
    from .manifest import manifest_hash, MAX_RADIUS
    from .protocol import ProtocolError

    if not isinstance(obs, dict) or type(obs.get("version")) is not int or obs["version"] != 2:
        raise ProtocolError("unsupported observation version")
    if type(obs.get("tick")) is not int or obs["tick"] < 0 or not isinstance(obs.get("constraints"), dict):
        raise ProtocolError("invalid observation header")
    if obs.get("manifest") != manifest_hash(manifest) or not isinstance(obs.get("world_run", ""), str):
        raise ProtocolError("observation manifest or world identity mismatch")
    width, height = manifest["world"]["width"], manifest["world"]["height"]
    for key, dtype in (("cells", CELL_DTYPE), ("tiles", TILE_DTYPE), ("events", EVENT_DTYPE)):
        rows = obs.get(key, np.empty(0, dtype=dtype)) if key == "events" else obs.get(key)
        if not isinstance(rows, np.ndarray) or rows.ndim != 1 or rows.dtype != dtype.newbyteorder('<'):
            raise ProtocolError(f"invalid {key} table layout")
        if key == "events":
            continue
        if len(rows) > width * height or np.any((rows["x"] < 0) | (rows["x"] >= width) | (rows["y"] < 0) | (rows["y"] >= height)):
            raise ProtocolError(f"invalid {key} coordinates")
        if len(np.unique(rows["y"].astype(np.int64) * width + rows["x"])) != len(rows):
            raise ProtocolError(f"duplicate {key} coordinates")
    cells, tiles = obs["cells"], obs["tiles"]
    if np.any(cells["cell_id"] == 0) or len(np.unique(cells["cell_id"])) != len(cells):
        raise ProtocolError("invalid cell identities")
    if np.any((cells["role"] < 0) | (cells["role"] > 2)) or np.any((cells["sense_radius"] < 0) | (cells["sense_radius"] > MAX_RADIUS)):
        raise ProtocolError("invalid cell role or radius")
    if not np.all(np.isin(tiles["occupant"], [EMPTY, MINE, OTHER, HIDDEN])):
        raise ProtocolError("invalid wire occupant code")
    for key in ("materials", "biomes", "blocks"):
        if key in obs:
            layer = obs[key]
            if not isinstance(layer, np.ndarray) or layer.dtype != np.uint8 or layer.shape != (len(tiles),):
                raise ProtocolError(f"invalid {key} layer")


def expand_observation(obs: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a wire observation with per-cell ``percepts`` added.

    Offsets beyond the world edge become OUTSIDE rows, and in-bounds offsets
    that the server did not include are left out (unknown).
    """
    validate_observation(obs, manifest)
    cells, tiles = obs["cells"], obs["tiles"]
    width, height = manifest["world"]["width"], manifest["world"]["height"]
    blanket = manifest["perception"]["model"] == "blanket"
    observer, dx, dy = _cell_offsets(cells, manifest["perception"].get("metric", "chebyshev"), blanket)
    tx = cells["x"].astype(np.int64)[observer] + dx
    ty = cells["y"].astype(np.int64)[observer] + dy
    inside = (tx >= 0) & (tx < width) & (ty >= 0) & (ty < height)

    keys = tiles["y"].astype(np.int64) * width + tiles["x"].astype(np.int64)
    order = np.argsort(keys)
    keys = keys[order]
    wanted = ty * width + tx
    if len(keys):
        pos = np.clip(np.searchsorted(keys, wanted), 0, len(keys) - 1)
        found = inside & (keys[pos] == wanted)
    else:
        pos = np.zeros(len(wanted), dtype=np.int64)
        found = np.zeros(len(wanted), dtype=bool)
    keep = found | ~inside

    percepts = np.zeros(len(observer), dtype=PERCEPT_DTYPE)
    percepts["observer"], percepts["dx"], percepts["dy"] = observer, dx, dy
    source = tiles[order][pos] if len(keys) else np.zeros(len(wanted), dtype=TILE_DTYPE)
    for column in _TILE_COLUMNS:
        percepts[column] = np.where(found, source[column], 0)
    occupant = np.where(found, source["occupant"], OUTSIDE).astype(np.int8)
    near = (np.abs(dx) <= 1) & (np.abs(dy) <= 1)
    bits = np.where(near, _BIT_TABLE[np.clip(dy + 1, 0, 2), np.clip(dx + 1, 0, 2)], -1)
    observer_bonds = cells["bonds"].astype(np.int64)[observer]
    bonded = (occupant == MINE) & (bits >= 0) & ((observer_bonds >> np.maximum(bits, 0)) & 1).astype(bool)
    occupant[bonded] = MINE_BONDED
    percepts["occupant"] = occupant
    if blanket:
        # Interior cells perceive their bonded neighbours, never resource layers,
        # even where a boundary window also covers the tile.
        inner = cells["role"][observer] == INTERIOR
        percepts["env_visible"][inner] = False
        percepts["food"][inner] = HIDDEN_VALUE
        percepts["temp"][inner] = 0
    return {**obs, "percepts": percepts[keep]}


def to_legacy_batch(obs: dict[str, Any]) -> dict[str, Any]:
    """Build the 0.1.x ``cells`` (n,5), ``neighborhood`` (n,45) and ``env``
    (n,12) arrays from the inner 3x3 window of an observation.

    Unperceived tiles in that window read as empty, which is all the old
    shapes can express; ``cell.sense`` distinguishes them. The original
    observation is kept under ``"observation"``.
    """
    cells, percepts = obs["cells"], obs["percepts"]
    n = len(cells)
    legacy_cells = np.empty((n, 5), dtype=np.int32)
    legacy_cells[:, 0] = cells["x"]
    legacy_cells[:, 1] = cells["y"]
    legacy_cells[:, 2] = cells["type"]
    legacy_cells[:, 3] = cells["state"]
    legacy_cells[:, 4] = cells["energy"]

    window = np.zeros((n, 9, 5), dtype=np.int32)
    food = np.zeros((n, 9), dtype=np.float32)
    temp = np.zeros(n, dtype=np.float32)
    dx, dy = percepts["dx"].astype(int), percepts["dy"].astype(int)
    inner = (np.abs(dx) <= 1) & (np.abs(dy) <= 1) & (percepts["occupant"] != OUTSIDE)
    rows = percepts[inner]
    observer = rows["observer"].astype(int)
    slot = (rows["dy"].astype(int) + 1) * 3 + rows["dx"].astype(int) + 1
    own = (rows["occupant"] == MINE) | (rows["occupant"] == MINE_BONDED)
    window[observer, slot, 0] = own
    window[observer, slot, 1] = rows["species"]
    window[observer, slot, 2] = rows["type"]
    window[observer, slot, 3] = rows["state"]
    window[observer, slot, 4] = rows["energy"]
    # Hidden resource layers read as 0, the closest the old shapes can express.
    food[observer, slot] = np.where(rows["env_visible"], rows["food"], 0)
    centre = slot == 4
    temp[observer[centre]] = np.where(rows["env_visible"], rows["temp"], 0)[centre]

    env = np.empty((n, 12), dtype=np.float32)
    env[:, 0] = temp
    env[:, 1] = food[:, 4]
    env[:, 2:11] = food
    env[:, 11] = cells["bonds"]
    return {
        "tick": obs["tick"],
        "cells": legacy_cells,
        "neighborhood": window.reshape(n, 45),
        "env": env,
        "constraints": obs["constraints"],
        "observation": obs,
    }


def intentions_to_v2(intents: np.ndarray, obs: dict[str, Any]) -> np.ndarray:
    """Map INTENTION_DTYPE rows to v2 rows [cell_id, action, dx, dy, param].

    Rows whose source is not one of the observed own cells are dropped.
    """
    cells = obs["cells"]
    ids = {(int(x), int(y)): int(cid) for cid, x, y in zip(cells["cell_id"], cells["x"], cells["y"])}
    out = []
    for row in np.asarray(intents):
        cid = ids.get((int(row["src_x"]), int(row["src_y"])))
        if cid is None:
            continue
        out.append([cid, int(row["action"]), int(row["tgt_x"]) - int(row["src_x"]),
                    int(row["tgt_y"]) - int(row["src_y"]), int(row["param"])])
    return np.asarray(out, dtype=np.int64).reshape(-1, V2_ROW_WIDTH)


def observation_to_world(obs: dict[str, Any], player_id: int, width: int, height: int) -> Any:
    """A WorldArrays holding only what this observation perceived.

    Used for the player's own map view: unperceived tiles stay empty. Other
    players' cells are attributed by species, which the server sets to the
    owning player's id.
    """
    from .models import WorldArrays

    world = WorldArrays(width, height)
    cells, tiles = obs["cells"], obs["tiles"]
    xs, ys = tiles["x"].astype(int), tiles["y"].astype(int)
    inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    tiles, xs, ys = tiles[inside], xs[inside], ys[inside]
    if len(tiles):
        occupant = tiles["occupant"]
        world.owner[ys, xs] = np.where(occupant == MINE, player_id,
                                       np.where(occupant == OTHER, tiles["species"],
                                                np.where(occupant == HIDDEN, -1, 0)))
        world.species[ys, xs] = tiles["species"]
        world.cell_type[ys, xs] = tiles["type"]
        world.state[ys, xs] = tiles["state"]
        world.energy[ys, xs] = tiles["energy"]
        world.env_food[ys, xs] = np.maximum(tiles["food"], 0)
        world.env_temp[ys, xs] = tiles["temp"]
        if "biomes" in obs and len(obs["biomes"]) == len(tiles):
            world.env_biome[ys, xs] = np.asarray(obs["biomes"], dtype=np.uint8)
        if "materials" in obs and len(obs["materials"]) == len(tiles):
            world.env_material[ys, xs] = np.asarray(obs["materials"], dtype=np.uint8)
        if "blocks" in obs and len(obs["blocks"]) == len(tiles):
            world.blocks[ys, xs] = np.asarray(obs["blocks"], dtype=np.uint8)
    if len(cells):
        cx, cy = cells["x"].astype(int), cells["y"].astype(int)
        world.bonds[cy, cx] = cells["bonds"]
        world.organism[cy, cx] = cells["entity"]
    return world


VISUAL_LIMITS = {"move": 80, "birth": 48, "death": 40, "eat": 32, "attack": 32}


def visual_events(previous_cells: Any, obs: dict[str, Any], player_id: int) -> list[list[int]]:
    """Animation events for the player's own cells, derived from two observations.

    Same format as the server's legacy visual events: [kind, x, y, tx, ty,
    owner, cell_type]. Only the player's own information is used.
    """
    from .models import Action

    now = {int(c["cell_id"]): (int(c["x"]), int(c["y"]), int(c["type"])) for c in obs["cells"]}
    before = {} if previous_cells is None else {
        int(c["cell_id"]): (int(c["x"]), int(c["y"])) for c in previous_cells}
    out, counts = [], {}

    def add(kind, x, y, tx, ty, cell_type=0):
        if counts.get(kind, 0) < VISUAL_LIMITS[kind]:
            counts[kind] = counts.get(kind, 0) + 1
            out.append([kind, x, y, tx, ty, int(player_id), cell_type])

    for cid, (x, y, cell_type) in now.items():
        if cid in before and before[cid] != (x, y):
            add("move", *before[cid], x, y, cell_type)
    for event in obs.get("events", ()):
        kind, cid, other = int(event["kind"]), int(event["cell_id"]), int(event["other"])
        if kind == EVENT_BORN and cid in now:
            parent = now.get(other) or before.get(other)
            if parent is not None:
                add("birth", parent[0], parent[1], now[cid][0], now[cid][1])
        elif kind == EVENT_DIED and cid in before:
            add("death", *before[cid], *before[cid])
        elif kind == EVENT_RESULT and int(event["code"]) == R_OK and cid in now:
            x, y = now[cid][:2]
            if int(event["action"]) == int(Action.EAT):
                add("eat", x, y, x, y)
            elif int(event["action"]) == int(Action.ATTACK):
                add("attack", x, y, x, y)
    return out


KNOWN_FIELDS = ("owner", "species", "cell_type", "state", "energy", "bonds", "organism")


def remember(known: Any, seen: np.ndarray, view: Any, obs: dict[str, Any], player_id: int) -> None:
    """Fold the current view into the player's known map, in place.

    ``seen`` is 0 for never seen, 1 for perceived now and 2 for remembered.
    Resource layers are only updated where they were visible. The player's own
    cells are always known exactly, so remembered copies of them are dropped.
    """
    tiles = obs["tiles"]
    xs, ys = tiles["x"].astype(int), tiles["y"].astype(int)
    inside = (xs >= 0) & (xs < known.w) & (ys >= 0) & (ys < known.h)
    xs, ys, visible = xs[inside], ys[inside], tiles["env_visible"][inside]
    seen[seen == 1] = 2
    seen[ys, xs] = 1
    for field in KNOWN_FIELDS:
        getattr(known, field)[ys, xs] = getattr(view, field)[ys, xs]
    known.env_food[ys[visible], xs[visible]] = view.env_food[ys[visible], xs[visible]]
    known.env_temp[ys[visible], xs[visible]] = view.env_temp[ys[visible], xs[visible]]
    known.env_biome[ys[visible], xs[visible]] = view.env_biome[ys[visible], xs[visible]]
    known.env_material[ys[visible], xs[visible]] = view.env_material[ys[visible], xs[visible]]
    known.blocks[ys[visible], xs[visible]] = view.blocks[ys[visible], xs[visible]]
    stale = (seen == 2) & (known.owner == player_id)
    for field in KNOWN_FIELDS:
        getattr(known, field)[stale] = 0


def _table(array: np.ndarray) -> dict[str, Any]:
    return {"columns": list(array.dtype.names), "rows": [list(row) for row in array.tolist()]}


def observation_to_json(obs: dict[str, Any]) -> dict[str, Any]:
    """Plain-JSON form for HTTP and stdio controllers."""
    return {
        "version": obs["version"],
        "tick": int(obs["tick"]),
        "manifest": obs["manifest"],
        "revision": obs.get("revision", 0),
        "world_run": obs.get("world_run", ""),
        "cells": _table(obs["cells"]),
        "tiles": _table(obs["tiles"]),
        **({"biomes": np.asarray(obs["biomes"], dtype=np.uint8).tolist()} if "biomes" in obs else {}),
        **({"materials": np.asarray(obs["materials"], dtype=np.uint8).tolist()} if "materials" in obs else {}),
        **({"blocks": np.asarray(obs["blocks"], dtype=np.uint8).tolist()} if "blocks" in obs else {}),
        "events": _table(np.asarray(obs.get("events", np.empty(0, dtype=EVENT_DTYPE)), dtype=EVENT_DTYPE)),
    }
