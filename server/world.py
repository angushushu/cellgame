"""WorldState: the authoritative world (spec section 4.3).

Owns the NumPy arrays, applies arbitrated intentions, runs the ecology
step (energy <= 0 dies), spawns starter cells on join, kills a whole
player on disconnect, and packs per-player sense batches.
"""
import numpy as np

from cellgame.shared.models import (
    ACTION_COST,
    ARMOR_TYPE,
    ARMOR_DEFENSE_BONUS,
    ARMOR_MOVE_SURCHARGE,
    CELL_FIELDS,
    EAT_MAX_GAIN,
    INTENTION_DTYPE,
    MAX_ACTION,
    REPRODUCE_CHILD_ENERGY,
    REPRODUCE_MIN_ENERGY,
    Action,
    WorldArrays,
)
from cellgame.shared.combat import defense as combat_defense
from cellgame.shared.manifest import DEFAULT_RULES, compile_rules, default_manifest
from cellgame.shared.observation import (
    BOUNDARY, DIED_ATTACK, DIED_SELF, DIED_STARVED, EVENT_BORN, EVENT_DIED, EVENT_DTYPE,
    EVENT_RESULT, INTERIOR,
)
from cellgame.shared.tick_utils import compute_delta, expand_neighborhood
from cellgame.shared.world_parameters import DEFAULTS, action_cost
from .organisms import Organisms


VISUAL_LIMITS = {"move": 80, "birth": 48, "death": 40, "eat": 32, "attack": 32, "share": 24}

DIRECTIONS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0)]


