"""Validated beginner-friendly species configurations."""
import copy
import inspect

from cellgame.shared.models import Action
import numpy as np
from cellgame.species.units import make_entities

BEHAVIORS = ("eat", "reproduce", "attack", "defend", "move")
DEFAULT = {
    "enabled": {"eat": True, "reproduce": True, "attack": False, "defend": False, "move": True},
    "order": ["eat", "reproduce", "attack", "defend", "move"],
    "eat_below": 20, "reproduce_at": 13, "move_above": 4, "move_style": "food",
    "bond_newborn": False, "bond_neighbors": False, "release_bonds": False, "share_energy": False,
    "share_below": 6, "share_amount": 3, "group_move": False,
    "formation": "free", "collective": False,
}
PRESETS = {
    "balanced": DEFAULT,
    "forager": {**DEFAULT, "reproduce_at": 16, "move_style": "food"},
    "hunter": {**DEFAULT, "enabled": {"eat": True, "reproduce": True, "attack": True, "defend": False, "move": True},
               "order": ["attack", "eat", "reproduce", "defend", "move"], "move_style": "wander"},
    "guardian": {**DEFAULT, "enabled": {"eat": True, "reproduce": True, "attack": False, "defend": True, "move": False},
                 "order": ["defend", "eat", "reproduce", "attack", "move"]},
}

# Connected layouts; all growth still uses ordinary server-validated births.
FORMATIONS = {
    "spider": {(0,0), (-1,-1), (0,-1), (1,-1), (-1,0), (1,0),
               (-1,1), (0,1), (1,1), (-2,-2), (2,-2), (-2,2), (2,2)},
    "cross": {(0,0), (-1,0), (-2,0), (1,0), (2,0), (0,-1), (0,-2), (0,1), (0,2)},
}
PRESETS.update({
    "spider": {**DEFAULT, "formation":"spider", "bond_newborn":True, "group_move":True},
    "cross": {**DEFAULT, "formation":"cross", "bond_newborn":True, "group_move":True},
    "swarm": {**DEFAULT, "collective":True, "move_style":"food"},
})


