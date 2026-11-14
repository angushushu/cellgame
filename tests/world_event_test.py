"""Exercise a trusted world rule callback and its bounded output."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.world import WorldState
from server.world_rules import WorldRuleEngine, run_tick_event


def main():
    source = '''
def on_epoch(summary, tick):
    return {}
def on_event(event, view):
    assert event["type"] == "tick"
    assert event["tick"] == 7
    assert event["counts"]["eat"] == 2
    assert view.get_region(0, 0, 2, 2)["owner"].shape == (2, 2)
    return [
        {"type": "add_food", "x": 1, "y": 1, "amount": 7},
        {"type": "add_food", "x": 1, "y": 1, "amount": 1000000},
        {"type": "set_reproduction", "enabled": False},
    ]
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.py"
        path.write_text(source, encoding="utf-8")
        rules = WorldRuleEngine(str(path))
        world = WorldState(8, 8, seed=42)
        world.tick = 7
        old_food = float(world.arrays.env_food[1, 1])
        assert run_tick_event(world, rules, {"eat": 2}) is None
        assert abs(float(world.arrays.env_food[1, 1]) - old_food - 7) < 0.001
        assert not world.constraints["reproduce_enabled"]
    print("WORLD EVENT TEST PASSED")


if __name__ == "__main__":
    main()
