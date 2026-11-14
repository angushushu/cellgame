"""M2: roles, blanket perception, visibility, role metabolism, action rules,
the sense action, and per-player action events."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cellgame.server.perception import gather_observation
from cellgame.server.sim_process import resolve_tick
from cellgame.server.world import WorldState
from cellgame.shared.arbiter import arbitrate
from cellgame.shared.manifest import ManifestError, build_manifest, compile_rules
from cellgame.shared.models import INTENTION_DTYPE, Action
from cellgame.shared.observation import (
    BOUNDARY, DIED_ATTACK, DIED_STARVED, EVENT_BORN, EVENT_DIED, EVENT_RESULT, HIDDEN, INTERIOR,
    MINE, MINE_BONDED, OTHER, R_BLOCKED, R_CONTESTED, R_DISABLED, R_DUPLICATE, R_INVALID,
    R_NO_ENERGY, R_OK, R_ROLE, expand_observation, to_legacy_batch,
)

BLANKET = {"perception": {"model": "blanket", "external_radius": 1}}


def expect_error(overrides, fragment):
    try:
        build_manifest(overrides)
    except ManifestError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"expected ManifestError for {overrides!r}")


def world_with(manifest_overrides=None, size=24):
    world = WorldState(size, size, seed=1)
    world.arrays.env_food[:] = 0
    world.configure(build_manifest(manifest_overrides or BLANKET))
    return world


def block(world, pid, x0, y0, side, energy=20):
    """A fully bonded side x side square of cells; returns {(x, y): cell_id}."""
    ids = {}
    for y in range(y0, y0 + side):
        for x in range(x0, x0 + side):
            ids[(x, y)] = world.place_cell(pid, x, y, energy=energy)
    for (x, y) in ids:
        for dx, dy in ((1, 0), (0, 1), (1, 1), (-1, 1)):
            if (x + dx, y + dy) in ids:
                world._set_bond(x, y, x + dx, y + dy, True)
    return ids


def intents(*rows):
    arr = np.zeros(len(rows), dtype=INTENTION_DTYPE)
    for i, row in enumerate(rows):
        arr[i] = row
    return arr


def observe(world, pid):
    manifest = world.manifest
    return expand_observation(gather_observation(world, pid, manifest), manifest)


def percepts_of(obs, cell_id):
    row = int(np.where(obs["cells"]["cell_id"] == cell_id)[0][0])
    p = obs["percepts"]
    return {(int(r["dx"]), int(r["dy"])): r for r in p[p["observer"] == row]}


# -- manifest ------------------------------------------------------------------

def test_manifest_blanket_and_sections():
    m = build_manifest({
        "perception": {"model": "blanket", "external_radius": 2},
        "visibility": {"others_interior": "hidden", "state": "boundary_only", "spectator": "none"},
        "ecology": {"metabolism": {"boundary": 2, "interior": 1}},
        "actions": {"sense": {"enabled": True, "cost_per_radius": 2, "max_radius": 4},
                    "eat": {"actor_roles": ["boundary"]}},
    })
    assert m["perception"] == {"model": "blanket", "external_radius": 2, "metric": "chebyshev"}
    assert m["observation"]["version"] == 2
    sense = next(a for a in m["actions"] if a["name"] == "sense")
    assert sense["enabled"] and sense["actor_roles"] == ["boundary"] and sense["max_radius"] == 4
    rules = compile_rules(m)
    assert rules.needs_roles and rules.sense_cost_per_radius == 2
    assert int(Action.SENSE) in rules.enabled and int(Action.ATTACK) in rules.enabled


def test_manifest_defaults_keep_legacy_rules():
    m = build_manifest()
    sense = next(a for a in m["actions"] if a["name"] == "sense")
    assert not sense["enabled"]
    assert m["visibility"]["spectator"] == "full"
    assert m["ecology"]["metabolism"] == {"boundary": 1, "interior": 1}
    rules = compile_rules(m)
    assert not rules.needs_roles and int(Action.SENSE) not in rules.enabled


def test_manifest_rejects_bad_m2_overrides():
    expect_error({"perception": {"model": "blanket", "external_radius": 0}}, "external_radius")
    expect_error({"perception": {"model": "blanket", "radius": 2}}, "radius")
    expect_error({"visibility": {"state": "boundary_only"}}, "legacy")
    expect_error({**BLANKET, "visibility": {"state": "sometimes"}}, "state")
    expect_error({**BLANKET, "visibility": {"xray": True}}, "xray")
    expect_error({"actions": {"sense": {"enabled": True}}}, "legacy")
    expect_error({**BLANKET, "actions": {"teleport": {}}}, "teleport")
    expect_error({**BLANKET, "actions": {"eat": {"actor_roles": []}}}, "actor_roles")
    expect_error({**BLANKET, "actions": {"eat": {"target_roles": ["boundary"]}}}, "target_roles")
    expect_error({**BLANKET, "actions": {"sense": {"max_radius": 9}}}, "max_radius")
    expect_error({**BLANKET, "actions": {"move": {"enabled": "yes"}}}, "enabled")
    expect_error({**BLANKET, "ecology": {"metabolism": {"boundary": 11}}}, "boundary")
    expect_error({**BLANKET, "ecology": {"rain": 1}}, "rain")


# -- roles and metabolism ------------------------------------------------------

def test_roles_follow_bond_topology():
    world = world_with()
    ids = block(world, 1, 5, 5, 5)
    loner = world.place_cell(1, 15, 15)
    edge = block(world, 1, 0, 0, 3)
    roles = world.roles()
    for (x, y) in ids:
        inner = 6 <= x <= 8 and 6 <= y <= 8
        assert roles[y, x] == (INTERIOR if inner else BOUNDARY), (x, y)
    assert roles[15, 15] == BOUNDARY and loner
    assert roles[1, 1] == INTERIOR and all(roles[y, x] == BOUNDARY for (x, y) in edge if (x, y) != (1, 1))
    assert roles[0, 23] == 0


def test_world_edge_counts_as_outside():
    world = world_with()
    block(world, 1, 0, 0, 2)
    assert (world.roles()[0:2, 0:2] == BOUNDARY).all()


def test_metabolism_by_role():
    world = world_with({**BLANKET, "ecology": {"metabolism": {"boundary": 3, "interior": 0}}})
    block(world, 1, 5, 5, 3, energy=10)
    world.tick = world.constraints["metabolism_interval"]
    world.ecology()
    assert world.arrays.energy[6, 6] == 10
    assert world.arrays.energy[5, 5] == 7 and world.arrays.energy[7, 6] == 7


# -- action rules and reasons ----------------------------------------------------

def run(world, rows, pids):
    report = {}
    resolved = arbitrate(rows, world, world.constraints, tick=world.tick,
                         player_ids=np.asarray(pids, dtype=np.int32), report=report)
    return resolved, report["reasons"]


def test_disabled_and_role_restricted_actions():
    world = world_with({**BLANKET,
                        "actions": {"attack": {"enabled": False}, "eat": {"actor_roles": ["boundary"]}}})
    block(world, 1, 5, 5, 3)
    world.arrays.env_food[5:8, 5:8] = 5
    world.place_cell(2, 9, 6, energy=1)
    _, reasons = run(world, intents((6, 6, 6, 6, Action.EAT, 0, 0),
                                    (5, 5, 5, 5, Action.EAT, 0, 0),
                                    (7, 6, 8, 6, Action.ATTACK, 0, 0)), [1, 1, 1])
    assert reasons.tolist() == [R_ROLE, R_OK, R_DISABLED]


def test_attack_targets_are_always_boundary_cells():
    """An attacker must be adjacent, which makes its target a boundary cell:
    interior cells are protected by geometry until the membrane is breached."""
    world = world_with(BLANKET)
    ids = block(world, 2, 5, 5, 3, energy=1)
    world.place_cell(1, 8, 6, energy=50)
    assert world.roles()[6, 6] == INTERIOR and world.roles()[6, 7] == BOUNDARY
    resolve_tick(world, {1: (intents((8, 6, 7, 6, Action.ATTACK, 0, 0)), np.array([1], np.int32))})
    assert world.arrays.owner[6, 7] == 0
    assert world.roles()[6, 6] == BOUNDARY and ids


def test_reason_codes():
    world = world_with(BLANKET)
    a = world.place_cell(1, 3, 3, energy=1)
    b = world.place_cell(1, 5, 5, energy=20)
    c = world.place_cell(1, 7, 5, energy=20)
    world.place_cell(2, 10, 10, energy=20)
    world.place_cell(2, 11, 10, energy=20)
    assert a and b and c
    rows = intents((3, 3, 4, 3, Action.MOVE, 0, 0),        # not enough energy
                   (5, 5, 6, 5, Action.MOVE, 0, 0),        # contested with c
                   (5, 5, 5, 5, Action.EAT, 0, 0),         # duplicate for b
                   (7, 5, 6, 5, Action.MOVE, 0, 0),
                   (10, 10, 11, 10, Action.MOVE, 0, 0),    # target occupied
                   (10, 10, 12, 10, Action.MOVE, 0, 0))    # not adjacent
    _, reasons = run(world, rows, [1, 1, 1, 1, 2, 2])
    assert reasons[0] == R_NO_ENERGY
    assert sorted([reasons[1], reasons[3]]) == [R_OK, R_CONTESTED]
    assert reasons[2] == R_DUPLICATE
    assert reasons[4] == R_BLOCKED
    assert reasons[5] == R_INVALID


def test_sense_action_costs_energy_and_boosts_next_observation():
    world = world_with({**BLANKET, "actions": {"sense": {"enabled": True, "cost_per_radius": 2, "max_radius": 4}}})
    cid = world.place_cell(1, 10, 10, energy=20)
    resolve_tick(world, {1: (intents((10, 10, 10, 10, Action.SENSE, 0, 3)), np.array([1], np.int32))})
    assert world.arrays.energy[10, 10] == 14
    obs = observe(world, 1)
    assert int(obs["cells"]["sense_radius"][0]) == 3 and len(percepts_of(obs, cid)) == 49
    world.end_observation_window()
    obs = observe(world, 1)
    assert int(obs["cells"]["sense_radius"][0]) == 1 and len(percepts_of(obs, cid)) == 9
    _, reasons = run(world, intents((10, 10, 10, 10, Action.SENSE, 0, 5)), [1])
    assert reasons.tolist() == [R_INVALID]


def test_sense_survives_v2_and_legacy_row_conversion():
    from cellgame.client.executor import to_intentions
    world = world_with({**BLANKET, "actions": {"sense": {"enabled": True}}})
    cid = world.place_cell(1, 10, 10, energy=20)
    assert len(world.intentions_from_v2(1, [[cid, int(Action.SENSE), 0, 0, 2]])) == 1
    assert len(to_intentions([[10, 10, 10, 10, int(Action.SENSE), 0, 2]], np.array([[10, 10, 0, 0, 20]]))) == 1


def test_sense_is_disabled_in_legacy_rules():
    world = WorldState(16, 16, seed=0)
    world.place_cell(1, 4, 4, energy=20)
    _, reasons = run(world, intents((4, 4, 4, 4, Action.SENSE, 0, 2)), [1])
    assert reasons.tolist() == [R_DISABLED]


# -- events --------------------------------------------------------------------

def test_events_report_results_births_and_deaths():
    world = world_with(BLANKET)
    parent = world.place_cell(1, 5, 5, energy=20)
    starving = world.place_cell(1, 15, 15, energy=1)
    prey = world.place_cell(2, 9, 9, energy=1)
    hunter = world.place_cell(1, 8, 9, energy=30)
    world.arrays.energy[15, 15] = 0
    pending = {1: (intents((5, 5, 6, 5, Action.REPRODUCE, 0, 0), (8, 9, 9, 9, Action.ATTACK, 0, 0)),
                   np.array([1, 1], np.int32))}
    resolve_tick(world, pending)
    events = gather_observation(world, 1, world.manifest)["events"]
    results = {(int(e["cell_id"]), int(e["action"])): int(e["code"]) for e in events if e["kind"] == EVENT_RESULT}
    assert results == {(parent, int(Action.REPRODUCE)): R_OK, (hunter, int(Action.ATTACK)): R_OK}
    born = [e for e in events if e["kind"] == EVENT_BORN]
    assert len(born) == 1 and int(born[0]["other"]) == parent and int(born[0]["cell_id"]) == int(world.arrays.cell_id[5, 6])
    died = {int(e["cell_id"]): int(e["code"]) for e in events if e["kind"] == EVENT_DIED}
    assert died == {starving: DIED_STARVED}
    victim_events = gather_observation(world, 2, world.manifest)["events"]
    assert [(int(e["kind"]), int(e["cell_id"]), int(e["code"])) for e in victim_events] == [(EVENT_DIED, prey, DIED_ATTACK)]
    world.end_observation_window()
    assert len(gather_observation(world, 1, world.manifest)["events"]) == 0


# -- blanket perception and visibility -------------------------------------------

def test_blanket_perception_by_role():
    world = world_with(BLANKET)
    ids = block(world, 1, 5, 5, 5)
    world.arrays.env_food[7, 7] = 9  # under the deep interior cell
    world.arrays.env_food[4, 4] = 3  # outside, next to the corner
    obs = observe(world, 1)
    cells = obs["cells"]
    centre, corner = ids[(7, 7)], ids[(5, 5)]
    roles = dict(zip(cells["cell_id"].tolist(), cells["role"].tolist()))
    assert roles[centre] == INTERIOR and roles[corner] == BOUNDARY
    inner = percepts_of(obs, centre)
    assert set(inner) == {(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    assert all(r["occupant"] in (MINE, MINE_BONDED) for r in inner.values())
    assert not inner[(0, 0)]["env_visible"] and inner[(0, 0)]["food"] == -1
    outer = percepts_of(obs, corner)
    assert len(outer) == 9 and outer[(-1, -1)]["env_visible"] and outer[(-1, -1)]["food"] == 3
    # The wire never carries the hidden food value.
    tiles = gather_observation(world, 1, world.manifest)["tiles"]
    hidden = tiles[(tiles["x"] == 7) & (tiles["y"] == 7)][0]
    assert hidden["food"] == -1 and not hidden["env_visible"]


def test_interior_with_partial_bonds_sees_only_bonded_neighbors():
    world = world_with(BLANKET)
    ids = block(world, 1, 5, 5, 3)
    world._set_bond(6, 6, 7, 7, False)
    obs = observe(world, 1)
    seen = percepts_of(obs, ids[(6, 6)])
    assert (1, 1) not in seen and (0, 0) in seen and len(seen) == 8


def test_visibility_hides_other_interiors():
    world = world_with({"perception": {"model": "blanket", "external_radius": 3},
                        "visibility": {"others_interior": "hidden", "state": "boundary_only"}})
    theirs = block(world, 2, 10, 5, 3, energy=17)
    world.arrays.state[5, 10] = 42
    world.arrays.state[6, 11] = 99
    mine = world.place_cell(1, 8, 6, energy=20)
    seen = percepts_of(observe(world, 1), mine)
    interior = seen[(3, 0)]
    assert interior["occupant"] == HIDDEN and interior["energy"] == -1 and interior["state"] == -1
    assert interior["species"] == -1
    edge = seen[(2, -1)]
    assert edge["occupant"] == OTHER and edge["state"] == 42 and edge["energy"] == 17
    assert theirs


def test_legacy_adapter_hides_unknown_food_as_zero():
    world = world_with(BLANKET)
    ids = block(world, 1, 5, 5, 5)
    world.arrays.env_food[7, 7] = 9
    batch = to_legacy_batch(observe(world, 1))
    row = int(np.where(batch["observation"]["cells"]["cell_id"] == ids[(7, 7)])[0][0])
    assert batch["env"][row, 1] == 0


SDK_RULE = """
seen = {}
def decide_cell(cell):
    hidden = [p for p in cell.percepts() if not p.env_visible]
    seen[cell.id] = (cell.role, cell.last_result, len(hidden))
    if cell.role == "boundary":
        return cell.move((1, 0))
    return cell.wait()
