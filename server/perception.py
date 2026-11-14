"""Server-side perception: build each player's observation (format v2).

Only what the world's perception model and visibility rules allow is put into
the observation; players in non-legacy worlds receive nothing else about the map.

The wire form lists each perceived tile once (the union over the player's
cells). Which offsets each cell perceives follows from its row in ``cells``
(position, role, sense_radius, bonds) and the manifest, so the client rebuilds
per-cell percepts exactly (``shared.observation.expand_observation``). Within
one player the knowledge is pooled anyway (spec §11.1), so this reveals nothing
extra, and the message size is bounded by the world area.

Perception by model:
- radius: every cell sees its window (``radius``, or a larger ``sense`` radius).
- blanket: boundary cells see their window (``external_radius`` or ``sense``);
  interior cells see only themselves and their bonded neighbors, and not the
  resource layers of those tiles.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from cellgame.shared.manifest import base_radius, manifest_hash, window_offsets
from cellgame.shared.observation import (
    CELL_DTYPE, EMPTY, HIDDEN, HIDDEN_VALUE, INTERIOR, MINE, OTHER, ROLE_NONE, TILE_DTYPE,
)

_DIRECTIONS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0)]
_ATTRIBUTE_SOURCES = (("species", "species"), ("type", "cell_type"), ("state", "state"),
                      ("energy", "energy"))


def _cell_radii(world: Any, ids: np.ndarray, base: int, inner: np.ndarray) -> np.ndarray:
    boost = world.sense_boost
    radii = np.array([max(base, boost.get(int(cid), 0)) for cid in ids], dtype=np.int64)
    radii[inner] = 0
    return radii


def _cells_table(arrays: Any, xs: np.ndarray, ys: np.ndarray, roles: np.ndarray,
                 radii: np.ndarray) -> np.ndarray:
    cells = np.zeros(len(xs), dtype=CELL_DTYPE)
    cells["cell_id"] = arrays.cell_id[ys, xs]
    cells["x"], cells["y"] = xs, ys
    cells["type"] = arrays.cell_type[ys, xs]
    cells["state"] = arrays.state[ys, xs]
    cells["energy"] = arrays.energy[ys, xs]
    cells["bonds"] = arrays.bonds[ys, xs]
    cells["entity"] = arrays.organism[ys, xs]
    cells["role"] = roles
    cells["sense_radius"] = radii
    return cells


def _window_keys(arrays: Any, xs, ys, radii, metric):
    """Sorted flat keys of tiles covered by any non-interior cell's window.

    Built by OR-ing shifted copies of a world-sized mask, so memory stays
    proportional to the world area however many cells use a large radius.
    """
    w, h = arrays.w, arrays.h
    covered = np.zeros((h, w), dtype=bool)
    for radius in np.unique(radii[radii > 0]):
        sources = np.zeros((h, w), dtype=bool)
        pick = radii == radius
        sources[ys[pick], xs[pick]] = True
        for dx, dy in window_offsets(int(radius), metric):
            covered[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] |= \
                sources[max(-dy, 0):h - max(dy, 0), max(-dx, 0):w - max(dx, 0)]
    return np.flatnonzero(covered).astype(np.int64)


def _interior_keys(arrays: Any, xs, ys):
    """Interior cells perceive their own tile and their bonded neighbors."""
    keys = [ys * arrays.w + xs]
    bonds = arrays.bonds[ys, xs]
    for bit, (dx, dy) in enumerate(_DIRECTIONS):
        has = (bonds & (1 << bit)) != 0
        keys.append((ys[has] + dy) * arrays.w + xs[has] + dx)
    return np.concatenate(keys)


def _apply_visibility(tiles: np.ndarray, roles_grid, visibility: dict[str, str]) -> None:
    other = tiles["occupant"] == OTHER
    if not other.any():
        return
    interior = np.zeros(len(tiles), dtype=bool)
    if roles_grid is not None:
        interior = other & (roles_grid[tiles["y"], tiles["x"]] == INTERIOR)
    for column in ("state", "energy", "type"):
        level = visibility[column]
        hide = other if level == "none" else (interior if level == "boundary_only" else None)
        if hide is not None:
            tiles[column][hide] = HIDDEN_VALUE
    if visibility["others_interior"] == "hidden":
        tiles["occupant"][interior] = HIDDEN
        for column in ("species", "type", "state", "energy"):
            tiles[column][interior] = HIDDEN_VALUE


def _tiles(world: Any, player_id: int, window_keys, interior_keys, visibility, roles_grid):
    arrays = world.arrays
    keys = np.union1d(window_keys, interior_keys)
    ty, tx = np.divmod(keys, arrays.w)
    tiles = np.zeros(len(keys), dtype=TILE_DTYPE)
    tiles["x"], tiles["y"] = tx, ty
    owner = arrays.owner[ty, tx]
    tiles["occupant"] = np.where(owner == player_id, MINE, np.where(owner != 0, OTHER, EMPTY))
    for column, field in _ATTRIBUTE_SOURCES:
        tiles[column] = getattr(arrays, field)[ty, tx]
    visible = np.isin(keys, window_keys)
    tiles["env_visible"] = visible
    tiles["food"] = np.where(visible, arrays.env_food[ty, tx], HIDDEN_VALUE)
    tiles["temp"] = np.where(visible, arrays.env_temp[ty, tx], 0)
    _apply_visibility(tiles, roles_grid, visibility)
    return tiles


def gather_observation(world: Any, player_id: int, manifest: dict[str, Any],
                       world_run: str = "") -> dict[str, Any]:
    """Wire-form observation v2 for one player."""
    arrays = world.arrays
    ys, xs = np.where(arrays.owner == player_id)
    ys, xs = ys.astype(np.int64), xs.astype(np.int64)
    blanket = manifest["perception"]["model"] == "blanket"
    roles_grid = world.roles() if world.rules.needs_roles else None
    # Roles are reported whenever rules depend on them; only blanket worlds
    # change what an interior cell perceives.
    roles = roles_grid[ys, xs] if roles_grid is not None else np.full(len(xs), ROLE_NONE, dtype=np.int8)
    inner = blanket & (roles == INTERIOR)
    radii = _cell_radii(world, arrays.cell_id[ys, xs], base_radius(manifest), inner)
    metric = manifest["perception"].get("metric", "chebyshev")
    tiles = _tiles(world, player_id, _window_keys(arrays, xs, ys, radii, metric),
                   _interior_keys(arrays, xs[inner], ys[inner]), manifest["visibility"], roles_grid)
    return {
        "version": 2,
        "tick": world.tick,
        "manifest": manifest_hash(manifest),
        "revision": 0,
        "world_run": world_run,
        "cells": _cells_table(arrays, xs, ys, roles, radii),
        "tiles": tiles,
        "biomes": np.where(tiles["env_visible"], arrays.env_biome[tiles["y"], tiles["x"]], 0).astype(np.uint8),
        "materials": np.where(tiles["env_visible"], arrays.env_material[tiles["y"], tiles["x"]], 0).astype(np.uint8),
        "events": world.events_for(player_id),
        "constraints": dict(world.constraints),
    }
