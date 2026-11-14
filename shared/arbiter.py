"""Validate and arbitrate local player intentions against a pre-tick world.

Only owned source cells can act. Move, attack and reproduce target a Moore
neighbor; eat, change, set state, sense and die target the source. Strength is
computed from authoritative energy. Contested targets are resolved
deterministically; self-actions and incoming attacks are independent
interactions. WorldState applies the accepted actions in its documented order.

The world's compiled rules (``world.rules``) may disable actions or restrict
them to cell roles. Pass ``report={}`` to receive a reason code for every
input row (``report["reasons"]``) and the input index of every returned row
(``report["winners"]``).
"""
import numpy as np

from .combat import defense as combat_defense
from .manifest import DEFAULT_RULES
from .models import ARMOR_TYPE, INTENTION_DTYPE, MAX_ACTION, Action
from .observation import (
    R_BLOCKED, R_CONTESTED, R_DISABLED, R_DUPLICATE, R_INVALID, R_NO_ENERGY, R_OK, R_ROLE,
)
from .world_parameters import DEFAULTS, action_cost

SELF_ACTIONS = (Action.EAT, Action.CHANGE, Action.DIE, Action.SET_STATE, Action.SENSE)
LINK_ACTIONS = (Action.BOND, Action.UNBOND, Action.TRANSFER)
DIRECTIONS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0)]


def _det_hash(*ints):
    """Deterministic 64-bit mix (splitmix-style). Never uses random."""
    h = 0x9E3779B97F4A7C15
    for v in ints:
        h ^= (int(v) + 0x9E3779B97F4A7C15 + ((h << 6) & 0xFFFFFFFFFFFFFFFF) + (h >> 2))
        h &= 0xFFFFFFFFFFFFFFFF
        h ^= h >> 33
        h = (h * 0xFF51AFD7ED558CCD) & 0xFFFFFFFFFFFFFFFF
        h ^= h >> 33
    return h


class _Rows:
    """The surviving intention rows, filtered stage by stage."""

    def __init__(self, arr, player_ids, reasons):
        self.arr = arr
        self.pid = player_ids
        self.orig = np.arange(len(arr))
        self.reasons = reasons
        self._unpack()

    def _unpack(self):
        a = self.arr
        self.sx, self.sy = a["src_x"].astype(int), a["src_y"].astype(int)
        self.tx, self.ty = a["tgt_x"].astype(int), a["tgt_y"].astype(int)
        self.act = a["action"].astype(int)

    def keep(self, ok, code):
        """Keep rows where ok; record code for the rest. Returns False if empty."""
        self.reasons[self.orig[~ok]] = code
        self.arr, self.pid, self.orig = self.arr[ok], self.pid[ok], self.orig[ok]
        self._unpack()
        return len(self.arr) > 0

    def reorder(self, order):
        self.arr, self.pid, self.orig = self.arr[order], self.pid[order], self.orig[order]
        self._unpack()

    def is_(self, *actions):
        return np.isin(self.act, [int(a) for a in actions])


def _costs(rows, arrays, constraints, rules):
    cost = np.zeros(len(rows.arr), dtype=np.int64)
    for action in Action:
        cost[rows.act == int(action)] = action_cost(action, constraints)
    sense = rows.act == int(Action.SENSE)
    cost[sense] = rows.arr["param"][sense].astype(np.int64) * rules.sense_cost_per_radius
    armored_move = (rows.act == int(Action.MOVE)) & (arrays.cell_type[rows.sy, rows.sx] == ARMOR_TYPE)
    cost += armored_move * constraints.get("armor_move_surcharge", DEFAULTS["armor_move_surcharge"])
    target_block = arrays.blocks[rows.ty, rows.tx] != 0
    block_attack = (rows.act == int(Action.ATTACK)) & (arrays.owner[rows.ty, rows.tx] == 0) & target_block
    cost[block_attack] = constraints.get("block_attack_cost", DEFAULTS["block_attack_cost"])
    push = (rows.act == int(Action.MOVE)) & target_block
    cost += push * constraints.get("push_cost", DEFAULTS["push_cost"])
    return cost