"""


def test_sdk_exposes_roles_results_and_hidden_layers():
    from cellgame.client.rule_loader import load_rule
    from cellgame.client.executor import to_intentions
    from cellgame.shared.observation import intentions_to_v2
    world = world_with(BLANKET)
    ids = block(world, 1, 5, 5, 5)
    decide = load_rule(SDK_RULE)
    for _ in range(2):
        obs = observe(world, 1)
        world.end_observation_window()  # as the sim does after observing everyone
        batch = to_legacy_batch(obs)
        rows = to_intentions(decide(batch["cells"], batch["neighborhood"], batch["env"],
                                    batch["constraints"], batch["tick"], observation=obs), batch["cells"])
        resolve_tick(world, {1: (world.intentions_from_v2(1, intentions_to_v2(rows, obs)),
                                 np.full(len(rows), 1, np.int32))})
    seen = decide.rule_namespace["seen"]
    assert seen[ids[(7, 7)]][0] == "interior" and seen[ids[(7, 7)]][2] >= 1
    assert seen[ids[(5, 5)]][0] == "boundary"
    # Bonded cells cannot MOVE, so every boundary move was blocked.
    assert seen[ids[(5, 5)]][1] == "blocked"
    assert seen[ids[(7, 7)]][1] is None


def test_known_map_fades_old_tiles_and_drops_own_ghosts():
    from cellgame.shared.models import WorldArrays
    from cellgame.shared.observation import observation_to_world, remember
    world = world_with(BLANKET)
    a = world.place_cell(1, 3, 3)
    world.place_cell(1, 15, 15)
    world.place_cell(2, 4, 4)
    known, seen = WorldArrays(24, 24), np.zeros((24, 24), dtype=np.uint8)
    wire = gather_observation(world, 1, world.manifest)
    remember(known, seen, observation_to_world(wire, 1, 24, 24), wire, 1)
    assert seen[3, 3] == 1 and known.owner[4, 4] == 2 and seen[10, 10] == 0
    world.arrays.energy[3, 3] = 0   # our cell at (3, 3) starves; nobody sees that corner now
    world.ecology()
    wire = gather_observation(world, 1, world.manifest)
    remember(known, seen, observation_to_world(wire, 1, 24, 24), wire, 1)
    assert seen[4, 4] == 2 and known.owner[4, 4] == 2      # the enemy is remembered, faded
    assert seen[3, 3] == 2 and known.owner[3, 3] == 0      # our dead cell is not a ghost
    assert a


# -- review regressions ------------------------------------------------------------

def test_events_survive_json_for_controllers():
    import json
    from cellgame.shared.observation import observation_to_json
    world = world_with(BLANKET)
    world.place_cell(1, 5, 5, energy=20)
    resolve_tick(world, {1: (intents((5, 5, 6, 5, Action.REPRODUCE, 0, 0)), np.array([1], np.int32))})
    data = observation_to_json(gather_observation(world, 1, world.manifest))
    text = json.dumps(data)
    assert data["events"]["columns"][:2] == ["kind", "cell_id"] and len(data["events"]["rows"]) == 2 and text


def test_blanket_interior_cannot_eat_by_default():
    world = world_with(BLANKET)
    block(world, 1, 5, 5, 3)
    world.arrays.env_food[6, 6] = 5
    _, reasons = run(world, intents((6, 6, 6, 6, Action.EAT, 0, 0)), [1])
    assert reasons.tolist() == [R_ROLE]
    eat = next(a for a in world.manifest["actions"] if a["name"] == "eat")
    assert eat["actor_roles"] == ["boundary"]
    opted_in = build_manifest({**BLANKET, "actions": {"eat": {"actor_roles": ["boundary", "interior"]}}})
    assert next(a for a in opted_in["actions"] if a["name"] == "eat")["actor_roles"] == ["boundary", "interior"]


def test_blanket_sense_rejects_interior_actors():
    expect_error({**BLANKET, "actions": {"sense": {"enabled": True, "actor_roles": ["interior"]}}}, "interior")


def test_interior_observers_never_see_resource_layers():
    world = world_with(BLANKET)
    ids = block(world, 1, 5, 5, 5)
    world.arrays.env_food[5, 5] = 4   # under a boundary cell, inside some boundary windows
    seen = percepts_of(observe(world, 1), ids[(6, 6)])
    corner = seen[(-1, -1)]
    assert corner["occupant"] == MINE_BONDED and not corner["env_visible"] and corner["food"] == -1


def test_radius_world_with_role_rules_reports_roles():
    world = world_with({"perception": {"model": "radius", "radius": 1},
                        "ecology": {"metabolism": {"boundary": 2, "interior": 1}}})
    ids = block(world, 1, 5, 5, 3)
    obs = observe(world, 1)
    roles = dict(zip(obs["cells"]["cell_id"].tolist(), obs["cells"]["role"].tolist()))
    assert roles[ids[(6, 6)]] == INTERIOR and roles[ids[(5, 5)]] == BOUNDARY
    assert len(percepts_of(obs, ids[(6, 6)])) == 9   # radius worlds keep the full window


def test_group_move_followers_are_contested_not_interrupted():
    world = world_with(BLANKET)
    a = world.place_cell(1, 4, 4, energy=20)
    b = world.place_cell(1, 5, 4, energy=20)
    world._set_bond(4, 4, 5, 4, True)
    resolve_tick(world, {1: (intents((4, 4, 4, 5, Action.MOVE_GROUP, 0, 0), (5, 4, 5, 3, Action.MOVE_GROUP, 0, 0)),
                             np.array([1, 1], np.int32))})
    events = gather_observation(world, 1, world.manifest)["events"]
    codes = {int(e["cell_id"]): int(e["code"]) for e in events if e["kind"] == EVENT_RESULT}
    assert codes == {a: R_OK, b: R_CONTESTED}, codes


def test_deep_dive_keeps_its_map_from_spectators():
    from cellgame.server.main import resolve_manifest
    manifest = resolve_manifest(str(Path(__file__).resolve().parents[1] / "server" / "worlds" / "deep_dive.py"))
    assert manifest["visibility"]["spectator"] == "none"
    assert manifest["combat"]["bonded_support_percent"] == 50


def test_example_species_play_deep_dive_together():
    """species/swarm, blob, sensing_forager and predator run without errors."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import blanket_experiment as experiment
    manifest, rules = experiment.variant("deep-dive")
    alive, stats = experiment.run(manifest, rules, list(experiment.SPECIES), seed=0, ticks=25)
    assert all(count > 0 for count in alive), alive
    assert stats["sense"] > 0, stats
    # Bodies need time to close around an interior; check the blob on its own.
    _, blob = experiment.run(manifest, rules, ["blob"], seed=0, ticks=100)  # first interiors: tick 60-90
    assert blob["interior"] > 0, blob


