"""Pure vectorized helpers shared by server and client preview (spec 6).

Neighborhood expansion must be vectorized: with ~10k cells in a 256x256
world, a Python loop over cells costs seconds; slicing is milliseconds.
"""
import numpy as np


def expand_neighborhood(arrays, xs, ys, player_id, radius=1):
    """Moore neighborhood expansion for n cells.

    Each cell's (2r+1)x(2r+1) neighborhood is flattened row-major
    (top-left first, center in the middle). Each neighbor is a 5-tuple
    (owner_is_self, species, cell_type, state, energy); out of bounds
    is zero. Returns an (n, (2r+1)^2 * 5) int32 array.
    """
    r = radius
    n = len(xs)
    size = 2 * r + 1
    if n == 0:
        return np.empty((0, size * size * 5), dtype=np.int32)

    def padded(field):
        return np.pad(field, r, mode="constant", constant_values=0)

    owner_p = padded(arrays.owner)
    species_p = padded(arrays.species)
    ctype_p = padded(arrays.cell_type)
    state_p = padded(arrays.state)
    energy_p = padded(arrays.energy)

    xs = np.asarray(xs)
    ys = np.asarray(ys)
    cols = []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            yy = ys + dy + r
            xx = xs + dx + r
            own = (owner_p[yy, xx] == player_id).astype(np.int32)
            cols.append(own)
            cols.append(species_p[yy, xx].astype(np.int32))
            cols.append(ctype_p[yy, xx].astype(np.int32))
            cols.append(state_p[yy, xx].astype(np.int32))
            cols.append(energy_p[yy, xx].astype(np.int32))
    return np.stack(cols, axis=1).astype(np.int32)


def compute_delta(prev, cur):
    """Diff two WorldArrays. Returns an (m, 8) int32 array:
    [x, y, owner, species, cell_type, state, energy, flags].
    flags marks which fields changed (see shared.models FLAG_*)."""
    changed = (
        (prev.owner != cur.owner)
        | (prev.species != cur.species)
        | (prev.cell_type != cur.cell_type)
        | (prev.state != cur.state)
        | (prev.energy != cur.energy)
    )
    ys, xs = np.where(changed)
    if len(xs) == 0:
        return np.empty((0, 8), dtype=np.int32)
    flags = np.zeros(len(xs), dtype=np.int32)
    flags |= np.where(prev.owner[ys, xs] != cur.owner[ys, xs], 1, 0)
    flags |= np.where(prev.species[ys, xs] != cur.species[ys, xs], 2, 0)
    flags |= np.where(prev.cell_type[ys, xs] != cur.cell_type[ys, xs], 4, 0)
    flags |= np.where(prev.state[ys, xs] != cur.state[ys, xs], 8, 0)
    flags |= np.where(prev.energy[ys, xs] != cur.energy[ys, xs], 16, 0)
    out = np.empty((len(xs), 8), dtype=np.int32)
    out[:, 0] = xs
    out[:, 1] = ys
    out[:, 2] = cur.owner[ys, xs]
    out[:, 3] = cur.species[ys, xs]
    out[:, 4] = cur.cell_type[ys, xs]
    out[:, 5] = cur.state[ys, xs]
    out[:, 6] = cur.energy[ys, xs]
    out[:, 7] = flags
    return out


def apply_delta(arrays, changes):
    """Apply a compute_delta() result to a WorldArrays in place."""
    if len(changes) == 0:
        return
    xs = changes[:, 0]
    ys = changes[:, 1]
    flags = changes[:, 7]
    arrays.owner[ys, xs] = np.where(flags & 1, changes[:, 2], arrays.owner[ys, xs])
    arrays.species[ys, xs] = np.where(flags & 2, changes[:, 3], arrays.species[ys, xs])
    arrays.cell_type[ys, xs] = np.where(flags & 4, changes[:, 4], arrays.cell_type[ys, xs])
    arrays.state[ys, xs] = np.where(flags & 8, changes[:, 5], arrays.state[ys, xs])
    arrays.energy[ys, xs] = np.where(flags & 16, changes[:, 6], arrays.energy[ys, xs])
