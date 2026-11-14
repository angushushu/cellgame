"""Shared data model for the cellular species game (spec section 2).

Kept exactly as specified: world size, chunk size, Action enum values,
INTENTION_DTYPE fields, SenseBatch / WorldDelta shapes.
"""
from enum import IntEnum

import numpy as np

# World size (demo fixed, configurable later)
WORLD_W, WORLD_H = 256, 256
CHUNK_W, CHUNK_H = 32, 32
NUM_CHUNKS_X = WORLD_W // CHUNK_W   # 8
NUM_CHUNKS_Y = WORLD_H // CHUNK_H   # 8

# Tick timing (spec section 3.2)
TICK_MS = 3000
DEADLINE_MS = 2500


class Action(IntEnum):
    MOVE = 0       # move to target
    ATTACK = 1     # attack target cell
    REPRODUCE = 2  # spawn a new cell on an empty target cell
    EAT = 3        # take resources from target cell
    CHANGE = 4     # change own cell_type / state
    DIE = 5        # die voluntarily
    SET_STATE = 6  # update own public per-cell state
    BOND = 7       # connect to a friendly neighbor
    UNBOND = 8     # disconnect from a connected neighbor
    TRANSFER = 9   # give energy to a connected neighbor
    MOVE_GROUP = 10  # atomically translate a connected component
    SENSE = 11       # pay energy to perceive a larger radius next tick (param = radius)


MAX_ACTION = max(int(a) for a in Action)


# One intention per cell per tick, shipped as a NumPy structured array.
INTENTION_DTYPE = np.dtype([
    ("src_x",    np.int16),
    ("src_y",    np.int16),
    ("tgt_x",    np.int16),   # CHANGE / DIE: equals src
    ("tgt_y",    np.int16),
    ("action",   np.int8),
    ("strength", np.int16),   # energy / attack power, used by the arbiter
    ("param",    np.int32),   # extra param, e.g. CHANGE's new cell_type
])

# Energy costs per action (spec section 4.4)
ACTION_COST = {
    Action.MOVE: 2,
    Action.ATTACK: 3,
    Action.REPRODUCE: 8,
    Action.EAT: 0,
    Action.CHANGE: 1,
    Action.DIE: 0,
    Action.SET_STATE: 0,
    Action.BOND: 0,
    Action.UNBOND: 0,
    Action.TRANSFER: 0,
    Action.MOVE_GROUP: 0,
    Action.SENSE: 0,  # charged per radius by the world's action rules
}
REPRODUCE_MIN_ENERGY = 10   # src must have at least this much to reproduce
REPRODUCE_CHILD_ENERGY = 5  # energy of the newborn cell
EAT_MAX_GAIN = 5            # max energy gained per EAT
ARMOR_TYPE = 1
ARMOR_DEFENSE_BONUS = 3
ARMOR_MOVE_SURCHARGE = 1

# WorldDelta change flags (bitmask, spec section 2.4)
FLAG_OWNER = 1
FLAG_SPECIES = 2
FLAG_CELL_TYPE = 4
FLAG_STATE = 8
FLAG_ENERGY = 16

WORLD_FIELDS = ("owner", "species", "cell_type", "state", "energy",
                "env_temp", "env_food", "env_biome", "env_material", "blocks", "bonds", "organism")
# Server-private fields: copied with the world but not part of snapshots,
# deltas or recordings. cell_id is a stable per-cell identity (0 = none).
INTERNAL_FIELDS = ("cell_id",)
# Fields that travel with a cell when it moves.
CELL_FIELDS = ("owner", "species", "cell_type", "state", "energy", "organism", "cell_id")


class WorldArrays:
    """One independent NumPy array per field (structured arrays are
    bad for vectorization). owner 0 == environment / empty."""

    def __init__(self, w=WORLD_W, h=WORLD_H):
        self.w, self.h = w, h
        self.owner = np.zeros((h, w), dtype=np.int32)
        self.species = np.zeros((h, w), dtype=np.int16)
        self.cell_type = np.zeros((h, w), dtype=np.int16)
        self.state = np.zeros((h, w), dtype=np.uint32)
        self.energy = np.zeros((h, w), dtype=np.int16)
        # Bit i corresponds to the ith Moore neighbor, in row-major order.
        self.bonds = np.zeros((h, w), dtype=np.uint8)
        self.organism = np.zeros((h, w), dtype=np.int32)
        self.cell_id = np.zeros((h, w), dtype=np.uint32)
        self.env_temp = np.full((h, w), 20.0, dtype=np.float32)
        self.env_food = np.zeros((h, w), dtype=np.float32)
        self.env_biome = np.zeros((h, w), dtype=np.uint8)
        self.env_material = np.zeros((h, w), dtype=np.uint8)
        self.blocks = np.zeros((h, w), dtype=np.uint8)

    def copy(self):
        other = WorldArrays(self.w, self.h)
        for f in WORLD_FIELDS + INTERNAL_FIELDS:
            setattr(other, f, getattr(self, f).copy())
        return other

    def to_dict(self):
        return {f: getattr(self, f) for f in WORLD_FIELDS}

    @classmethod
    def from_dict(cls, d, w=WORLD_W, h=WORLD_H):
        arr = cls(w, h)
        for f in WORLD_FIELDS:
            if f in d:
                setattr(arr, f, np.array(d[f], copy=True))
        return arr
