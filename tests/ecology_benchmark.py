"""Reproducible offline ecology benchmark using the real simulation pieces."""
import argparse
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.executor import to_intentions
from server.world import WorldState
from server.world_rules import WorldRuleEngine, apply_world_params
from shared.arbiter import arbitrate
from species.grazer import decide as grazer
from species.hunter import decide as hunter


def run(seed, ticks=200, metabolism_interval=10, local_food=None, world_rules_path=None):
    world = WorldState(seed=seed)
    world.constraints["metabolism_interval"] = metabolism_interval
    rules = WorldRuleEngine(world_rules_path or str(ROOT / "server" / "default_world_rules.py"))
    world.spawn_player(1, 1, count=20)
    world.spawn_player(2, 2, count=20)
    totals = {name: 0 for name in ("move", "eat", "reproduce", "attack", "death")}
    late = {name: 0 for name in totals}
    population = []
    for tick in range(ticks):
        # Server applies the previous decision, then ecology and epoch rules.
        if tick % 10 == 0:
            params, error = rules.on_epoch(world.summary(), tick)
            if error:
                raise RuntimeError(error)
            if local_food is not None:
                params["food_regrow_near_cells"] = local_food
            apply_world_params(world, params)
        intents, pids = [], []
        for pid, decide in ((1, grazer), (2, hunter)):
            batch = world.gather_sense(pid)
            result = decide(batch["cells"], batch["neighborhood"], batch["env"],
                            batch["constraints"], tick)
            array = to_intentions(result, batch["cells"])
            if len(array):
                intents.append(array)
                pids.append(np.full(len(array), pid, dtype=np.int32))
        if intents:
            combined = np.concatenate(intents)
            resolved = arbitrate(combined, world, world.constraints, tick=tick + 1,
                                 player_ids=np.concatenate(pids))
            counts = world.apply_intentions(resolved)
            for action in ("move", "eat", "reproduce", "attack"):
                totals[action] += counts[action]
                if tick >= ticks // 2:
                    late[action] += counts[action]
        world.tick = tick + 1
        deaths = world.ecology()
        totals["death"] += deaths
        if tick >= ticks // 2:
            late["death"] += deaths
        population.append(int((world.arrays.owner != 0).sum()))
    return population, totals, late


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--metabolism", type=int, default=10)
    ap.add_argument("--local-food", type=int, default=None)
    ap.add_argument("--rules", default=None, help="path to world rules file")
    args = ap.parse_args()
    for seed in range(args.seeds):
        population, totals, late = run(seed, args.ticks, args.metabolism, args.local_food, args.rules)
        points = {t: population[t - 1] for t in (20, 50, 100, 200) if t <= args.ticks}
        print(f"seed={seed} population={points} actions={totals} second_half={late}")
