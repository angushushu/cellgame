"""An active hunter: stays strong, looks for prey, and chases it.

An attack only lands when the attacker's energy is strictly greater than the
target's (+3 if the target is armoured), so a hunter that breeds as early as
its prey is rarely strong enough. This one:

- hoards energy: eats up to EAT_UNTIL and only reproduces at REPRODUCE_AT;
- grazes until it has a reserve (HUNT_FROM): chasing and looking cost energy,
  and a starving hunter is too weak to win a fight anyway;
- hunts: in worlds with the sense action it pays to look HUNT_RADIUS tiles
  out, picks prey it can clearly beat, remembers where it was, and chases;
- searches: with no prey in sight it keeps a heading and travels straight,
  which covers far more ground than a random walk, then looks again;
- falls back to grazing like species/swarm.py when it is low on energy.

Only boundary cells can be attacked (an attacker must be adjacent, and a cell
with an enemy next to it is a boundary cell); hidden interiors are never
targets. Its thresholds differ from the shared probe economy on purpose:
hoarding is part of the hunting strategy.
"""
EAT_UNTIL = 45
REPRODUCE_AT = 30
HUNT_FROM = 15
STEP_ABOVE = 6
HUNT_RADIUS = 4
LOOK_EVERY = 3
MARGIN = 2           # prey may eat before we arrive; want a clear advantage
MEMORY_TICKS = 4     # how long a sighting stays worth chasing
ARMOR_BONUS = 3


def _defense(cell, p):
    bonus = cell.constraints.get("armor_defense_bonus", ARMOR_BONUS)
    return p.energy + (bonus if p.cell_type == 1 else 0)


def _beatable(cell, p, margin=0):
    return p.is_enemy and p.energy >= 0 and cell.energy > _defense(cell, p) + margin


def _wander(cell, empty):
    return empty[((cell.tick or 0) + cell.x * 7 + cell.y * 13) % len(empty)]


def _step_toward(cell, target, empty):
    tx, ty = target
    dx = (tx > cell.x) - (tx < cell.x)
    dy = (ty > cell.y) - (ty < cell.y)
    for direction in ((dx, dy), (dx, 0), (0, dy), (-dy, dx), (dy, -dx)):
        if direction != (0, 0) and direction in empty:
            return direction
    return None


def _visible_prey(cell):
    seen = cell.percepts() or cell.surrounding()
    prey = [p for p in seen if _beatable(cell, p, MARGIN) and (p.dx, p.dy) != (0, 0)]
    if not prey:
        return None
    best = min(prey, key=lambda p: (max(abs(p.dx), abs(p.dy)), p.energy))
    return (cell.x + best.dx, cell.y + best.dy)


def decide_cell(cell):
    adjacent = [n for n in cell.surrounding() if _beatable(cell, n)]
    if adjacent and cell.energy >= cell.constraints.get("attack_cost", 3):
        weakest = min(adjacent, key=lambda n: _defense(cell, n))
        return cell.attack((weakest.dx, weakest.dy))
    if cell.food_here > 0 and cell.energy < EAT_UNTIL:
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= REPRODUCE_AT and cell.constraints.get("reproduce_enabled", True):
        return cell.reproduce(_wander(cell, empty))

    memory, tick = (cell.memory if cell.id is not None else {}), cell.tick or 0
    if memory.pop("looked", False) and cell.last_result != "ok":
        memory["cannot_look"] = True
    if cell.energy < HUNT_FROM:
        memory.pop("prey", None)
        return _graze(cell, empty)
    sighting = _visible_prey(cell)
    if sighting is not None:
        memory["prey"], memory["seen_at"] = sighting, tick
    elif tick - memory.get("seen_at", -MEMORY_TICKS - 1) > MEMORY_TICKS:
        memory.pop("prey", None)
    if memory.get("prey") and cell.energy > STEP_ABOVE:
        step = _step_toward(cell, memory["prey"], empty)
        if step is not None:
            return cell.move(step)

    if (cell.id is not None and not memory.get("cannot_look") and tick >= memory.get("next_look", 0)
            and cell.energy > HUNT_RADIUS + 2 * STEP_ABOVE):
        memory["looked"], memory["next_look"] = True, tick + LOOK_EVERY
        return cell.extend_sense(HUNT_RADIUS)
    return _search(cell, empty, memory)


HEADINGS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


def _search(cell, empty, memory):
    """Travel straight along a remembered heading; turn when blocked."""
    if cell.food_here > 0 and cell.energy < EAT_UNTIL:
        return cell.eat()
    if not empty or cell.energy <= STEP_ABOVE:
        return cell.wait()
    heading = tuple(memory.get("heading", HEADINGS[(cell.x * 3 + cell.y * 5) % 8]))
    if heading not in empty:
        start = HEADINGS.index(heading)
        heading = next((HEADINGS[(start + k) % 8] for k in (1, -1, 2, -2, 3, -3, 4) if HEADINGS[(start + k) % 8] in empty), empty[0])
    memory["heading"] = heading
    return cell.move(heading)


def _graze(cell, empty):
    if empty and cell.energy > STEP_ABOVE:
        food = [n for n in cell.surrounding() if n.is_empty and n.food > 0]
        if food:
            best = max(food, key=lambda n: n.food)
            return cell.move((best.dx, best.dy))
        return cell.move(_wander(cell, empty))
    return cell.wait()
