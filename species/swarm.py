"""A blind, unbonded swarm: eat what is underfoot, step toward food you can
touch, otherwise wander.

Shares its economy (EAT_UNTIL, REPRODUCE_AT, STEP_ABOVE) with
species/blob.py, species/sensing_forager.py and species/predator.py, so that
tests/blanket_experiment.py compares strategies rather than thresholds.
"""
EAT_UNTIL = 25
REPRODUCE_AT = 14
STEP_ABOVE = 6


def _wander(cell, empty):
    return empty[((cell.tick or 0) + cell.x * 7 + cell.y * 13) % len(empty)]


def decide_cell(cell):
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
