"""Transport- and GUI-independent authoritative tick phase.

Does not increment time, run epoch/on_event hooks, or handle sessions. Hosts
control those phases explicitly (see CORE_STANDARD_zh.md).
"""
import numpy as np
from cellgame.shared.arbiter import arbitrate
from cellgame.shared.observation import R_CONTESTED, R_INTERRUPTED, R_BLOCKED

EMPTY_COUNTS = {"move": 0, "attack": 0, "reproduce": 0, "eat": 0, "change": 0, "state": 0, "die": 0}


def resolve_tick(world, pending, world_rules=None):
    """Arbitrate and apply last window's intentions, record per-row results,
    then run the ecology step. Returns the action counts."""
    counts = dict(EMPTY_COUNTS)
    world.last_rule_events = []
    if pending:
        intents = np.concatenate([v[0] for v in pending.values()])
        pids = np.concatenate([v[1] for v in pending.values()])
        A = world.arrays
        sx = np.clip(intents["src_x"].astype(int), 0, world.w - 1)
        sy = np.clip(intents["src_y"].astype(int), 0, world.h - 1)
        own = (A.owner[sy, sx] == pids) & (sx == intents["src_x"]) & (sy == intents["src_y"])
        cell_ids = np.where(own, A.cell_id[sy, sx], 0)
        keep = np.ones(len(intents), dtype=bool)
        if world_rules is not None:
            from .world_rules import WorldView
            keep, error = world_rules.filter_actions(intents, pids, WorldView(world.arrays), world.tick)
            if error:
                raise RuntimeError("世界行动规则失败，模拟已停止：" + error)
        report = {}
        resolved = arbitrate(intents[keep], world, world.constraints, tick=world.tick,
                             player_ids=pids[keep], report=report)
        if len(resolved):
            owners = A.owner[resolved["src_y"], resolved["src_x"]]
            counts = world.apply_intentions(resolved, owners)
            report["reasons"][report["winners"][~world.last_applied]] = R_INTERRUPTED
            report["reasons"][report["winners"][world.last_group_followers]] = R_CONTESTED
        reasons = np.full(len(intents), R_BLOCKED, dtype=np.int8)
        reasons[keep] = report["reasons"]
        world.record_results(pids, cell_ids, intents["action"], reasons)
    if world_rules is not None:
        from .world_rules import WorldView, apply_ecology_commands
        events = world.last_rule_events if pending else []
        commands, error = world_rules.after_actions(events, WorldView(world.arrays), world.tick)
        if error:
            raise RuntimeError("世界行动后规则失败，模拟已停止：" + error)
        apply_ecology_commands(world, commands)
        commands, error = world_rules.before_ecology(WorldView(world.arrays), world.tick)
        if error:
            raise RuntimeError("世界生态规则失败，模拟已停止：" + error)
        apply_ecology_commands(world, commands)
    world._last_ecology = world.ecology()
    world.refresh_entities()
    return counts
