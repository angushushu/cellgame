"""Exercise the JSON-lines agent protocol without opening a socket."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.external_agent import ExternalAgentExecutor
from server.world import WorldState
from shared.models import Action


def main():
    world = WorldState(16, 16, seed=0)
    world.arrays.owner[3, 4] = 1
    world.arrays.species[3, 4] = 1
    world.arrays.energy[3, 4] = 10
    world.arrays.env_food[3, 4] = 5
    agent = ExternalAgentExecutor([sys.executable, "-u", str(ROOT / "species" / "stdio_example.py")])
    try:
        batch = world.gather_sense(1)
        result = agent._exchange(batch)
        assert len(result) == 1 and int(result[0]["action"]) == Action.EAT
        assert (int(result[0]["src_x"]), int(result[0]["src_y"])) == (4, 3)
        world.tick += 1
        assert len(agent._exchange(world.gather_sense(1))) == 1
    finally:
        agent.close()
    broken = ExternalAgentExecutor([
        sys.executable, "-u", "-c",
        "import sys,json; line=sys.stdin.readline(); print(json.dumps({'tick':-1,'actions':[]}),flush=True)",
    ])
    try:
        try:
            broken._exchange(batch)
        except ValueError as exc:
            assert "tick" in str(exc)
        else:
            raise AssertionError("stale external-agent response was accepted")
    finally:
        broken.close()
    print("EXTERNAL AGENT TEST PASSED")


if __name__ == "__main__":
    main()
