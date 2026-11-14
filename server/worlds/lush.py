"""A resource-rich beginner world; select it with --world-rules."""
from cellgame.server.default_world_rules import on_epoch as base_on_epoch, on_event, after_actions, before_ecology


def on_epoch(summary, tick):
    params = base_on_epoch(summary, tick)
    params.update(food_regrow=400, food_regrow_near_cells=60, metabolism_interval=15)
    return params
