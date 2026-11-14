"""Verify presets, configurable behavior, and rule-source execution."""
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.executor import RuleExecutor
from client.preview import run_preview
from server.world import WorldState
from shared.models import Action
from species.composer import PRESETS, build_source, validate_config, decide_with_config


def world_minimum_test():
    """The species threshold never undercuts the world's reproduction rules."""
    from cellgame.species.composer import DEFAULT, reproduce_threshold
    config = {**DEFAULT, "reproduce_at": 10}
    assert reproduce_threshold(config, {"reproduce_min_energy": 25, "reproduce_cost": 8}) == 25
    assert reproduce_threshold(config, {"reproduce_min_energy": 5, "reproduce_cost": 12}) == 12
    assert reproduce_threshold({**DEFAULT, "reproduce_at": 30}, {"reproduce_min_energy": 10}) == 30


def main():
    world_minimum_test()
    for name, config in PRESETS.items():
        source = build_source(config)
        assert "CONFIG =" not in source and "def choose(cell):" in source
        scenario = WorldState(8, 8, seed=2)
        for x, y, owner, energy in [(2,2,1,15),(4,4,1,20),(3,4,2,4)]:
            scenario.arrays.owner[y,x] = scenario.arrays.species[y,x] = owner
            scenario.arrays.energy[y,x] = energy
            scenario.arrays.env_food[y,x] = 5
        batch = scenario.gather_sense(1)
        args = (batch["cells"], batch["neighborhood"], batch["env"], batch["constraints"], batch["tick"])
        ns = {}; exec(source, ns)
        assert np.array_equal(ns["decide"](*args), decide_with_config(config, *args)), name
        result = run_preview(source, ticks=10, size=32, seed=1)
        assert result["ticks"] == 10, name
    try:
        validate_config({**PRESETS["balanced"], "order": [["bad"]] * 5})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid behavior order was accepted")
    world = WorldState(8, 8, seed=1)
    world.arrays.owner[3, 3] = world.arrays.species[3, 3] = 1
    world.arrays.energy[3, 3] = 10
    world.arrays.env_food[3, 3] = 10
    world.arrays.owner[3, 4] = world.arrays.species[3, 4] = 2
    world.arrays.energy[3, 4] = 5
    world.arrays.energy[3, 3] = 15
    batch = world.gather_sense(1)
    def action_for(preset):
        result = decide_with_config(preset, batch["cells"], batch["neighborhood"],
                                    batch["env"], batch["constraints"], batch["tick"])
        return int(result[0, 4])
    assert action_for(PRESETS["balanced"]) == Action.EAT
    assert action_for(PRESETS["hunter"]) == Action.ATTACK
    assert action_for(PRESETS["guardian"]) == Action.CHANGE
    executor = RuleExecutor()
    try:
        executor.load(build_source(PRESETS["balanced"]))
        result = executor._call(world.gather_sense(1))
        assert len(result) == 1 and int(result[0]["action"]) == Action.EAT
    finally:
        executor.close()
    print("COMPOSER TEST PASSED")


if __name__ == "__main__":
    main()
