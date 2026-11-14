"""Strategy balance experiment for blanket worlds (docs/WORLD_MANIFEST_zh.md §12, §15).

Four probe species share one economy (eat up to 25, reproduce at 14, step only
above 6 energy) and differ in a single strategic trait:
  swarm     species/swarm.py           blind, unbonded, wanders
  blob      species/blob.py            bonded body with an interior, sessile
  sensing   species/sensing_forager.py pays to see further, remembers targets
  predator  species/predator.py        attacks weaker neighbouring enemies
Each species runs alone, then all four together, in several world variants.
"Alone" measures whether a strategy is viable; "together" measures who wins.
This is a measurement script, not a pass/fail test.

Usage: python tests/blanket_experiment.py [--ticks 240] [--seeds 3] [--worlds a,b]
"""
import argparse
import copy
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cellgame.client.executor import to_intentions
from cellgame.client.rule_loader import load_rule
from cellgame.server.perception import gather_observation
from cellgame.server.sim_process import resolve_tick
from cellgame.server.world import WorldState
from cellgame.server.world_rules import apply_world_params, run_tick_event
from cellgame.server.worlds import deep_dive
from cellgame.shared.manifest import build_manifest
from cellgame.shared.observation import (
    BOUNDARY, DIED_ATTACK, EVENT_DIED, INTERIOR, expand_observation, intentions_to_v2, to_legacy_batch,
)
from cellgame.species import simple as sdk

SPECIES = {name: (ROOT / "species" / f"{file}.py").read_text(encoding="utf-8")
           for name, file in (("swarm", "swarm"), ("blob", "blob"),
                              ("sensing", "sensing_forager"), ("predator", "predator"),
                              ("stalker", "stalker"))}
DEFAULT_SPECIES = "swarm,blob,sensing,stalker"

# name -> (manifest changes, food changes); applied on top of the deep-dive preset.
WORLDS = {
    "deep-dive": ({}, {}),
    "free-sense": ({"actions": {"sense": {"cost_per_radius": 0}}}, {}),
    "no-membrane": ({"ecology": {"metabolism": {"boundary": 1, "interior": 1}},
                     "actions": {"eat": {"actor_roles": ["boundary", "interior"]}}}, {}),
    "scattered": ({}, {"food_regrow": 400, "food_regrow_near_cells": 40, "zone_drops": 0}),
    "predation": ({}, {"attack_reward_percent": 100, "attack_cost": 1}),
    "cheap-interior": ({"ecology": {"metabolism": {"boundary": 2, "interior": 0}}}, {}),
    "famine": ({}, {"food_regrow": 60, "food_regrow_near_cells": 10}),
    "famine-cheap": ({"ecology": {"metabolism": {"boundary": 2, "interior": 0}}},
                     {"food_regrow": 60, "food_regrow_near_cells": 10}),
    "radius": ({"perception": {"model": "radius", "radius": 1}}, {}),
    # deep-dive's bodies defend with 50% of their bonded neighbours' energy;
    # these compare that with no support and with full support.
    "no-support": ({"combat": {"bonded_support_percent": 0}}, {}),
    "no-support-pred": ({"combat": {"bonded_support_percent": 0}},
                        {"attack_reward_percent": 100, "attack_cost": 1}),
    "support30": ({"combat": {"bonded_support_percent": 30}}, {}),
    "cohesion100": ({"combat": {"bonded_support_percent": 100}}, {}),
    "cohesion100-pred": ({"combat": {"bonded_support_percent": 100}},
                         {"attack_reward_percent": 100, "attack_cost": 1}),
}
# Keys of the second element that are world parameters rather than food knobs.
WORLD_PARAMETER_KEYS = ("attack_reward_percent", "attack_cost", "move_cost", "reproduce_cost")


