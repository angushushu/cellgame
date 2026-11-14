"""An unbonded predator: attack a neighbouring enemy cell it can beat, otherwise
live like species/swarm.py (same economy).

Only boundary cells can ever be attacked: an attack must target an adjacent
tile, and any cell with an enemy next to it is a boundary cell.
"""
EAT_UNTIL = 25
REPRODUCE_AT = 14
STEP_ABOVE = 6
ARMOR_BONUS = 3
ATTACK_COST = 3


def _wander(cell, empty):
    return empty[((cell.tick or 0) + cell.x * 7 + cell.y * 13) % len(empty)]


def _prey(cell):
    bonus = cell.constraints.get("armor_defense_bonus", ARMOR_BONUS)
    cost = cell.constraints.get("attack_cost", ATTACK_COST)
    targets = []
    for n in cell.surrounding():
        if n.is_enemy and n.energy >= 0:      # -1 means the energy is hidden
            defense = n.energy + (bonus if n.cell_type == 1 else 0)
            if cell.energy > defense and cell.energy >= cost:
                targets.append((defense, n))
    return min(targets, key=lambda t: t[0])[1] if targets else None


def decide_cell(cell):
    prey = _prey(cell)
    if prey is not None:
        return cell.attack((prey.dx, prey.dy))
    if cell.food_here > 0 and cell.energy < EAT_UNTIL:
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= REPRODUCE_AT and cell.constraints.get("reproduce_enabled", True):
        return cell.reproduce(_wander(cell, empty))
    if empty and cell.energy > STEP_ABOVE:
        food = [n for n in cell.surrounding() if n.is_empty and n.food > 0]
        if food:
            best = max(food, key=lambda n: n.food)
            return cell.move((best.dx, best.dy))
        return cell.move(_wander(cell, empty))
    return cell.wait()
