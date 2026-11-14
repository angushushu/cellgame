"""A forager that pays to look further and remembers what it saw.

For worlds with the sense action (e.g. ``--world-preset deep-dive``). It lives
like species/swarm.py (same economy), with one difference: when no food is in
reach it buys a wider view (cell.extend_sense) and, one tick later, walks
toward the richest food it saw. The target is kept in cell.memory, so the cell
keeps walking after the food is out of sight. If looking is unavailable or
finds nothing, it wanders like the swarm and looks again a few ticks later.
"""
LOOK_RADIUS = 3
LOOK_EVERY = 4
# Same economy as species/swarm.py, blob.py and predator.py.
EAT_UNTIL = 25
REPRODUCE_AT = 14
STEP_ABOVE = 6


def _wander(cell, empty):
    return empty[((cell.tick or 0) + cell.x * 7 + cell.y * 13) % len(empty)]


def _step_toward(cell, target, empty):
    tx, ty = target
    dx = (tx > cell.x) - (tx < cell.x)
    dy = (ty > cell.y) - (ty < cell.y)
    for direction in ((dx, dy), (dx, 0), (0, dy)):
        if direction != (0, 0) and direction in empty:
            return direction
    return None


def _best_food(cell):
    foods = [p for p in cell.percepts() if p.env_visible and p.food > 0 and (p.dx, p.dy) != (0, 0)]
    if not foods:
        return None
    best = max(foods, key=lambda p: p.food / (1 + max(abs(p.dx), abs(p.dy))))
    return (cell.x + best.dx, cell.y + best.dy)


def decide_cell(cell):
    if cell.food_here > 0 and cell.energy < EAT_UNTIL:
        cell.memory.pop("target", None)
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= REPRODUCE_AT and cell.constraints.get("reproduce_enabled", True):
        return cell.reproduce(_wander(cell, empty))
    memory, tick = cell.memory if cell.id is not None else {}, cell.tick or 0
    if memory.pop("looked", False) and cell.last_result != "ok":
        memory["cannot_look"] = True           # sense is disabled or not allowed here
    target = memory.get("target") or _best_food(cell)
    if target is not None and cell.energy > STEP_ABOVE:
        step = _step_toward(cell, target, empty)
        if step is not None:
            memory["target"] = target
            return cell.move(step)
    memory.pop("target", None)
    if (cell.id is not None and not memory.get("cannot_look")
            and tick >= memory.get("next_look", 0) and cell.energy > LOOK_RADIUS + STEP_ABOVE):
        memory["looked"], memory["next_look"] = True, tick + LOOK_EVERY
        return cell.extend_sense(LOOK_RADIUS)
    if empty and cell.energy > STEP_ABOVE:
        return cell.move(_wander(cell, empty))
    return cell.wait()