def _params_ok(rows, rules):
    param = rows.arr["param"]
    ok = np.ones(len(rows.arr), dtype=bool)
    # cell_type is a signed 16-bit world field; reject unrepresentable
    # values before NumPy assignment rather than letting one client crash it.
    ok &= ~rows.is_(Action.CHANGE) | ((param >= 0) & (param <= 32767))
    ok &= ~rows.is_(Action.SET_STATE) | (param >= 0)
    ok &= ~rows.is_(Action.REPRODUCE) | ((param >= 0) & (param <= 1))
    ok &= ~rows.is_(Action.TRANSFER) | ((param >= 1) & (param <= 100))
    ok &= ~rows.is_(Action.SENSE) | ((param >= 1) & (param <= rules.sense_max_radius))
    return ok


def _preconditions_ok(rows, arrays, constraints, rules):
    tgt_owner = arrays.owner[rows.ty, rows.tx]
    defense = combat_defense(arrays.energy, arrays.cell_type, arrays.bonds, rows.tx, rows.ty,
                             constraints, rules.bonded_support_percent)
    strength = rows.arr["strength"].astype(int)
    src_bonds = arrays.bonds[rows.sy, rows.sx]
    ok = np.ones(len(rows.arr), dtype=bool)
    is_move, is_attack = rows.is_(Action.MOVE), rows.is_(Action.ATTACK)
    is_group, is_repro, is_eat = rows.is_(Action.MOVE_GROUP), rows.is_(Action.REPRODUCE), rows.is_(Action.EAT)
    is_link, is_transfer = rows.is_(*LINK_ACTIONS), rows.is_(Action.TRANSFER)
    # Connected cells remain in place until their links are removed.
    ok[is_move] &= (tgt_owner[is_move] == 0) & (src_bonds[is_move] == 0)
    ok[is_group] &= (src_bonds[is_group] != 0) & ((tgt_owner[is_group] == 0) | (tgt_owner[is_group] == rows.pid[is_group]))
    ok[is_link] &= tgt_owner[is_link] == rows.pid[is_link]
    # Transfers require a pre-existing connection, not just a friendly target.
    connected = np.zeros(len(rows.arr), dtype=bool)
    for bit, (dx, dy) in enumerate(DIRECTIONS):
        connected |= (rows.tx - rows.sx == dx) & (rows.ty - rows.sy == dy) & ((src_bonds & (1 << bit)) != 0)
    ok[is_transfer] &= connected[is_transfer]
    block_target = (tgt_owner == 0) & (arrays.blocks[rows.ty, rows.tx] != 0)
    enemy_target = (tgt_owner != 0) & (tgt_owner != rows.pid) & (strength > defense)
    ok[is_attack] &= (block_target | enemy_target)[is_attack]
    ok[is_repro] &= (tgt_owner[is_repro] == 0) & (arrays.blocks[rows.ty[is_repro], rows.tx[is_repro]] == 0)
    ok[is_eat] &= arrays.env_food[rows.ty[is_eat], rows.tx[is_eat]] > 0
    return ok


def _winners(rows, arrays, tick):
    w, h = arrays.w, arrays.h
    tgt_owner = arrays.owner[rows.ty, rows.tx]
    strength = rows.arr["strength"].astype(int)
    # target class: 0 = own cell, 1 = empty, 2 = other player's cell
    tgt_class = np.where(tgt_owner == rows.pid, 0, np.where(tgt_owner == 0, 1, 2))
    # An attack and a self-action are distinct interactions. In particular,
    # eating must not grant immunity to an incoming attack.
    key = (rows.tx.astype(np.int64) * h + rows.ty) * 2 + rows.is_(Action.ATTACK).astype(np.int64)
    # Neighbor interactions do not reserve the target cell or block its own action.
    independent = rows.is_(*LINK_ACTIONS, Action.MOVE_GROUP)
    key[independent] = 2 * w * h + rows.sx[independent].astype(np.int64) * h + rows.sy[independent]
    order = np.lexsort((
        np.array([_det_hash(tick, int(a), int(b), int(c), int(d))
                  for a, b, c, d in zip(rows.tx, rows.ty, rows.sx, rows.sy)], dtype=np.uint64),
        -strength,          # higher strength first
        tgt_class,          # own > empty > other
        key,                # group
    ))
    _, first = np.unique(key[order], return_index=True)
    winners = np.zeros(len(rows.arr), dtype=bool)
    winners[order[first]] = True
    return winners, key