def test_bonded_support_strengthens_bodies():
    for support, landed in ((0, True), (50, False)):
        world = world_with({**BLANKET, "combat": {"bonded_support_percent": support}})
        block(world, 2, 5, 5, 3, energy=6)          # (7, 6) has 5 bonded neighbours of energy 6
        world.place_cell(1, 8, 6, energy=10)
        _, reasons = run(world, intents((8, 6, 7, 6, Action.ATTACK, 0, 0)), [1])
        assert reasons.tolist() == ([R_OK] if landed else [R_BLOCKED]), (support, reasons)
        resolve_tick(world, {1: (intents((8, 6, 7, 6, Action.ATTACK, 0, 0)), np.array([1], np.int32))})
        assert (world.arrays.owner[6, 7] == 0) == landed, support


def test_combat_section_validation():
    assert build_manifest()["combat"] == {"bonded_support_percent": 0}
    expect_error({"combat": {"bonded_support_percent": 101}}, "bonded_support_percent")
    expect_error({"combat": {"armor": 1}}, "armor")


def test_client_animation_events_from_observations():
    from cellgame.shared.observation import visual_events
    world = world_with(BLANKET)
    world.place_cell(1, 5, 5, energy=20)
    world.place_cell(1, 9, 9, energy=20)
    starving = world.place_cell(1, 15, 15, energy=1)
    world.arrays.env_food[9, 9] = 5
    before = gather_observation(world, 1, world.manifest)["cells"]
    world.arrays.energy[15, 15] = 0
    resolve_tick(world, {1: (intents((5, 5, 6, 5, Action.MOVE, 0, 0), (9, 9, 9, 9, Action.EAT, 0, 0)),
                             np.array([1, 1], np.int32))})
    events = visual_events(before, gather_observation(world, 1, world.manifest), 1)
    kinds = sorted((e[0], tuple(e[1:5])) for e in events)
    assert kinds == [("death", (15, 15, 15, 15)), ("eat", (9, 9, 9, 9)), ("move", (5, 5, 6, 5))], kinds
    assert starving and all(e[5] == 1 for e in events)


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("BLANKET TEST PASSED")


if __name__ == "__main__":
    main()
