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
        self.arrays.owner[y, x] = player_id
        self.arrays.species[y, x] = species_id
        self.arrays.energy[y, x] = 10
        return 1


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