def formation_birth(entity, shape, threshold):
    """One legal candidate per component; templates may translate but not teleport."""
    pattern = FORMATIONS[shape]
    positions = {(c.x, c.y) for c in entity.cells}
    if len(positions) >= len(pattern):
        return None
    anchors = sorted({(c.x-dx, c.y-dy) for c in entity.cells for dx,dy in pattern})
    for ax, ay in anchors:
        targets = {(ax+dx, ay+dy) for dx,dy in pattern}
        if not positions <= targets:
            continue
        for cell in sorted(entity.cells, key=lambda c:(c.y,c.x)):
            if cell.energy < threshold:
                continue
            for dx,dy in cell.empty_neighbors():
                if (cell.x+dx,cell.y+dy) in targets:
                    return (cell.x,cell.y), (dx,dy)
    return None


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("配置必须是一个对象")
    # Older saved configurations did not include cooperation options.
    config = {**{k: DEFAULT[k] for k in ("bond_newborn", "bond_neighbors", "release_bonds", "share_energy", "share_below", "share_amount", "group_move", "formation", "collective")}, **config}
    if set(config) != set(DEFAULT):
        raise ValueError("配置字段不完整或包含未知字段")
    if any(type(config[k]) is not bool for k in ("bond_newborn", "bond_neighbors", "release_bonds", "share_energy", "group_move")):
        raise ValueError("细胞协作开关格式不正确")
    if type(config["share_below"]) is not int or not 2 <= config["share_below"] <= 30:
        raise ValueError("分享能量阈值需为 2–30")
    if type(config["share_amount"]) is not int or not 1 <= config["share_amount"] <= 20:
        raise ValueError("分享能量数量需为 1–20")
    if config["release_bonds"] and (config["bond_newborn"] or config["bond_neighbors"]):
        raise ValueError("断开已有连接时，请先关闭自动连接")
    if config["formation"] not in ("free", *FORMATIONS) or type(config["collective"]) is not bool:
        raise ValueError("未知形态或群体模式")
    if config["formation"] != "free" and config["release_bonds"]:
        raise ValueError("形态生长时不能同时断开连接")
    enabled = config["enabled"]
    if not isinstance(enabled, dict) or set(enabled) != set(BEHAVIORS) or any(type(enabled[k]) is not bool for k in BEHAVIORS):
        raise ValueError("行为开关格式不正确")
    order = config["order"]
    if (not isinstance(order, list) or len(order) != len(BEHAVIORS)
            or any(not isinstance(item, str) for item in order) or set(order) != set(BEHAVIORS)):
        raise ValueError("行为顺序必须包含每个行为一次")
    for key, low, high in (("eat_below", 1, 40), ("reproduce_at", 10, 40), ("move_above", 2, 30)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError(f"{key} 超出允许范围")
    if config["move_style"] not in ("food", "wander"):
        raise ValueError("未知移动策略")
    return copy.deepcopy(config)


def build_source(config):
    """Export readable, editable Python with the same behavior as the composer."""
    config = validate_config(config)
    labels = {
        "eat_below": "进食的能量上限", "reproduce_at": "尝试繁殖的能量门槛（受世界规则约束）",
        "move_above": "尝试移动的能量门槛", "move_style": "移动偏好：food 或 wander",
        "bond_newborn": "新生细胞与父细胞连接", "bond_neighbors": "连接相邻的己方细胞",
        "release_bonds": "断开现有连接", "share_energy": "向相连细胞分享能量",
        "share_below": "邻居低于此能量时分享", "share_amount": "每次最多分享的能量",
        "group_move": "连接细胞整体移动", "formation": "生长形态：free、spider 或 cross",
        "collective": "共享食物方向线索",
    }
    lines = ["# 由行为组合生成；修改参数或下面的决策逻辑后，点击‘启用代码’。",
             "# 所有动作的结果和代价仍由服务器裁决。",
             "import numpy as np", "from cellgame.shared.models import Action",
             "from cellgame.species.units import make_entities",
             "from cellgame.species.composer import formation_birth", ""]
    for key, label in labels.items():
        lines.append(f"{key.upper()} = {config[key]!r}  # {label}")
    lines.append(f"BEHAVIOR_ORDER = {tuple(config['order'])!r}  # 按顺序尝试")
    for name in BEHAVIORS:
        lines.append(f"{name.upper()}_ENABLED = {config['enabled'][name]!r}")
    lines.extend(["", "def decide(cells, neighborhood, env, constraints, tick, observation=None):"])
    body = inspect.getsource(decide_with_config).split("\n", 1)[1]
    body = body.replace('reproduce_threshold(config, constraints)', 'max(REPRODUCE_AT, constraints.get("reproduce_min_energy", 10), constraints.get("reproduce_cost", 8))')
    for key in labels:
        body = body.replace(f'config["{key}"]', key.upper())
        for default in ("False", '"free"'):
            body = body.replace(f'config.get("{key}", {default})', key.upper())
    body = body.replace('config["order"]', 'BEHAVIOR_ORDER')
    body = body.replace('if not config["enabled"][behavior]:',
                        'if not {"eat": EAT_ENABLED, "reproduce": REPRODUCE_ENABLED, "attack": ATTACK_ENABLED, "defend": DEFEND_ENABLED, "move": MOVE_ENABLED}[behavior]:')
    return "\n".join(lines) + "\n" + body


def reproduce_threshold(config, constraints):
    """When this species tries to reproduce: its own threshold, but never below
    what the world requires (the server rejects anything less)."""
    world_minimum = max(constraints.get("reproduce_min_energy", 10), constraints.get("reproduce_cost", 8))
    return max(config["reproduce_at"], world_minimum)


def decide_with_config(config, cells, neighborhood, env, constraints, tick, observation=None):
    entities = make_entities(cells, neighborhood, env, constraints, tick, observation)
    reproduce_at = reproduce_threshold(config, constraints)
    growth = {}
    formation = config.get("formation", "free")
    if formation != "free":
        for entity in entities:
            candidate = formation_birth(entity, formation, reproduce_at)
            if candidate:
                growth[candidate[0]] = candidate[1]
    # A simple shared cue: every member sees the direction of the strongest local food signal.
    cue = None
    if config.get("collective", False):
        seen = [(n.food, n.dx, n.dy) for entity in entities for cell in entity.cells
                for n in cell.surrounding() if n.in_bounds and n.food > 0]
        if seen:
            _, dx, dy = max(seen)
            cue = (dx, dy)
    def choose(cell):
        empties = cell.empty_neighbors()
        neighbors = cell.surrounding()
        if config.get("release_bonds", False):
            bonded = next((n for n in neighbors if n.is_bonded), None)
            if bonded:
                return cell.unbond((bonded.dx, bonded.dy))
        if config.get("share_energy", False):
            needy = [n for n in neighbors if n.is_bonded and n.is_mine
                     and n.energy < config["share_below"]
                     and cell.energy > max(config["share_below"], n.energy + 1)]
            if needy:
                target = min(needy, key=lambda n: n.energy)
                amount = min(config["share_amount"], (cell.energy - target.energy) // 2)
                if amount:
                    return cell.transfer((target.dx, target.dy), amount)
        if config.get("bond_neighbors", False):
            unconnected = [n for n in neighbors if n.is_mine and not n.is_bonded]
            if unconnected:
                n = unconnected[0]
                return cell.bond((n.dx, n.dy))
        enemies = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dx or dy):
                    continue
                i = ((dy + 1) * 3 + dx + 1) * 5
                own, species, cell_type, _, energy = map(int, cell.neighbors[i:i + 5])
                if species and not own:
                    enemies.append((dx, dy, energy, cell_type))
        for behavior in config["order"]:
            if not config["enabled"][behavior]:
                continue
            if behavior == "eat" and cell.food_here > 0 and cell.energy < config["eat_below"]:
                return cell.eat()
            if behavior == "reproduce" and cell.energy >= reproduce_at and empties and constraints.get("reproduce_enabled", True):
                if formation != "free":
                    direction = growth.get((cell.x, cell.y))
                    if direction is not None:
                        return cell.reproduce(direction, bond=True)
                else:
                    return cell.reproduce(empties[(tick + cell.x * 7 + cell.y * 13) % len(empties)], bond=config.get("bond_newborn", False))
            if behavior == "attack" and cell.energy >= 3:
                bonus = constraints.get("armor_defense_bonus", 3)
                targets = [e for e in enemies if cell.energy > e[2] + (bonus if e[3] == 1 else 0)]
                if targets:
                    dx, dy, _, _ = min(targets, key=lambda e: e[2] + (bonus if e[3] == 1 else 0))
                    return [cell.x, cell.y, cell.x + dx, cell.y + dy, Action.ATTACK, 0, 0]
            if behavior == "defend" and enemies and cell.cell_type != 1 and cell.energy >= 2:
                return [cell.x, cell.y, cell.x, cell.y, Action.CHANGE, 0, 1]
            if behavior == "move" and (not cell.bonds or config.get("group_move", False)) and empties and cell.energy > config["move_above"]:
                move = cell.move_group if cell.bonds else cell.move
                if cue in empties:
                    return move(cue)
                if config["move_style"] == "food" and len(cell.env) >= 11:
                    best = max(empties, key=lambda p: cell.env[2 + (p[1] + 1) * 3 + p[0] + 1])
                    if cell.env[2 + (best[1] + 1) * 3 + best[0] + 1] > 0:
                        return move(best)
                return move(empties[(tick * 3 + cell.x * 5 + cell.y * 11) % len(empties)])
        return cell.wait()
    actions = [action for entity in entities for cell in entity.cells
               if (action := choose(cell)) is not None]
    return np.asarray(actions, dtype=np.int32).reshape(-1, 7)
