"""Demo world rules: resource regrowth + temperature cycle.

on_epoch runs every epoch_interval ticks (default 10). It returns global
parameter adjustments; the engine applies them (see world_rules.py).
Reproduction is disabled while the mean temperature is extreme.
"""
import math


def on_epoch(summary, tick):
    # Temperature follows a slow cycle (period ~190 ticks); the mean is
    # steered toward the target, so it actually crosses the 12/28
    # thresholds: a cold/hot snap disables reproduction for a stretch.
    # (The old version only nudged temp by 0.5*sin(tick/40), so the mean
    # never left [12, 28] and the constraint never fired.)
    mean_temp = summary.get("mean_temp", 20.0)
    target = 20.0 + 9.0 * math.sin(tick / 30.0)
    temp_delta = (target - mean_temp) * 0.7
    reproduce_enabled = 12.0 <= mean_temp <= 28.0
    return {
        "food_regrow": 300,
        "food_regrow_near_cells": 30,
        "temp_delta": temp_delta,
        "reproduce_enabled": reproduce_enabled,
    }


def on_event(event, world_view):
    return []


# 这些规则可由其他世界文件导入、替换或修改。
BERRY_BONUS = 2
LAVA_DAMAGE = 5
SPIKE_DAMAGE = 2


def after_actions(events, world_view, tick):
    return [{"type": "adjust_energy", "x": e["x"], "y": e["y"],
             "cell_id": e["cell_id"], "amount": BERRY_BONUS}
            for e in events if e["type"] == "eat" and e["material"] == 1]


def before_ecology(world_view, tick):
    import numpy as np
    data = world_view.get_region(0, 0, world_view.width, world_view.height)
    material, owner = data["env_material"], data["owner"]
    ys, xs = np.where((owner != 0) & ((material == 2) | (material == 3)))
    return [{"type": "adjust_energy", "x": int(x), "y": int(y),
             "amount": -LAVA_DAMAGE if material[y, x] == 2 else -SPIKE_DAMAGE}
            for y, x in zip(ys, xs)]
