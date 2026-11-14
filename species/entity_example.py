"""有机体控制：让每个边界细胞优先吃脚下的食物。"""
def decide_entity(entity):
    actions = []
    for cell in entity.boundary:
        if cell.food_here > 0 and cell.energy < 20:
            actions.append(cell.eat())
        elif cell.energy >= 13 and cell.empty_neighbors():
            actions.append(cell.reproduce(cell.empty_neighbors()[0], bond=True))
    return actions
