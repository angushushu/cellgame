"""A minimal species: edit this function and preview it."""


def decide_cell(cell):
    if cell.food_here > 0:
        return cell.eat()
    empty = cell.empty_neighbors()
    if cell.energy >= 13 and empty and cell.constraints['reproduce_enabled']:
        return cell.reproduce(empty[0])
    if cell.energy > 4 and empty:
        return cell.move(empty[0])
    return cell.wait()
