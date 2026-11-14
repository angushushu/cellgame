"""群体控制：汇总当前玩家所有有机体的信息并各自觅食。"""
def decide_unity(unity):
    actions = []
    for entity in unity.members:
        for cell in entity.boundary:
            if cell.food_here > 0 and cell.energy < 20:
                actions.append(cell.eat())
            elif cell.energy >= 13 and cell.empty_neighbors():
                actions.append(cell.reproduce(cell.empty_neighbors()[0], bond=True))
    return actions
