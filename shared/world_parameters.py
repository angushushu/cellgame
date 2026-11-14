"""Server-owned economic rules and validation."""
from .models import ACTION_COST, Action, EAT_MAX_GAIN, REPRODUCE_MIN_ENERGY, REPRODUCE_CHILD_ENERGY, ARMOR_DEFENSE_BONUS, ARMOR_MOVE_SURCHARGE

DEFAULTS = {
    "move_cost": ACTION_COST[Action.MOVE], "attack_cost": ACTION_COST[Action.ATTACK],
    "push_cost": 0, "block_attack_cost": 3,
    "reproduce_cost": ACTION_COST[Action.REPRODUCE], "change_cost": ACTION_COST[Action.CHANGE],
    "reproduce_min_energy": REPRODUCE_MIN_ENERGY, "child_energy": REPRODUCE_CHILD_ENERGY,
    "eat_gain": EAT_MAX_GAIN, "attack_reward_percent": 50,
    "armor_defense_bonus": ARMOR_DEFENSE_BONUS, "armor_move_surcharge": ARMOR_MOVE_SURCHARGE,
}
BOUNDS = {key: (0, 100) for key in DEFAULTS}
BOUNDS["child_energy"] = (1, 100)
BOUNDS["reproduce_min_energy"] = (1, 100)

def validate_parameters(values, *, partial=False):
    if not isinstance(values, dict) or any(k not in DEFAULTS for k in values):
        raise ValueError("未知的世界参数")
    result = {} if partial else dict(DEFAULTS)
    for key, value in values.items():
        lo, hi = BOUNDS[key]
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f"{key} 必须是 {lo}–{hi} 的整数")
        result[key] = value
    return result

def action_cost(action, constraints):
    key = {Action.MOVE: "move_cost", Action.ATTACK: "attack_cost",
           Action.REPRODUCE: "reproduce_cost", Action.CHANGE: "change_cost"}.get(action)
    return constraints.get(key, DEFAULTS[key]) if key else ACTION_COST[action]
