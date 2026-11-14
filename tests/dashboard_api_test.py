"""Verify the server dashboard's status contract without opening a socket."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.net import GameServer
from server.world import WorldState


class FakeHTTPServer:
    handler = None
    def __init__(self, address, handler):
        FakeHTTPServer.handler = handler
    def serve_forever(self):
        pass


class DeadProcess:
    def is_alive(self):
        return False


def get(path, address="127.0.0.1"):
    handler = object.__new__(FakeHTTPServer.handler)
    handler.path = path
    handler.client_address = (address, 1234)
    result = []
    handler._send = lambda status, body, ctype: result.append((status, json.loads(body)))
    handler.do_GET()
    return result[0]


def get_asset():
    handler = object.__new__(FakeHTTPServer.handler)
    handler.path = "/world-view.js"
    result = []
    handler._send = lambda code, body, ctype: result.append((code, body, ctype))
    handler.do_GET()
    return result[0]


def main():
    server = GameServer(None, None, port=19999, sim_proc=DeadProcess(),
                        world_config={"tick_ms": 5000, "world_preset": "lush"})
    world = WorldState(8, 8, seed=1)
    server.apply_snapshot(world.snapshot_arrays())
    server.latest_summary = world.summary()
    with patch("server.net.ThreadingHTTPServer", FakeHTTPServer):
        server.start_http()
    code, result = get("/api/players")
    assert code == 200 and result["game_port"] == 19999
    assert result["world_ready"] and not result["sim_alive"]
    assert result["settings"]["world_preset"] == "lush"
    assert "metabolism_interval" in result["constraints"]
    server.manifest["visibility"]["spectator"] = "none"
    code, full = get("/api/admin/snapshot")
    assert code == 200 and "env_biome" in full["arrays"]
    assert get("/api/admin/snapshot", "192.0.2.10")[0] == 403
    assert get("/api/snapshot", "192.0.2.10")[0] == 403
    code, body, ctype = get_asset()
    assert code == 200 and b"CellWorldView" in body and "javascript" in ctype
    print("DASHBOARD API TEST PASSED")


if __name__ == "__main__":
    main()