class WorldState:
    def __init__(self, w=256, h=256, seed=0):
        self.w, self.h = w, h
        self.arrays = WorldArrays(w, h)
        self.tick = 0
        self.version = 0
        self.constraints = {"reproduce_enabled": True, "world_w": w, "world_h": h,
                            "metabolism_interval": 10, "bond_actions": True, "group_move_max_cells": 256, "armor_defense_bonus": ARMOR_DEFENSE_BONUS,
                            "armor_move_surcharge": ARMOR_MOVE_SURCHARGE}
        self.constraints.update(DEFAULTS)
        self.organisms = Organisms()
        self.next_cell_id = 1
        self.manifest = default_manifest()
        self.rules = DEFAULT_RULES
        self._roles_cache = (None, None)
        self.sense_boost = {}       # cell_id -> radius for the next observation
        self.player_events = {}     # player_id -> [(kind, cell_id, action, code, other)]
        self.last_applied = np.zeros(0, dtype=bool)
        self._last_organism_metadata = {}
        self.rng = np.random.default_rng(seed)
        self._visual_events = []
        self._visual_counts = {}
        self._last_sent = self.arrays.copy()
        rng = np.random.default_rng(seed)
        # Smooth deterministic ecological regions, fixed for this world run.
        # 1 meadow, 2 forest, 3 desert, 4 tundra.
        gy = np.linspace(0, h - 1, max(2, h // 32 + 2))
        gx = np.linspace(0, w - 1, max(2, w // 32 + 2))
        coarse = rng.random((len(gy), len(gx)))
        horizontal = np.array([np.interp(np.arange(w), gx, row) for row in coarse])
        field = np.array([np.interp(np.arange(h), gy, horizontal[:, x]) for x in range(w)]).T
        self.arrays.env_biome = np.digitize(field, [0.35, 0.50, 0.65]).astype(np.uint8) + 1
        probabilities = np.array([0.08, 0.09, 0.14, 0.035, 0.055])
        mask = rng.random((h, w)) < probabilities[self.arrays.env_biome]
        self.arrays.env_food[mask] = rng.uniform(5, 20, size=int(mask.sum())).astype(np.float32)
        temperatures = np.array([20, 20, 23, 30, 8], dtype=np.float32)
        self.arrays.env_temp = (temperatures[self.arrays.env_biome] + rng.normal(0, 0.5, (h, w))).astype(np.float32)
        # 0 regular ground, 1 berry habitat, 2 lava, 3 spikes.
        roll = rng.random((h, w))
        self.arrays.env_material = np.where(roll < .006, 2, np.where(roll < .014, 3,
                                          np.where((self.arrays.env_biome == 2) & (roll < .10), 1, 0))).astype(np.uint8)
        self.arrays.env_food[self.arrays.env_material >= 2] = 0

    def _visual(self, kind, x, y, tx, ty, owner, cell_type=0):
        # Visual effects are best-effort and bounded; they never affect rules.
        count = self._visual_counts.get(kind, 0)
        if count < VISUAL_LIMITS.get(kind, 0):
            self._visual_events.append([kind, int(x), int(y), int(tx), int(ty), int(owner), int(cell_type)])
            self._visual_counts[kind] = count + 1

    def configure(self, manifest):
        """Adopt a validated manifest's rules (perception, roles, actions)."""
        self.manifest = manifest
        self.rules = compile_rules(manifest)

    # -- roles -----------------------------------------------------------------
    def component_labels(self):
        """(h, w) int64 labels of bonded components; -1 for empty tiles."""
        A = self.arrays
        ys, xs = np.where(A.owner != 0)
        flat = np.full(self.w * self.h, -1, dtype=np.int64)
        index = ys.astype(np.int64) * self.w + xs
        flat[index] = np.arange(len(index))
        u, v = [], []
        for bit, (dx, dy) in enumerate(DIRECTIONS):
            if (dy, dx) <= (0, 0):
                continue  # each bond is stored on both ends; scan one direction
            has = (A.bonds[ys, xs] & (1 << bit)) != 0
            nx, ny = xs[has] + dx, ys[has] + dy
            inside = (nx >= 0) & (nx < self.w) & (ny >= 0) & (ny < self.h)
            target = flat[ny[inside].astype(np.int64) * self.w + nx[inside]]
            ok = target >= 0
            u.append(np.arange(len(index))[has][inside][ok])
            v.append(target[ok])
        parent = np.arange(len(index))
        if u:
            u, v = np.concatenate(u), np.concatenate(v)
            while len(u):
                pu, pv = parent[u], parent[v]
                if np.array_equal(pu, pv):
                    break
                low = np.minimum(pu, pv)
                np.minimum.at(parent, pu, low)
                np.minimum.at(parent, pv, low)
                while True:  # pointer jumping
                    jumped = parent[parent]
                    if np.array_equal(jumped, parent):
                        break
                    parent = jumped
        labels = np.full((self.h, self.w), -1, dtype=np.int64)
        labels[ys, xs] = parent
        return labels

    def roles(self):
        """(h, w) int8 roles: BOUNDARY, INTERIOR, or 0 for empty tiles.

        A cell is interior when all eight neighbor tiles belong to its own
        bonded component; empty tiles, other components and the world edge
        count as outside. Cached until the world changes.
        """
        version, cached = self._roles_cache
        if version == self.version and cached is not None:
            return cached
        labels = self.component_labels()
        padded = np.pad(labels, 1, constant_values=-2)
        outside = np.zeros((self.h, self.w), dtype=bool)
        for dx, dy in DIRECTIONS:
            outside |= padded[1 + dy:1 + dy + self.h, 1 + dx:1 + dx + self.w] != labels
        roles = np.where(labels < 0, 0, np.where(outside, BOUNDARY, INTERIOR)).astype(np.int8)
        self._roles_cache = (self.version, roles)
        return roles

    # -- events ------------------------------------------------------------------
    def _event(self, player_id, kind, cell_id, action=0, code=0, other=0):
        if not self.manifest["observation"]["version"] >= 2:
            return  # legacy observations carry no events
        self.player_events.setdefault(int(player_id), []).append(
            (kind, int(cell_id), int(action), int(code), int(other)))

    def record_results(self, player_ids, cell_ids, actions, reasons):
        for pid, cid, action, code in zip(player_ids, cell_ids, actions, reasons):
            if cid:
                self._event(pid, EVENT_RESULT, cid, action, code)

    def events_for(self, player_id):
        rows = self.player_events.get(int(player_id), [])
        return np.array(rows, dtype=EVENT_DTYPE) if rows else np.empty(0, dtype=EVENT_DTYPE)

    def end_observation_window(self):
        """Forget per-observation state once every player has been observed."""
        self.sense_boost = {}
        self.player_events = {}

    def _set_bond(self, x, y, nx, ny, connected):
        dx, dy = nx - x, ny - y
        if (dx, dy) not in DIRECTIONS:
            return
        self.version += 1
        a, b = DIRECTIONS.index((dx, dy)), DIRECTIONS.index((-dx, -dy))
        if connected:
            self.arrays.bonds[y, x] |= 1 << a
            self.arrays.bonds[ny, nx] |= 1 << b
        else:
            self.arrays.bonds[y, x] &= 255 ^ (1 << a)
            self.arrays.bonds[ny, nx] &= 255 ^ (1 << b)

    def _clear_bonds(self, x, y):
        self.version += 1
        for bit, (dx, dy) in enumerate(DIRECTIONS):
            nx, ny = x + dx, y + dy
            if self.arrays.bonds[y, x] & (1 << bit) and 0 <= nx < self.w and 0 <= ny < self.h:
                self._set_bond(x, y, nx, ny, False)
        self.arrays.bonds[y, x] = 0

    # -- cell identity ------------------------------------------------------
    def _new_cell_id(self):
        cid = self.next_cell_id
        if cid > np.iinfo(np.uint32).max:
            raise OverflowError("cell IDs exhausted")
        self.next_cell_id += 1
        return cid

    def _clear_cell(self, x, y):
        """Return one tile to the environment (bonds are cleared separately)."""
        for field in CELL_FIELDS:
            getattr(self.arrays, field)[y, x] = 0

    def _clear_mask(self, mask):
        for field in CELL_FIELDS:
            getattr(self.arrays, field)[mask] = 0

    def place_cell(self, player_id, x, y, energy=10, species=None):
        """Create a founder cell on an empty tile and return its cell_id."""
        if not (0 <= x < self.w and 0 <= y < self.h) or self.arrays.owner[y, x] != 0 or self.arrays.blocks[y, x] != 0:
            raise ValueError(f"cannot place a cell at ({x}, {y})")
        A = self.arrays
        A.organism[y, x] = self.organisms.create(player_id, self.tick)
        A.owner[y, x] = player_id
        A.species[y, x] = player_id if species is None else species
        A.cell_type[y, x] = 0
        A.state[y, x] = 0
        A.energy[y, x] = energy
        A.cell_id[y, x] = self._new_cell_id()
        self.version += 1
        return int(A.cell_id[y, x])

    def intentions_from_v2(self, player_id, rows):
        """Convert v2 rows [cell_id, action, dx, dy, param] into intentions.

        Rows naming a cell this player does not own, a non-adjacent offset,
        an unknown action or a param outside int32 are dropped; order is kept.
        Raises ValueError for data that is not an (n, 5) integer table.
        """
        from cellgame.shared.protocol import integer_rows
        table = integer_rows(rows, 5, self.w * self.h)
        if table.size == 0:
            return np.empty((0,), dtype=INTENTION_DTYPE)
        ys, xs = np.where(self.arrays.owner == player_id)
        ids = self.arrays.cell_id[ys, xs].astype(np.int64)
        order = np.argsort(ids)
        ids, xs, ys = ids[order], xs[order], ys[order]
        if len(ids):
            pos = np.clip(np.searchsorted(ids, table[:, 0]), 0, len(ids) - 1)
            found = ids[pos] == table[:, 0]
        else:
            pos = np.zeros(len(table), dtype=np.int64)
            found = np.zeros(len(table), dtype=bool)
        int32 = np.iinfo(np.int32)
        ok = (found
              & (table[:, 1] >= 0) & (table[:, 1] <= MAX_ACTION)
              & (np.abs(table[:, 2]) <= 1) & (np.abs(table[:, 3]) <= 1)
              & (table[:, 4] >= int32.min) & (table[:, 4] <= int32.max))
        table, pos = table[ok], pos[ok]
        out = np.zeros(len(table), dtype=INTENTION_DTYPE)
        out["src_x"], out["src_y"] = xs[pos], ys[pos]
        out["tgt_x"], out["tgt_y"] = xs[pos] + table[:, 2], ys[pos] + table[:, 3]
        out["action"], out["param"] = table[:, 1], table[:, 4]
        return out

    # -- player lifecycle -------------------------------------------------
    def spawn_player(self, player_id, species_id, count=20, seed=None):
        """Choose a spread-out cluster, preferring distance from existing players."""
        rng = np.random.default_rng(seed if seed is not None else player_id * 7919 + 13)
        margin_x, margin_y = min(8, max(0, (self.w - 1) // 2)), min(8, max(0, (self.h - 1) // 2))
        cx_candidates = rng.integers(margin_x, self.w - margin_x, size=96)
        cy_candidates = rng.integers(margin_y, self.h - margin_y, size=96)
        ys, xs = np.where((self.arrays.owner != 0) & (self.arrays.owner != player_id))
        if len(xs):
            # Bounded work even in crowded late-game worlds.
            if len(xs) > 2048:
                selection = rng.choice(len(xs), 2048, replace=False)
                xs, ys = xs[selection], ys[selection]
            distances = (cx_candidates[:, None] - xs[None, :]) ** 2 + (cy_candidates[:, None] - ys[None, :]) ** 2
            best = int(np.argmax(np.min(distances, axis=1)))
        else:
            best = 0
        cx, cy = int(cx_candidates[best]), int(cy_candidates[best])
        placed = 0
        tries = 0
        while placed < count and tries < count * 200:
            tries += 1
            x = int(np.clip(cx + int(rng.integers(-8, 9)), 0, self.w - 1))
            y = int(np.clip(cy + int(rng.integers(-8, 9)), 0, self.h - 1))
            if self.arrays.owner[y, x] == 0 and self.arrays.blocks[y, x] == 0 and self.arrays.env_material[y, x] < 2:
                self._visual("birth", x, y, x, y, player_id)
                self.place_cell(player_id, x, y, energy=10, species=species_id)
                placed += 1
        self.version += 1
        return placed

    def kill_player(self, player_id):
        """Disconnect = death: every cell of the player returns to the
        environment in the same tick."""
        mask = self.arrays.owner == player_id
        n = int(mask.sum())
        if n:
            for y, x in zip(*np.where(mask)):
                self._visual("death", x, y, x, y, player_id, self.arrays.cell_type[y, x])
                self._clear_bonds(int(x), int(y))
            self._clear_mask(mask)
            self.version += 1
        return n

    # -- intentions --------------------------------------------------------
    def apply_intentions(self, resolved, player_ids=None):
        """Apply arbitrated intentions. Fixed order (DIE, CHANGE, SET_STATE, EAT,
        REPRODUCE, MOVE, ATTACK); occupancy is re-checked at apply time.
        ATTACK success was decided by the arbiter on the pre-tick world;
        here it only lands if the same owner's cell is still there."""
        self.last_group_followers = np.zeros(0, dtype=np.int64)
        self.last_rule_events = []
        if resolved is None or len(resolved) == 0:
            self.last_applied = np.zeros(0, dtype=bool)
            return {"move": 0, "attack": 0, "reproduce": 0, "eat": 0,
                    "change": 0, "state": 0, "die": 0}
        arr = np.asarray(resolved)
        n = len(arr)
        applied = np.zeros(n, dtype=bool)
        self.last_applied = applied
        if player_ids is None:
            player_ids = self.arrays.owner[arr["src_y"], arr["src_x"]]
        player_ids = np.asarray(player_ids, dtype=np.int32)

        # pre-tick snapshot for ATTACK landing checks
        snap_owner = self.arrays.owner.copy()
        snap_energy = self.arrays.energy.copy()
        snap_type = self.arrays.cell_type.copy()
        snap_bonds = self.arrays.bonds.copy()
        snap_blocks = self.arrays.blocks.copy()
        self._blocks_changed_during_actions = set()

        counts = {"move": 0, "attack": 0, "reproduce": 0, "eat": 0,
                  "change": 0, "state": 0, "die": 0}
        act = arr["action"].astype(int)
        sx, sy = arr["src_x"].astype(int), arr["src_y"].astype(int)
        tx, ty = arr["tgt_x"].astype(int), arr["tgt_y"].astype(int)
        strength = arr["strength"].astype(int)
        param = arr["param"].astype(int)
        A = self.arrays

        def alive(i):
            return A.owner[sy[i], sx[i]] == player_ids[i]

        # DIE
        for i in np.where(act == int(Action.DIE))[0]:
            if alive(i):
                self._visual("death", sx[i], sy[i], sx[i], sy[i], player_ids[i], A.cell_type[sy[i], sx[i]])
                self._event(player_ids[i], EVENT_DIED, A.cell_id[sy[i], sx[i]], int(Action.DIE), DIED_SELF)
                self._clear_bonds(sx[i], sy[i])
                self._clear_cell(sx[i], sy[i])
                applied[i] = True
                counts["die"] += 1
        # CHANGE
        for i in np.where(act == int(Action.CHANGE))[0]:
            if alive(i) and A.energy[sy[i], sx[i]] >= action_cost(Action.CHANGE, self.constraints):
                A.cell_type[sy[i], sx[i]] = param[i]
                A.energy[sy[i], sx[i]] -= action_cost(Action.CHANGE, self.constraints)
                applied[i] = True
                counts["change"] += 1
        # SET_STATE changes one public integer on the actor, at no energy
        # cost. It is still the cell's only action for this tick.
        for i in np.where(act == int(Action.SET_STATE))[0]:
            if alive(i):
                A.state[sy[i], sx[i]] = param[i]
                applied[i] = True
                counts["state"] += 1
        # SENSE widens this cell's perception for the next observation only.
        for i in np.where(act == int(Action.SENSE))[0]:
            cost = param[i] * self.rules.sense_cost_per_radius
            if alive(i) and A.energy[sy[i], sx[i]] >= cost:
                A.energy[sy[i], sx[i]] -= cost
                self.sense_boost[int(A.cell_id[sy[i], sx[i]])] = int(param[i])
                applied[i] = True
                counts["sense"] = counts.get("sense", 0) + 1
        # Connections are reciprocal and only join cells of the same owner.
        for action, connect in ((Action.UNBOND, False), (Action.BOND, True)):
            for i in np.where(act == int(action))[0]:
                if alive(i) and A.owner[ty[i], tx[i]] == player_ids[i]:
                    self._set_bond(sx[i], sy[i], tx[i], ty[i], connect)
                    applied[i] = True
        for i in np.where(act == int(Action.TRANSFER))[0]:
            direction = (tx[i] - sx[i], ty[i] - sy[i])
            if alive(i) and A.owner[ty[i], tx[i]] == player_ids[i] and direction in DIRECTIONS and A.bonds[sy[i], sx[i]] & (1 << DIRECTIONS.index(direction)):
                amount = min(param[i], max(0, int(A.energy[sy[i], sx[i]]) - 1), 32767 - int(A.energy[ty[i], tx[i]]))
                A.energy[sy[i], sx[i]] -= amount
                A.energy[ty[i], tx[i]] += amount
                applied[i] = True
                if amount:
                    self._visual("share", sx[i], sy[i], tx[i], ty[i], player_ids[i])
        # EAT
        for i in np.where(act == int(Action.EAT))[0]:
            if alive(i):
                food = A.env_food[ty[i], tx[i]]
                if food > 0:
                    gain = min(self.constraints["eat_gain"], float(food))
                    A.env_food[ty[i], tx[i]] = food - gain
                    A.energy[sy[i], sx[i]] = min(32767, int(A.energy[sy[i], sx[i]]) + int(gain))
                    self.last_rule_events.append({"type": "eat", "x": int(sx[i]), "y": int(sy[i]),
                                                  "cell_id": int(A.cell_id[sy[i], sx[i]]),
                                                  "material": int(A.env_material[ty[i], tx[i]])})
                    self._visual("eat", sx[i], sy[i], sx[i], sy[i], player_ids[i])
                    applied[i] = True
                    counts["eat"] += 1
        # REPRODUCE
        for i in np.where(act == int(Action.REPRODUCE))[0]:
            if alive(i) and A.energy[sy[i], sx[i]] >= max(self.constraints["reproduce_min_energy"], action_cost(Action.REPRODUCE, self.constraints)) \
                    and A.owner[ty[i], tx[i]] == 0 and A.blocks[ty[i], tx[i]] == 0:
                A.energy[sy[i], sx[i]] -= action_cost(Action.REPRODUCE, self.constraints)
                parent_id = int(A.organism[sy[i], sx[i]])
                if not parent_id:
                    parent_id = self.organisms.create(player_ids[i], self.tick)
                    A.organism[sy[i], sx[i]] = parent_id
                A.organism[ty[i], tx[i]] = parent_id if param[i] == 1 else self.organisms.create(player_ids[i], self.tick, parent_id, "birth")
                A.owner[ty[i], tx[i]] = player_ids[i]
                A.species[ty[i], tx[i]] = A.species[sy[i], sx[i]]
                A.cell_type[ty[i], tx[i]] = 0
                A.state[ty[i], tx[i]] = 0
                A.energy[ty[i], tx[i]] = self.constraints["child_energy"]
                A.cell_id[ty[i], tx[i]] = self._new_cell_id()
                self._event(player_ids[i], EVENT_BORN, A.cell_id[ty[i], tx[i]], int(Action.REPRODUCE),
                            0, A.cell_id[sy[i], sx[i]])
                applied[i] = True
                self._visual("birth", sx[i], sy[i], tx[i], ty[i], player_ids[i])
                if param[i] == 1:
                    self._set_bond(sx[i], sy[i], tx[i], ty[i], True)
                counts["reproduce"] += 1
        # MOVE
        for i in np.where(act == int(Action.MOVE))[0]:
            move_cost = action_cost(Action.MOVE, self.constraints) + (self.constraints["armor_move_surcharge"] if A.cell_type[sy[i], sx[i]] == ARMOR_TYPE else 0)
            if A.blocks[ty[i], tx[i]]:
                move_cost += self.constraints["push_cost"]
            if alive(i) and A.bonds[sy[i], sx[i]] == 0 and A.energy[sy[i], sx[i]] >= move_cost \
                    and A.owner[ty[i], tx[i]] == 0:
                push = self._plan_push([(int(tx[i]), int(ty[i]))], int(tx[i]-sx[i]), int(ty[i]-sy[i]))
                if push is None:
                    continue
                self._apply_push(push)
                A.energy[sy[i], sx[i]] -= move_cost
                self._visual("move", sx[i], sy[i], tx[i], ty[i], player_ids[i], A.cell_type[sy[i], sx[i]])
                for f in CELL_FIELDS:
                    getattr(A, f)[ty[i], tx[i]] = getattr(A, f)[sy[i], sx[i]]
                self._clear_cell(sx[i], sy[i])
                applied[i] = True
                counts["move"] += 1
        # A connected component can translate atomically. The smallest source
        # coordinate with an accepted proposal chooses its direction. All
        # destinations and every member's energy are checked before mutation.
        # Components under attack stay put, so an attack cannot hit a different
        # same-owner cell that moved into the victim's previous position.
        proposals = sorted(np.where(act == int(Action.MOVE_GROUP))[0], key=lambda i: (sy[i], sx[i]))
        visited, moved = set(), set()
        attacked = {(int(tx[i]), int(ty[i])) for i in np.where(act == int(Action.ATTACK))[0]}
        for i in proposals:
            start = (int(sx[i]), int(sy[i]))
            if start in visited or not alive(i) or not A.bonds[start[1], start[0]]:
                continue
            owner = int(player_ids[i])
            component, todo = set(), [start]
            while todo:
                x, y = todo.pop()
                if (x, y) in component:
                    continue
                component.add((x, y))
                mask = int(A.bonds[y, x])
                for bit, (dx, dy) in enumerate(DIRECTIONS):
                    nx, ny = x + dx, y + dy
                    if mask & (1 << bit) and 0 <= nx < self.w and 0 <= ny < self.h and A.owner[ny, nx] == owner and (nx, ny) not in component:
                        todo.append((nx, ny))
            visited.update(component)
            if len(component) > self.constraints.get("group_move_max_cells", 256) or component & attacked:
                continue
            dx, dy = int(tx[i] - sx[i]), int(ty[i] - sy[i])
            if any(not (0 <= x + dx < self.w and 0 <= y + dy < self.h) or (A.owner[y+dy, x+dx] != 0 and (x+dx, y+dy) not in component) for x, y in component):
                continue
            push = self._plan_push([(x + dx, y + dy) for x, y in component if (x + dx, y + dy) not in component], dx, dy)
            if push is None:
                continue
            coords = sorted(component, key=lambda p: (p[1], p[0]))
            xs = np.array([x for x, y in coords]); ys = np.array([y for x, y in coords])
            costs = action_cost(Action.MOVE, self.constraints) + (A.cell_type[ys, xs] == ARMOR_TYPE) * self.constraints["armor_move_surcharge"]
            costs = costs + (A.blocks[ys + dy, xs + dx] != 0) * self.constraints["push_cost"]
            if np.any(A.energy[ys, xs] < costs):
                continue
            self._apply_push(push)
            fields = CELL_FIELDS + ("bonds",)
            values = {field: getattr(A, field)[ys, xs].copy() for field in fields}
            values["energy"] -= costs.astype(values["energy"].dtype)
            for x, y in coords:
                self._visual("move", x, y, x + dx, y + dy, owner, A.cell_type[y, x])
            for field in fields:
                getattr(A, field)[ys, xs] = 0
            for field in fields:
                getattr(A, field)[ys + dy, xs + dx] = values[field]
            applied[i] = True
            moved.update(component)
            counts["move"] += len(component)
        # Other proposals from a component that already moved lost to that move.
        self.last_group_followers = np.array(
            [i for i in proposals if not applied[i] and (int(sx[i]), int(sy[i])) in moved], dtype=np.int64)
        # ATTACK (lands only if the victim is still the same owner's cell)
        for i in np.where(act == int(Action.ATTACK))[0]:
            x, y = int(tx[i]), int(ty[i])
            if snap_owner[y, x] == 0 and snap_blocks[y, x] != 0:
                cost = self.constraints["block_attack_cost"]
                if (alive(i) and A.energy[sy[i], sx[i]] >= cost and A.owner[y, x] == 0
                        and (x, y) not in self._blocks_changed_during_actions and A.blocks[y, x] == snap_blocks[y, x]):
                    block = int(A.blocks[y, x])
                    A.blocks[y, x] = 0
                    A.energy[sy[i], sx[i]] -= cost
                    self._visual("attack", sx[i], sy[i], x, y, player_ids[i], A.cell_type[sy[i], sx[i]])
                    self.last_rule_events.append({"type": "break_block", "x": x, "y": y,
                                                  "block": block, "cell_id": int(A.cell_id[sy[i], sx[i]])})
                    applied[i] = True
                    counts["attack"] += 1
                continue
            if alive(i) and A.energy[sy[i], sx[i]] >= action_cost(Action.ATTACK, self.constraints) \
                    and snap_owner[ty[i], tx[i]] != 0 \
                    and snap_owner[ty[i], tx[i]] != player_ids[i] \
                    and strength[i] > int(combat_defense(snap_energy, snap_type, snap_bonds, [tx[i]], [ty[i]],
                                                          self.constraints, self.rules.bonded_support_percent)[0]) \
                    and A.owner[ty[i], tx[i]] == snap_owner[ty[i], tx[i]]:
                self._visual("attack", sx[i], sy[i], tx[i], ty[i], player_ids[i], A.cell_type[sy[i], sx[i]])
                self._visual("death", tx[i], ty[i], tx[i], ty[i], A.owner[ty[i], tx[i]], A.cell_type[ty[i], tx[i]])
                self._clear_bonds(tx[i], ty[i])
                victim_energy = int(A.energy[ty[i], tx[i]])
                self._event(A.owner[ty[i], tx[i]], EVENT_DIED, A.cell_id[ty[i], tx[i]], int(Action.ATTACK), DIED_ATTACK)
                self._clear_cell(tx[i], ty[i])
                applied[i] = True
                new_energy = int(A.energy[sy[i], sx[i]]) + (victim_energy * self.constraints["attack_reward_percent"]) // 100 - action_cost(Action.ATTACK, self.constraints)
                A.energy[sy[i], sx[i]] = min(32767, new_energy)
                counts["attack"] += 1

        if n:
            self.version += 1
        return counts

    def seed_blocks(self, seed=0):
        """Populate sparse wood, stone and sand on safe ground, reproducibly."""
        rng = np.random.default_rng(seed + 83417)
        a = self.arrays
        roll = rng.random((self.h, self.w))
        allowed = (a.owner == 0) & (a.env_material < 2)
        a.blocks[allowed & (roll < .025)] = 1  # wood
        a.blocks[allowed & (roll >= .025) & (roll < .045)] = 2  # stone
        a.blocks[allowed & (roll >= .045) & (roll < .065)] = 3  # sand

    def _plan_push(self, starts, dx, dy):
        """Plan parallel block chains atomically; cells and edges stop them."""
        a = self.arrays
        blocks = set()
        for x, y in starts:
            while 0 <= x < self.w and 0 <= y < self.h and a.blocks[y, x]:
                blocks.add((x, y))
                if len(blocks) > 64:
                    return None
                x, y = x + dx, y + dy
            if not (0 <= x < self.w and 0 <= y < self.h) or a.owner[y, x]:
                return None
        return sorted(blocks, key=lambda p: p[0]*dx + p[1]*dy, reverse=True), dx, dy

    def _apply_push(self, plan):
        blocks, dx, dy = plan
        for x, y in blocks:
            self._blocks_changed_during_actions.update(((x, y), (x + dx, y + dy)))
            self.arrays.blocks[y + dy, x + dx] = self.arrays.blocks[y, x]
            self.arrays.blocks[y, x] = 0

    def ecology(self):
        """Energy-0 cells die at end of tick."""
        # Lava burns wood and fuses sand into stone, without changing terrain.
        a = self.arrays
        lava = a.env_material == 2
        a.blocks[lava & (a.blocks == 1)] = 0
        a.blocks[lava & (a.blocks == 3)] = 2
        interval = self.constraints["metabolism_interval"]
        if interval and self.tick > 0 and self.tick % interval == 0:
            self._metabolize()
        mask = (self.arrays.owner != 0) & (self.arrays.energy <= 0)
        n = int(mask.sum())
        if n:
            for y, x in zip(*np.where(mask)):
                self._visual("death", x, y, x, y, self.arrays.owner[y, x], self.arrays.cell_type[y, x])
                self._event(self.arrays.owner[y, x], EVENT_DIED, self.arrays.cell_id[y, x], 0, DIED_STARVED)
                self._clear_bonds(int(x), int(y))
            self.arrays.env_food[mask & (self.arrays.env_material < 2)] += 2.0
            self._clear_mask(mask)
            self.version += 1
        return n

    def _metabolize(self):
        rules, occupied = self.rules, self.arrays.owner != 0
        if rules.metabolism_boundary == rules.metabolism_interior:
            self.arrays.energy[occupied] -= rules.metabolism_boundary
            return
        roles = self.roles()
        self.arrays.energy[roles == BOUNDARY] -= rules.metabolism_boundary
        self.arrays.energy[roles == INTERIOR] -= rules.metabolism_interior

    # -- sensing / deltas ---------------------------------------------------
    def gather_sense(self, player_id, radius=1):
        ys, xs = np.where(self.arrays.owner == player_id)
        n = len(xs)
        if n == 0:
            return {
                "tick": self.tick,
                "cells": np.empty((0, 5), dtype=np.int32),
                "neighborhood": np.empty((0, (2 * radius + 1) ** 2 * 5), dtype=np.int32),
                "env": np.empty((0, 12), dtype=np.float32),
                "constraints": dict(self.constraints),
            }
        cells = np.empty((n, 5), dtype=np.int32)
        cells[:, 0] = xs
        cells[:, 1] = ys
        cells[:, 2] = self.arrays.cell_type[ys, xs]
        cells[:, 3] = self.arrays.state[ys, xs]
        cells[:, 4] = self.arrays.energy[ys, xs]
        neighborhood = expand_neighborhood(self.arrays, xs, ys, player_id, radius)
        # First two columns remain compatible with existing species. The
        # remaining nine are the 3x3 food field, including the center.
        env = np.empty((n, 12), dtype=np.float32)
        env[:, 0] = self.arrays.env_temp[ys, xs]
        env[:, 1] = self.arrays.env_food[ys, xs]
        food = np.pad(self.arrays.env_food, 1)
        for j, (dy, dx) in enumerate((dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
            env[:, 2 + j] = food[ys + dy + 1, xs + dx + 1]
        env[:, 11] = self.arrays.bonds[ys, xs]
        return {
            "tick": self.tick,
            "cells": cells,
            "neighborhood": neighborhood,
            "env": env,
            "constraints": dict(self.constraints),
        }

    def delta_since_last_sent(self):
        """Changes since the last call; also updates the baseline."""
        organism_stats = self.organisms.update(self.arrays, self.tick)
        metadata = {key: {k:v for k,v in item.items() if k not in ("cells", "energy")}
                    for key, item in organism_stats.items()}
        updates = {key:value for key,value in metadata.items() if self._last_organism_metadata.get(key) != value}
        removed = list(self._last_organism_metadata.keys() - metadata.keys())
        self._last_organism_metadata = metadata
        delta = compute_delta(self._last_sent, self.arrays)
        environment = {}
        for field in ("env_food", "env_temp", "blocks", "bonds", "organism"):
            if not np.array_equal(getattr(self._last_sent, field), getattr(self.arrays, field)):
                environment[field] = getattr(self.arrays, field).copy()
        self._last_sent = self.arrays.copy()
        events, self._visual_events = self._visual_events, []
        self._visual_counts = {}
        return {"tick": self.tick, "changes": delta, "environment": environment, "visual_events": events, "organism_updates": updates, "organism_removed": removed}

    def refresh_entities(self):
        """Reconcile identities after topology changes, before exposing observations."""
        return self.organisms.update(self.arrays, self.tick)

    def snapshot_arrays(self):
        # Multiprocessing queues serialize asynchronously; do not enqueue live
        # arrays that the simulation may mutate before serialization.
        return {name: array.copy() for name, array in self.arrays.to_dict().items()}

    def summary(self):
        owners, counts = np.unique(self.arrays.owner, return_counts=True)
        per_species = {}
        for o, c in zip(owners.tolist(), counts.tolist()):
            if o != 0:
                per_species[int(o)] = int(c)
        return {
            "tick": self.tick,
            "total_food": float(self.arrays.env_food.sum()),
            "mean_temp": float(self.arrays.env_temp.mean()),
            "cells_per_player": per_species,
            "total_cells": int((self.arrays.owner != 0).sum()),
            "constraints": dict(self.constraints),
        }
