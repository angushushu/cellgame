"""连接与能量分享：在进阶模式加载或复制本文件。"""

def decide_cell(cell):
    # 优先帮助已经连接的低能量邻居。
    for n in cell.surrounding():
        if n.is_bonded and n.energy < 6 and cell.energy >= 10:
            return cell.transfer((n.dx, n.dy), 3)

    if cell.food_here > 0 and cell.energy < 20:
        return cell.eat()

    empty = cell.empty_neighbors()
    if empty and cell.energy >= 13 and cell.constraints.get("reproduce_enabled", True):
        return cell.reproduce(empty[0], bond=True)

    # 如果希望整体移动，可将下一行替换为：
    # if cell.bonds and empty: return cell.move_group(empty[0])
    if not cell.bonds and empty and cell.energy > 4:
        return cell.move(empty[0])
    return cell.wait()