def arbitrate(intentions, world, constraints, tick=0, player_ids=None, report=None):
    empty = np.empty((0,), dtype=INTENTION_DTYPE)
    arr = np.asarray(intentions if intentions is not None else empty, dtype=INTENTION_DTYPE)
    n = len(arr)
    reasons = np.full(n, R_OK, dtype=np.int8)
    if report is not None:
        report["reasons"], report["winners"] = reasons, np.empty(0, dtype=np.int64)
    if n == 0:
        return empty

    # `world` may be a WorldState or a bare WorldArrays.
    arrays = getattr(world, "arrays", world)
    rules = getattr(world, "rules", DEFAULT_RULES)
    w, h = arrays.w, arrays.h
    if player_ids is None or len(player_ids) != n:
        player_ids = np.zeros(n, dtype=np.int32)
    rows = _Rows(arr, np.asarray(player_ids, dtype=np.int32), reasons)

    # 1. bounds, then ownership and locality (the client is untrusted).
    if not rows.keep((rows.sx >= 0) & (rows.sx < w) & (rows.sy >= 0) & (rows.sy < h)
                     & (rows.tx >= 0) & (rows.tx < w) & (rows.ty >= 0) & (rows.ty < h)
                     & (rows.act >= 0) & (rows.act <= MAX_ACTION), R_INVALID):
        return empty
    distance = np.maximum(np.abs(rows.tx - rows.sx), np.abs(rows.ty - rows.sy))
    local = np.where(rows.is_(*SELF_ACTIONS), distance == 0, distance == 1)
    if not rows.keep((rows.pid > 0) & (arrays.owner[rows.sy, rows.sx] == rows.pid) & local, R_INVALID):
        return empty

    # 2. world rules: disabled actions and role restrictions.
    if not rows.keep(np.isin(rows.act, list(rules.enabled)), R_DISABLED):
        return empty
    if rules.needs_roles and hasattr(world, "roles"):
        role = world.roles()[rows.sy, rows.sx].astype(int)
        mask = np.asarray(rules.actor_role_mask, dtype=np.int64)[rows.act]
        if not rows.keep(((mask >> role) & 1).astype(bool), R_ROLE):
            return empty
    if not rows.keep(_params_ok(rows, rules), R_INVALID):
        return empty

    # 3. energy: attack power and contest priority come from authoritative energy.
    rows.arr = rows.arr.copy()
    rows.arr["strength"] = arrays.energy[rows.sy, rows.sx]
    energy = arrays.energy[rows.sy, rows.sx]
    ok = energy >= _costs(rows, arrays, constraints, rules)
    ok &= ~(rows.is_(Action.REPRODUCE) & (energy < constraints.get("reproduce_min_energy", DEFAULTS["reproduce_min_energy"])))
    if not rows.keep(ok, R_NO_ENERGY):
        return empty

    # 4. one intention per source cell: keep the first.
    _, first = np.unique(rows.sx.astype(np.int64) * h + rows.sy, return_index=True)
    ok = np.zeros(len(rows.arr), dtype=bool)
    ok[first] = True
    if not rows.keep(ok, R_DUPLICATE):
        return empty

    # 5. temporary world constraints, then preconditions on the pre-tick world.
    if not constraints.get("reproduce_enabled", True):
        if not rows.keep(~rows.is_(Action.REPRODUCE), R_DISABLED):
            return empty
    if not rows.keep(_preconditions_ok(rows, arrays, constraints, rules), R_BLOCKED):
        return empty

    # 6. group by target, one winner per group. Winners are returned in group
    # key order; application order matters (a move into a tile succeeds only
    # after its occupant has left), so this order is part of the rules.
    winners, key = _winners(rows, arrays, tick)
    if not rows.keep(winners, R_CONTESTED):
        return empty
    rows.reorder(np.argsort(key[winners], kind="stable"))
    if report is not None:
        report["winners"] = rows.orig.copy()
    return np.ascontiguousarray(rows.arr)