class Rules:
    """deep_dive's world rules with adjustable food (no file re-execution)."""

    def __init__(self, food):
        self.food = {"food_regrow": None, "food_regrow_near_cells": None,
                     "zone_drops": deep_dive.ZONE_DROPS, **food}

    def on_epoch(self, summary, tick):
        params = deep_dive.on_epoch(summary, tick)
        params.update({k: v for k, v in self.food.items()
                       if (k.startswith("food_") or k in WORLD_PARAMETER_KEYS) and v is not None})
        return params, None

    def on_event(self, event, view):
        commands = deep_dive.on_event(event, view)
        return commands[:self.food["zone_drops"]], None


def merge(base, changes):
    out = copy.deepcopy(base)
    for key, value in changes.items():
        out[key] = merge(out.get(key, {}), value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def variant(name):
    manifest_changes, food = WORLDS[name]
    m = merge(deep_dive.MANIFEST, manifest_changes)
    if "perception" in manifest_changes:
        m["perception"] = manifest_changes["perception"]  # replace, never merge models
    if m["perception"]["model"] == "radius":
        m = {"id": "radius-control", "world": m["world"], "perception": m["perception"]}
    return build_manifest(m), Rules(food)


def run(manifest, rules, species_names, seed, ticks):
    w, h = manifest["world"]["width"], manifest["world"]["height"]
    world = WorldState(w, h, seed=seed)
    world.configure(manifest)
    deciders = {}
    for pid, name in enumerate(species_names, start=1):
        world.spawn_player(pid, pid, count=20, seed=seed * 31 + pid)
        deciders[pid] = load_rule(SPECIES[name])
    pending, stats, memories = {}, {"sense": 0, "attack": 0, "interior": 0}, {}
    # Per player: cells lost to attacks, and boundary / interior cell-ticks.
    exposure = {pid: {"killed": 0, "boundary": 0, "interior": 0} for pid in deciders}
    for _ in range(ticks):
        counts = resolve_tick(world, pending)
        stats["sense"] += counts.get("sense", 0)
        stats["attack"] += counts.get("attack", 0)
        run_tick_event(world, rules, dict(counts, ecology_deaths=world._last_ecology))
        if world.tick % 10 == 0:
            apply_world_params(world, rules.on_epoch(world.summary(), world.tick)[0])
        if world.rules.needs_roles:
            roles = world.roles()
            stats["interior"] += int((roles == INTERIOR).sum())
            for pid in deciders:
                mine = world.arrays.owner == pid
                exposure[pid]["boundary"] += int((mine & (roles == BOUNDARY)).sum())
                exposure[pid]["interior"] += int((mine & (roles == INTERIOR)).sum())
        for pid, events in world.player_events.items():
            exposure.get(pid, {})["killed"] = exposure.get(pid, {}).get("killed", 0) + sum(
                1 for e in events if e[0] == EVENT_DIED and e[3] == DIED_ATTACK)
        pending = {}
        for pid, decide in deciders.items():
            # Each player normally runs in its own process; give each its own
            # cell.memory store so one player's pruning cannot erase another's.
            sdk._MEMORY = memories.setdefault(pid, {})
            obs = expand_observation(gather_observation(world, pid, manifest), manifest)
            batch = to_legacy_batch(obs)
            rows = to_intentions(decide(batch["cells"], batch["neighborhood"], batch["env"],
                                        batch["constraints"], batch["tick"], observation=obs),
                                 batch["cells"], w, h)
            v2 = world.intentions_from_v2(pid, intentions_to_v2(rows, obs))
            if len(v2):
                pending[pid] = (v2, np.full(len(v2), pid, dtype=np.int32))
        world.end_observation_window()
        world.organisms.update(world.arrays, world.tick)
        world.tick += 1
    alive = [int((world.arrays.owner == pid).sum()) for pid in deciders]
    stats = {k: v / ticks for k, v in stats.items()}
    stats["exposure"] = [exposure[pid] for pid in deciders]
    return alive, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=240)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--worlds", default=",".join(WORLDS))
    parser.add_argument("--species", default=DEFAULT_SPECIES)
    parser.add_argument("--versus", metavar="HUNTER",
                        help="instead of the full table, pit HUNTER against each other species one "
                             "at a time and report the prey's losses")
    parser.add_argument("--predation", action="store_true",
                        help="also print, per species in the mixed runs, cells killed by attacks "
                             "and kills per 1000 boundary cell-ticks")
    args = parser.parse_args()
    names = args.species.split(",")
    if args.versus:
        return versus(args, [n for n in names if n != args.versus])
    print(f"{args.ticks} ticks, seeds 0..{args.seeds - 1}; live cells at the end (mean)\n")
    print(f"{'world':<12}" + "".join(f"{n:>9}" for n in names) + "  | together " + "/".join(names)
          + "  | mixed winners")
    for world_name in args.worlds.split(","):
        manifest, rules = variant(world_name)
        started = time.monotonic()
        solo, notes = [], []
        for name in names:
            results = [run(manifest, rules, [name], seed, args.ticks) for seed in range(args.seeds)]
            solo.append(np.mean([r[0][0] for r in results]))
            if name == "blob":
                notes.append(f"blob interior {np.mean([r[1]['interior'] for r in results]):.1f}")
        mixed = [run(manifest, rules, names, seed, args.ticks) for seed in range(args.seeds)]
        together = np.mean([m[0] for m in mixed], axis=0)
        winners = [names[int(np.argmax(m[0]))] if max(m[0]) else "-" for m in mixed]
        notes.append(f"attacks/tick {np.mean([m[1]['attack'] for m in mixed]):.1f}")
        print(f"{world_name:<12}" + "".join(f"{v:>9.1f}" for v in solo)
              + "  | " + "/".join(f"{v:.0f}" for v in together)
              + "  | " + ",".join(winners)
              + f"  ({'; '.join(notes)}; {time.monotonic() - started:.0f}s)", flush=True)
        if args.predation:
            print("    killed: " + "  ".join(
                f"{n} {np.mean([m[1]['exposure'][i]['killed'] for m in mixed]):.0f}"
                f" ({1000 * sum(m[1]['exposure'][i]['killed'] for m in mixed) / max(1, sum(m[1]['exposure'][i]['boundary'] for m in mixed)):.1f}/k)"
                for i, n in enumerate(names)), flush=True)


