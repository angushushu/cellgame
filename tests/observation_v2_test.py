"""Observation v2 (M1): cell identity, radius perception, intentions v2,
the legacy adapter, SDK access, and tick-for-tick parity with legacy."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cellgame.client.executor import to_intentions
from cellgame.client.rule_loader import load_rule
from cellgame.server.perception import gather_observation
from cellgame.server.world import WorldState
from cellgame.server.world_rules import apply_world_params
from cellgame.shared.arbiter import arbitrate
from cellgame.shared.manifest import build_manifest
from cellgame.shared.models import INTENTION_DTYPE, Action
from cellgame.shared.observation import (
    EMPTY, MINE, MINE_BONDED, OTHER, OUTSIDE,
    expand_observation, intentions_to_v2, observation_to_json, observation_to_world, to_legacy_batch,
)
from cellgame.shared.protocol import encode_msg
from cellgame.species.composer import PRESETS, decide_with_config

RADIUS1 = build_manifest({"perception": {"model": "radius", "radius": 1}})
RADIUS2 = build_manifest({"perception": {"model": "radius", "radius": 2}})


def observe(world, pid, manifest, run=""):
    return expand_observation(gather_observation(world, pid, manifest, run), manifest)


def small_world():
    world = WorldState(16, 16, seed=3)
    world.arrays.env_food[:] = 0
    return world


def percepts_of(obs, row):
    p = obs["percepts"]
    return p[p["observer"] == row]


# -- cell identity -----------------------------------------------------------

def test_spawn_assigns_unique_ids():
    world = WorldState(32, 32, seed=0)
    world.spawn_player(1, 1, count=10)
    world.spawn_player(2, 2, count=10)
    ids = world.arrays.cell_id[world.arrays.owner != 0]
    assert len(ids) == 20 and np.all(ids > 0) and len(set(ids.tolist())) == 20
    assert np.all(world.arrays.cell_id[world.arrays.owner == 0] == 0)


def test_ids_follow_moves_and_clear_on_death():
    world = small_world()
    mover = world.place_cell(1, 5, 5, energy=20)
    parent = world.place_cell(1, 9, 9, energy=20)
    world.arrays.energy[9, 9] = 20
    rows = np.zeros(2, dtype=INTENTION_DTYPE)
    rows[0] = (5, 5, 6, 5, Action.MOVE, 0, 0)
    rows[1] = (9, 9, 10, 9, Action.REPRODUCE, 0, 0)
    world.apply_intentions(arbitrate(rows, world, world.constraints, 0, np.array([1, 1])))
    assert world.arrays.cell_id[5, 6] == mover and world.arrays.cell_id[5, 5] == 0
    child = int(world.arrays.cell_id[9, 10])
    assert child not in (0, mover, parent) and world.arrays.cell_id[9, 9] == parent
    world.arrays.energy[5, 6] = 0
    world.ecology()
    assert world.arrays.cell_id[5, 6] == 0


def test_ids_follow_group_moves_and_clear_on_attack():
    world = small_world()
    a = world.place_cell(1, 4, 4, energy=20)
    b = world.place_cell(1, 5, 4, energy=20)
    world._set_bond(4, 4, 5, 4, True)
    rows = np.zeros(1, dtype=INTENTION_DTYPE)
    rows[0] = (4, 4, 4, 5, Action.MOVE_GROUP, 0, 0)
    world.apply_intentions(arbitrate(rows, world, world.constraints, 0, np.array([1])))
    assert world.arrays.cell_id[5, 4] == a and world.arrays.cell_id[5, 5] == b
    victim = world.place_cell(2, 6, 5, energy=1)
    assert victim
    rows[0] = (5, 5, 6, 5, Action.ATTACK, 0, 0)
    world.apply_intentions(arbitrate(rows, world, world.constraints, 1, np.array([1])))
    assert world.arrays.owner[5, 6] == 0 and world.arrays.cell_id[5, 6] == 0


def test_kill_player_clears_ids():
    world = WorldState(32, 32, seed=0)
    world.spawn_player(1, 1, count=5)
    world.kill_player(1)
    assert not world.arrays.cell_id.any()


def test_copy_keeps_ids():
    world = small_world()
    world.place_cell(1, 2, 2)
    assert world.arrays.copy().cell_id[2, 2] == world.arrays.cell_id[2, 2]


# -- radius perception ----------------------------------------------------------

def test_radius1_percepts_encode_occupants():
    world = small_world()
    me = world.place_cell(1, 0, 0, energy=12)
    world.place_cell(1, 1, 0, energy=7)
    world.place_cell(1, 0, 1, energy=6)
    world.place_cell(2, 1, 1, energy=9)
    world._set_bond(0, 0, 1, 0, True)
    world.arrays.env_food[0, 0] = 4.5
    obs = observe(world, 1, RADIUS1)
    assert obs["version"] == 2 and obs["tick"] == world.tick
    cells = obs["cells"]
    row = int(np.where(cells["cell_id"] == me)[0][0])
    assert (cells["x"][row], cells["y"][row], cells["energy"][row]) == (0, 0, 12)
    seen = {(int(p["dx"]), int(p["dy"])): p for p in percepts_of(obs, row)}
    assert len(seen) == 9
    assert seen[(-1, -1)]["occupant"] == OUTSIDE and seen[(0, -1)]["occupant"] == OUTSIDE
    assert seen[(0, 0)]["occupant"] == MINE and seen[(0, 0)]["food"] == np.float32(4.5)
    assert seen[(1, 0)]["occupant"] == MINE_BONDED and seen[(1, 0)]["energy"] == 7
    assert seen[(0, 1)]["occupant"] == MINE
    assert seen[(1, 1)]["occupant"] == OTHER and seen[(1, 1)]["species"] == 2


def test_radius2_and_euclidean_sizes():
    world = small_world()
    world.place_cell(1, 8, 8)
    world.place_cell(2, 10, 8)
    obs = observe(world, 1, RADIUS2)
    assert len(obs["percepts"]) == 25
    far = [p for p in obs["percepts"] if (p["dx"], p["dy"]) == (2, 0)]
    assert far and far[0]["occupant"] == OTHER
    disc = build_manifest({"perception": {"model": "radius", "radius": 2, "metric": "euclidean"}})
    assert len(observe(world, 1, disc)["percepts"]) == 13


def test_empty_player_observation():
    obs = observe(small_world(), 7, RADIUS1)
    assert len(obs["cells"]) == 0 and len(obs["percepts"]) == 0


def test_observation_json_is_plain():
    world = small_world()
    world.place_cell(1, 3, 3)
    data = observation_to_json(observe(world, 1, RADIUS1))
    assert data["cells"]["columns"][0] == "cell_id"
    assert data["tiles"]["columns"][:3] == ["x", "y", "occupant"]
    assert len(data["tiles"]["rows"]) == 9
    assert all(isinstance(v, (int, float)) for v in data["tiles"]["rows"][0])


def test_wire_lists_each_tile_once_and_stays_small():
    world = WorldState(256, 256, seed=0)
    for y in range(40, 180):
        for x in range(40, 180):
            world.place_cell(1, x, y)
    wire = gather_observation(world, 1, build_manifest({"perception": {"model": "radius", "radius": 3}}))
    assert len(wire["cells"]) == 140 * 140 and "percepts" not in wire
    assert len(wire["tiles"]) == 146 * 146
    assert len(encode_msg("observation", **wire)) < 4 * 1024 * 1024


def test_world_view_shows_only_perceived_tiles():
    world = small_world()
    world.place_cell(1, 2, 2)
    world.place_cell(2, 3, 3)
    world.place_cell(2, 10, 10)
    world.arrays.env_food[12, 12] = 5
    view = observation_to_world(gather_observation(world, 1, RADIUS1), 1, 16, 16)
    assert view.owner[2, 2] == 1 and view.owner[3, 3] == 2
    assert view.owner[10, 10] == 0 and view.env_food[12, 12] == 0
    assert (view.owner != 0).sum() == 2


def test_expand_with_unknown_tiles_omits_rows():
    world = small_world()
    world.place_cell(1, 5, 5)
    wire = gather_observation(world, 1, RADIUS1)
    for key in ("tiles", "materials", "biomes"):
        wire[key] = wire[key][:0]  # optional layers stay aligned with the tile table
    obs = expand_observation(wire, RADIUS1)
    assert len(obs["percepts"]) == 0


# -- intentions v2 ---------------------------------------------------------------

def test_intentions_from_v2_validates_rows():
    world = small_world()
    mine = world.place_cell(1, 4, 4, energy=20)
    theirs = world.place_cell(2, 8, 8, energy=20)
    rows = np.array([
        [mine, Action.MOVE, 1, 0, 0],
        [theirs, Action.MOVE, 1, 0, 0],           # not mine
        [999999, Action.EAT, 0, 0, 0],            # unknown id
        [mine, Action.MOVE, 2, 0, 0],             # not adjacent
        [mine, Action.SET_STATE, 0, 0, 2 ** 31],  # param overflows int32
        [mine, 99, 0, 0, 0],                      # unknown action
        [mine, Action.EAT, 0, 0, 0],
    ], dtype=np.int64)
    out = world.intentions_from_v2(1, rows)
    assert out.dtype == INTENTION_DTYPE
    assert [(int(r["src_x"]), int(r["src_y"]), int(r["tgt_x"]), int(r["tgt_y"]), int(r["action"]))
            for r in out] == [(4, 4, 5, 4, Action.MOVE), (4, 4, 4, 4, Action.EAT)]


def test_intentions_from_v2_rejects_bad_shapes():
    world = small_world()
    for bad in ([[1, 2, 3]], "x", [[1.5, 0, 0, 0, 0]]):
        try:
            world.intentions_from_v2(1, bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    assert len(world.intentions_from_v2(1, [])) == 0


def test_intentions_round_trip_through_v2():
    world = small_world()
    cid = world.place_cell(1, 4, 4, energy=20)
    obs = observe(world, 1, RADIUS1)
    legacy = to_intentions([[4, 4, 5, 5, Action.MOVE, 0, 0], [9, 9, 9, 9, Action.EAT, 0, 0]],
                           to_legacy_batch(obs)["cells"])
    v2 = intentions_to_v2(legacy, obs)
    assert v2.tolist() == [[cid, Action.MOVE, 1, 1, 0]]
    back = world.intentions_from_v2(1, v2)
    assert (int(back[0]["tgt_x"]), int(back[0]["tgt_y"])) == (5, 5)


# -- legacy adapter and parity ----------------------------------------------------

def busy_world(size=48):
    world = WorldState(size, size, seed=11)
    for pid in (1, 2, 3):
        world.spawn_player(pid, pid, count=18, seed=pid)
    ys, xs = np.where(world.arrays.owner == 1)
    for x, y in zip(xs[:6], ys[:6]):
        for dx, dy in ((1, 0), (0, 1), (1, 1)):
            nx, ny = x + dx, y + dy
            if nx < size and ny < size and world.arrays.owner[ny, nx] == 1:
                world._set_bond(int(x), int(y), int(nx), int(ny), True)
    world.place_cell(2, 0, 0)
    world.place_cell(2, size - 1, size - 1)
    return world


def test_legacy_adapter_matches_gather_sense():
    world = busy_world()
    for pid in (1, 2, 3):
        expected = world.gather_sense(pid)
        adapted = to_legacy_batch(observe(world, pid, RADIUS1))
        for key in ("cells", "neighborhood", "env"):
            assert adapted[key].dtype == expected[key].dtype, key
            assert np.array_equal(adapted[key], expected[key]), key
        assert adapted["tick"] == expected["tick"]
        assert adapted["constraints"] == expected["constraints"]


def test_legacy_adapter_uses_inner_window_for_larger_radius():
    world = busy_world()
    expected = world.gather_sense(2)
    adapted = to_legacy_batch(observe(world, 2, RADIUS2))
    assert np.array_equal(adapted["neighborhood"], expected["neighborhood"])
    assert np.array_equal(adapted["env"], expected["env"])


def composer(name):
    config = PRESETS[name]
    return lambda c, n, e, k, t: decide_with_config(config, c, n, e, k, t)


def step(world, deciders, manifest):
    intents, pids = [], []
    for pid, decide in deciders.items():
        if manifest is None:
            batch = world.gather_sense(pid)
            rows = to_intentions(decide(batch["cells"], batch["neighborhood"], batch["env"],
                                        batch["constraints"], batch["tick"]), batch["cells"])
        else:
            obs = observe(world, pid, manifest)
            batch = to_legacy_batch(obs)
            legacy = to_intentions(decide(batch["cells"], batch["neighborhood"], batch["env"],
                                          batch["constraints"], batch["tick"]), batch["cells"])
            rows = world.intentions_from_v2(pid, intentions_to_v2(legacy, obs))
        if len(rows):
            intents.append(rows)
            pids.append(np.full(len(rows), pid, dtype=np.int32))
    if intents:
        resolved = arbitrate(np.concatenate(intents), world, world.constraints,
                             tick=world.tick, player_ids=np.concatenate(pids))
        if len(resolved):
            world.apply_intentions(resolved, world.arrays.owner[resolved["src_y"], resolved["src_x"]])
    world.ecology()
    world.organisms.update(world.arrays, world.tick)
    if world.tick % 10 == 0:
        apply_world_params(world, {"food_regrow": 300, "food_regrow_near_cells": 30})
    world.tick += 1


def test_radius1_world_matches_legacy_tick_for_tick():
    deciders = {1: composer("spider"), 2: composer("hunter"), 3: composer("balanced")}
    legacy, radius = busy_world(), busy_world()
    bonded_ticks = 0
    for tick in range(80):
        step(legacy, deciders, None)
        step(radius, deciders, RADIUS1)
        for field in ("owner", "species", "cell_type", "state", "energy", "bonds",
                      "organism", "env_food"):
            assert np.array_equal(getattr(legacy.arrays, field), getattr(radius.arrays, field)), (tick, field)
        bonded_ticks += bool(radius.arrays.bonds.any())
    alive = [int((radius.arrays.owner == pid).sum()) for pid in deciders]
    assert all(count > 5 for count in alive), alive
    assert bonded_ticks > 40, bonded_ticks


# -- SDK -------------------------------------------------------------------------

SDK_RULE = '''
seen = []
def decide_cell(cell):
    here = cell.sense(0, 0)
    far = cell.sense(5, 5)
    count = cell.memory.get("count", 0) + 1
    cell.memory["count"] = count
    seen.append((cell.id, here.occupant, far, len(cell.percepts()), count))
    return cell.wait()
'''


def test_sdk_exposes_ids_percepts_and_memory():
    world = small_world()
    a = world.place_cell(1, 0, 0)
    b = world.place_cell(1, 7, 7)
    decide = load_rule(SDK_RULE)
    for _ in range(2):
        batch = to_legacy_batch(observe(world, 1, RADIUS2))
        decide(batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"],
               batch["tick"], observation=batch["observation"])
    world.arrays.energy[7, 7] = 0
    world.ecology()
    batch = to_legacy_batch(observe(world, 1, RADIUS2))
    decide(batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"],
           batch["tick"], observation=batch["observation"])
    seen = decide.rule_namespace["seen"]
    assert {row[0] for row in seen} == {a, b}
    corner = [row for row in seen if row[0] == a]
    assert corner[0][1] == MINE and corner[0][2] is None
    assert corner[0][3] == 9  # 25 offsets, 16 fall outside the world at the corner
    assert [row[4] for row in corner] == [1, 2, 3]
    assert [row[4] for row in seen if row[0] == b] == [1, 2]


MEMORY_RULE = '''
def decide_cell(cell):
    cell.memory["n"] = cell.memory.get("n", 0) + 1
    return cell.set_state(cell.memory["n"])
'''


def test_sdk_memory_resets_for_a_new_world_run():
    world = small_world()
    world.place_cell(1, 4, 4)
    decide = load_rule(MEMORY_RULE)
    rows = []
    for run in ("run-a", "run-a", "run-b"):
        batch = to_legacy_batch(observe(world, 1, RADIUS1, run))
        rows.append(int(decide(batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"],
                               batch["tick"], observation=batch["observation"])[0][6]))
    assert rows == [1, 2, 1], rows


def test_sdk_legacy_world_has_no_ids():
    world = small_world()
    world.place_cell(1, 3, 3)
    batch = world.gather_sense(1)
    decide = load_rule("def decide_cell(cell):\n    assert cell.id is None and cell.sense(0, 0) is None\n"
                       "    return cell.wait()\n")
    decide(batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"], batch["tick"])
    try:
        load_rule("def decide_cell(cell):\n    cell.memory\n")(
            batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"], batch["tick"])
    except RuntimeError as exc:
        assert "cell_id" in str(exc)
    else:
        raise AssertionError("memory should need cell ids")


def test_batch_rule_can_request_observation():
    world = small_world()
    world.place_cell(1, 3, 3)
    batch = to_legacy_batch(observe(world, 1, RADIUS2))
    decide = load_rule("got = []\ndef decide(cells, neighborhood, env, constraints, tick, observation=None):\n"
                       "    got.append(observation)\n    return []\n")
    decide(batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"], batch["tick"],
           observation=batch["observation"])
    assert decide.rule_namespace["got"][0] is batch["observation"]
    plain = load_rule("def decide(cells, neighborhood, env, constraints, tick):\n    return []\n")
    plain(batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"], batch["tick"],
          observation=batch["observation"])


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OBSERVATION V2 TEST PASSED")


if __name__ == "__main__":
    main()
