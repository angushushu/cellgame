"""Local 32x32 preview simulator (spec section 5.5).

Replays the server tick pipeline (same shared arbiter, same WorldState)
on a small grid so players can validate rules before uploading.
Runs one species (the player's) against food; optionally a second
species file can be loaded as a rival.
"""
import numpy as np
import os
import multiprocessing as mp
import copy
from cellgame.server.perception import gather_observation
from cellgame.shared.observation import expand_observation

from cellgame.server.kernel import resolve_tick
from cellgame.shared.models import INTENTION_DTYPE
from cellgame.server.world import WorldState
from cellgame.server.world_rules import WorldRuleEngine, apply_world_params, run_tick_event
from .executor import to_intentions
from .rule_loader import load_rule


def load_decide(source):
    return load_rule(source, "<preview_rules>")


def run_preview(source, ticks=200, size=32, rival_source=None, seed=0, world_rules_path=None):
    if not 1 <= ticks <= 1000 or not 4 <= size <= 256:
        raise ValueError("预览 tick 范围为 1–1000，地图大小范围为 4–256")
    world = WorldState(size, size, seed=seed)
    path = world_rules_path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "server", "default_world_rules.py")
    rules = WorldRuleEngine(path)
    if rules.ns.get("GENERATE_BLOCKS", True):
        world.seed_blocks(seed)
    manifest = copy.deepcopy(world.manifest)
    manifest["world"].update(width=size, height=size)
    world.configure(manifest)
    decide = load_decide(source)
    rival = load_decide(rival_source) if rival_source else None
    world.spawn_player(1, 1, count=15, seed=seed + 1)
    if rival is not None:
        world.spawn_player(2, 2, count=15, seed=seed + 2)

    population = []
    energy = []
    births = deaths = eats = attacks = 0
    previous_counts = {"move": 0, "attack": 0, "reproduce": 0, "eat": 0,
                       "change": 0, "state": 0, "die": 0, "ecology_deaths": 0}
    for t in range(ticks):
        error = run_tick_event(world, rules, previous_counts)
        if error:
            raise RuntimeError("world event rules: " + error)
        if t % 10 == 0:
            params, err = rules.on_epoch(world.summary(), t)
            if err:
                raise RuntimeError("world rules: " + err)
            apply_world_params(world, params)
        intents, pids = [], []
        for pid, fn in ((1, decide), (2, rival)) if rival else ((1, decide),):
            batch = world.gather_sense(pid)
            if len(batch["cells"]) == 0:
                continue
            try:
                obs = expand_observation(gather_observation(world, pid, manifest, "preview"), manifest)
                out = fn(batch["cells"], batch["neighborhood"], batch["env"],
                         batch["constraints"], t, observation=obs)
            except Exception as exc:
                raise RuntimeError(f"规则在 tick {t} 出错: {type(exc).__name__}: {exc}") from exc
            arr = to_intentions(out)
            if len(arr):
                intents.append(arr)
                pids.append(np.full(len(arr), pid, dtype=np.int32))
        world.tick = t + 1
        pending = {}
        if intents:
            pending[0] = (np.concatenate(intents), np.concatenate(pids))
        counts = resolve_tick(world, pending, rules)
        births += counts["reproduce"]
        eats += counts["eat"]
        attacks += counts["attack"]
        ecology_deaths = world._last_ecology
        deaths += ecology_deaths
        world.end_observation_window()
        previous_counts = dict(counts, ecology_deaths=ecology_deaths)
        mask = world.arrays.owner == 1
        population.append(int(mask.sum()))
        energy.append(int(world.arrays.energy[mask].sum()) if mask.any() else 0)

    final = world.arrays
    return {
        "ticks": ticks,
        "size": size,
        "population": population,
        "energy": energy,
        "births": births,
        "deaths": deaths,
        "eats": eats,
        "attacks": attacks,
        "final_cells": int((final.owner == 1).sum()),
        "final_grid": {
            # species per cell, row-major, for the console mini-canvas
            "species": final.species.astype(np.int32).tolist(),
            "owner": final.owner.astype(np.int32).tolist(),
            "blocks": final.blocks.astype(np.uint8).tolist(),
        },
    }


def _preview_worker(connection, kwargs):
    try:
        connection.send((True, run_preview(**kwargs)))
    except BaseException as exc:
        connection.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def run_preview_isolated(source, ticks=200, timeout=20):
    """Run browser preview in a terminable worker; not a security sandbox."""
    context = mp.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_preview_worker,
                              args=(child, {"source": source, "ticks": ticks}), daemon=True)
    try:
        process.start()
        child.close()
        if not parent.poll(timeout):
            raise TimeoutError(f"预览超过 {timeout} 秒，已停止")
        ok, result = parent.recv()
        if not ok:
            raise RuntimeError(result)
        return result
    finally:
        child.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        parent.close()
