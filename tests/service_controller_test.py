"""Local service validation, observation format and mode switching."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.executor import RuleExecutor
from client.local_service import call_service, validate_service_url, NoRedirect
from server.world import WorldState
from shared.models import Action
from examples.local_agent_service import respond


class Response:
    def __init__(self, content):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, size):
        return self.content[:size]


class Opener:
    def __init__(self):
        self.observed = None
    def open(self, request, timeout):
        self.observed = json.loads(request.data)
        assert timeout == 1
        return Response(json.dumps({"tick": self.observed["tick"],
                                    "actions": [[3, 3, 3, 3, 3, 0, 0]]}).encode())


def main():
    assert validate_service_url("http://127.0.0.1:9000/decide")
    for url in ("http://example.com:9000", "http://127.0.0.1.evil:9000",
                "http://example.com@localhost:9000", "https://localhost:9000"):
        try:
            validate_service_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid service URL accepted: {url}")
    world = WorldState(8, 8, seed=1)
    world.arrays.owner[3, 3] = world.arrays.species[3, 3] = 1
    world.arrays.energy[3, 3] = 10
    batch = world.gather_sense(1)
    opener = Opener()
    with patch("urllib.request.build_opener", return_value=opener):
        actions = call_service("http://127.0.0.1:9000/decide", batch, 1)
    assert int(actions[0]["action"]) == Action.EAT
    assert opener.observed["cells"][0][:2] == [3, 3]
    assert opener.observed["tick"] == batch["tick"]
    assert respond(opener.observed)["tick"] == batch["tick"]
    executor = RuleExecutor(timeout=1)
    try:
        executor.load_service("http://127.0.0.1:9000/decide")
        with patch("urllib.request.build_opener", return_value=opener):
            assert int(executor._call(batch)[0]["action"]) == Action.EAT
        try:
            executor.load_service("http://example.org:8080")
        except ValueError:
            pass
        assert executor.service_url == "http://127.0.0.1:9000/decide"
        executor.load("def decide(cells, neighborhood, env, constraints, tick):\n    return []")
        assert executor.service_url is None and len(executor._call(batch)) == 0
    finally:
        executor.close()
    print("SERVICE CONTROLLER TEST PASSED")


if __name__ == "__main__":
    main()
