"""围棋式世界：正交连接，行动后无气群同时死亡。"""
import numpy as np
from cellgame.shared.models import Action
from cellgame.server.default_world_rules import on_epoch, on_event, after_actions, before_ecology as material_effects

MANIFEST = {"id": "go", "name": "围棋生态"}


def filter_actions(intentions, players, world_view, tick):
    """禁止对角线建立连接；普通移动仍按基础世界规则裁决。"""
    diagonal = (intentions["src_x"] != intentions["tgt_x"]) & (intentions["src_y"] != intentions["tgt_y"])
    connected = ((intentions["action"] == int(Action.BOND)) |
                 ((intentions["action"] == int(Action.REPRODUCE)) & (intentions["param"] == 1)))
    return ~(diagonal & connected)


def before_ecology(world_view, tick):
    """以正交同玩家群体计算气，返回所有无气细胞的死亡命令。"""
    owners = world_view.get_region(0, 0, world_view.width, world_view.height)["owner"]
    h, w = owners.shape
    visited = np.zeros((h, w), dtype=bool)
    dead = []
    for y, x in zip(*np.where(owners != 0)):
        if visited[y, x]:
            continue
        owner = owners[y, x]
        stack = [(int(x), int(y))]
        visited[y, x] = True
        group, has_liberty = [], False
        while stack:
            cx, cy = stack.pop()
            group.append((cx, cy))
            for dx, dy in ((1,0), (-1,0), (0,1), (0,-1)):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if owners[ny, nx] == 0:
                    has_liberty = True
                elif owners[ny, nx] == owner and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((nx, ny))
        if not has_liberty:
            dead.extend({"type": "kill", "x": x, "y": y} for x, y in group)
    return material_effects(world_view, tick) + dead
