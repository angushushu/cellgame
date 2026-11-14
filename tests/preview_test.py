"""Preview tie timing, error visibility and worker termination."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import client.preview as preview
from server.world import WorldState
from shared.arbiter import _det_hash


class FixedWorld(WorldState):
    def spawn_player(self, player_id, species_id, count=20, seed=None):
        x, y = ((4, 4) if player_id == 1 else (5, 4))
        self.arrays.blocks[y, x] = 0
        self.place_cell(player_id, x, y, energy=10, species=species_id)
        return 1


class BlockWorld(WorldState):
    def seed_blocks(self, seed=0):
        self.arrays.blocks[:] = 0
        self.arrays.blocks[4, 5] = 1
    def spawn_player(self, player_id, species_id, count=20, seed=None):
        self.place_cell(player_id, 4, 4, energy=20, species=species_id)
        return 1

BLOCK_RULE = """
def decide_cell(cell):
    p = cell.sense(1, 0)
    return cell.attack((1, 0)) if p and p.block == 1 else cell.wait()
"""

MOVE = """
def decide(cells, neighborhood, env, constraints, tick):
    x, y = map(int, cells[0,:2])
    return [[x, y, 5, 5, 0, 0, 0]]
"""
FAIL = """
def decide(cells, neighborhood, env, constraints, tick):
    raise ValueError('deliberate error')
"""
LOOP = """
def decide(cells, neighborhood, env, constraints, tick):
    while True:
        pass
"""


def main():
    previous = preview.WorldState
    try:
        preview.WorldState = FixedWorld
        result = preview.run_preview(MOVE, ticks=1, size=16, rival_source=MOVE)
        winner = 1 if _det_hash(1, 5, 5, 4, 4) < _det_hash(1, 5, 5, 5, 4) else 2
        assert result["final_grid"]["owner"][5][5] == winner
        other_tick = 1 if _det_hash(0, 5, 5, 4, 4) < _det_hash(0, 5, 5, 5, 4) else 2
        assert winner != other_tick
    finally:
        preview.WorldState = previous
    try:
        preview.WorldState = BlockWorld
        result = preview.run_preview(BLOCK_RULE, ticks=1, size=16)
        assert result["attacks"] == 1 and result["final_grid"]["blocks"][4][5] == 0
    finally:
        preview.WorldState = previous
    try:
        preview.run_preview_isolated(FAIL, ticks=1, timeout=5)
    except RuntimeError as exc:
        assert "deliberate error" in str(exc)
    else:
        raise AssertionError("preview swallowed rule error")
    start = time.monotonic()
    try:
        preview.run_preview_isolated(LOOP, ticks=1, timeout=1)
    except TimeoutError:
        pass
    else:
        raise AssertionError("preview did not stop")
    assert time.monotonic() - start < 5
    # The console invokes preview from an HTTP server thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(preview.run_preview_isolated, MOVE, ticks=1, timeout=5).result()
        assert result["ticks"] == 1
    print("PREVIEW TEST PASSED")


if __name__ == "__main__":
    main()
