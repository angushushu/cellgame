"""Process rule loading, persistent state, timeout, and recovery."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.executor import RuleExecutor
from server.world import WorldState
from shared.models import Action

GOOD = """
counter = 0
def decide(cells, neighborhood, env, constraints, tick):
    global counter
    counter += 1
    x, y = map(int, cells[0, :2])
    return [[x, y, x, y, 4, 0, counter]]
"""
LOOP = """
def decide(cells, neighborhood, env, constraints, tick):
    while True:
        pass
"""


def main():
    world = WorldState(8, 8)
    world.arrays.owner[3, 3] = world.arrays.species[3, 3] = 1
    world.arrays.energy[3, 3] = 10
    batch = world.gather_sense(1)
    executor = RuleExecutor(timeout=0.3)
    try:
        executor.load(GOOD)
        assert int(executor._call(batch)[0]["param"]) == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(executor.load, GOOD).result()
        assert int(executor._call(batch)[0]["param"]) == 1
        assert int(executor._call(batch)[0]["param"]) == 2
        try:
            executor.load("def decide(:")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid rules loaded")
        assert int(executor._call(batch)[0]["param"]) == 3
        executor.load(LOOP)
        start = time.monotonic()
        try:
            executor._call(batch)
        except TimeoutError:
            pass
        else:
            raise AssertionError("infinite rule did not time out")
        assert time.monotonic() - start < 5
        assert executor.process is None
        executor.load(GOOD)
        assert int(executor._call(batch)[0]["param"]) == 1
    finally:
        executor.close()
    print("RULE EXECUTOR TEST PASSED")


if __name__ == "__main__":
    main()