def versus(args, prey_names):
    """Head-to-head: the hunter against one prey species at a time.

    Reports, per prey: live cells alone and with the hunter, cells killed by
    attacks, kills per 1000 prey cell-ticks, kills per 1000 boundary cell-ticks
    (blanket worlds), and the hunter's own live cells.
    """
    hunter = args.versus
    print(f"{hunter} vs each prey; {args.ticks} ticks, seeds 0..{args.seeds - 1}")
    print()
    print(f"{'world':<12}{'prey':<9}{'alone':>7}{'w/ hunter':>11}{'killed':>8}"
          f"{'kill/k cell':>13}{'kill/k bnd':>12}{'hunter':>8}")
    for world_name in args.worlds.split(","):
        manifest, rules = variant(world_name)
        for prey in prey_names:
            alone = np.mean([run(manifest, rules, [prey], s, args.ticks)[0][0] for s in range(args.seeds)])
            duel = [run(manifest, rules, [prey, hunter], s, args.ticks) for s in range(args.seeds)]
            killed = sum(d[1]["exposure"][0]["killed"] for d in duel)
            cells = sum(d[1]["exposure"][0]["boundary"] + d[1]["exposure"][0]["interior"] for d in duel)
            boundary = sum(d[1]["exposure"][0]["boundary"] for d in duel)
            print(f"{world_name:<12}{prey:<9}{alone:>7.0f}{np.mean([d[0][0] for d in duel]):>11.0f}"
                  f"{killed / args.seeds:>8.0f}{1000 * killed / max(1, cells):>13.2f}"
                  f"{1000 * killed / max(1, boundary):>12.2f}{np.mean([d[0][1] for d in duel]):>8.0f}", flush=True)


if __name__ == "__main__":
    main()
