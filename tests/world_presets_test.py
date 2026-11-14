"""Check selectable world presets load and have their documented settings."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.world import WorldState
from server.world_rules import WorldRuleEngine, apply_world_params


def main():
    paths = {
        "balanced": ROOT / "server" / "default_world_rules.py",
        "lush": ROOT / "server" / "worlds" / "lush.py",
        "challenging": ROOT / "server" / "worlds" / "challenging.py",
    }
    values = {}
    for name, path in paths.items():
        world = WorldState(32, 32, seed=0)
        world.spawn_player(1, 1, count=15)
        engine = WorldRuleEngine(str(path))
        params, error = engine.on_epoch(world.summary(), 0)
        assert error is None
        apply_world_params(world, params)
        values[name] = (params["food_regrow_near_cells"], world.constraints["metabolism_interval"])
    assert values["challenging"][0] < values["balanced"][0] < values["lush"][0]
    assert values["challenging"][1] < values["balanced"][1] < values["lush"][1]
    print("WORLD PRESETS TEST PASSED")


if __name__ == "__main__":
    main()
