"""A compact bonded organism that grows an interior.

For blanket worlds (e.g. ``--world-preset deep-dive``). Cells bond to every
neighboring cell of their own, grow into the empty tile that touches the most
of their own cells (which keeps the body round), and pass energy along bonds
to hungry members. Boundary cells feed; interior cells are cheaper to keep
alive and cannot be attacked until the membrane around them is broken.
"""
# Same economy as species/swarm.py, sensing_forager.py and predator.py.
EAT_UNTIL = 25
REPRODUCE_AT = 14
SHARE_BELOW = 7
SHARE_FROM = 12


def _crowding(cell, direction):
    """How many of our own cells would touch a newborn placed at direction."""
    dx, dy = direction
    count = 0
    for p in cell.percepts() or cell.surrounding():
        if p.is_mine and max(abs(p.dx - dx), abs(p.dy - dy)) == 1:
            count += 1
    return count


def decide_cell(cell):
    neighbors = cell.surrounding()
    loose = [n for n in neighbors if n.is_mine and not n.is_bonded]
    if loose:
        return cell.bond((loose[0].dx, loose[0].dy))
    hungry = [n for n in neighbors if n.is_bonded and n.energy < SHARE_BELOW]
    if hungry and cell.energy >= SHARE_FROM:
        target = min(hungry, key=lambda n: n.energy)
        return cell.transfer((target.dx, target.dy), 3)
    if cell.role != "interior" and cell.food_here > 0 and cell.energy < EAT_UNTIL:
        return cell.eat()
    empty = cell.empty_neighbors()
    if empty and cell.energy >= REPRODUCE_AT and cell.constraints.get("reproduce_enabled", True):
        return cell.reproduce(max(empty, key=lambda d: _crowding(cell, d)), bond=True)
    return cell.wait()
