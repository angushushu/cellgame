"""Exercise console HTTP handlers in-process without opening network sockets."""
import io
import json
import base64
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.executor import RuleExecutor
from client.http_server import ConsoleServer
from client.net import ClientState, GameClient
from species.composer import PRESETS
from server.world import WorldState
import numpy as np


class CompletedFuture:
    def cancelled(self):
        return False
    def exception(self):
        return None
    def add_done_callback(self, callback):
        callback(self)


def finish(coro):
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("unexpected async suspension")


class FakeHTTPServer:
    handler = None
    def __init__(self, address, handler):
        FakeHTTPServer.handler = handler
    def serve_forever(self):
        pass


def request(path, body=None, headers=None, expected_status=200):
    handler = object.__new__(FakeHTTPServer.handler)
    handler.path = path
    data = b"" if body is None else json.dumps(body).encode("utf-8")
    handler.headers = {"Content-Length": str(len(data)), "Content-Type": "application/json"}
    if headers:
        handler.headers.update(headers)
    handler.rfile = io.BytesIO(data)
    result = []
    handler._send = lambda code, content, ctype="application/json": result.append((code, json.loads(content)))
    if body is None:
        handler.do_GET()
    else:
        handler.do_POST()
    assert len(result) == 1 and result[0][0] == expected_status
    return result[0][1]


def get_static(path):
    handler = object.__new__(FakeHTTPServer.handler)
    handler.path = path
    result = []
    handler._send = lambda code, content, ctype="application/json": result.append((code, content, ctype))
    handler.do_GET()
    assert len(result) == 1 and result[0][0] == 200
    return result[0][1:]


def main():
    state = ClientState()
    executor = RuleExecutor()
    client = GameClient(state, executor)
    console = ConsoleServer(state, executor, client)
    try:
        with patch("client.http_server.ThreadingHTTPServer", FakeHTTPServer):
            console.start()
        generated = request("/api/compose/source", {"config": PRESETS["spider"]})
        assert generated["ok"] and "spider" in generated["source"]
        assert not request("/api/compose/source", {"config": {}})["ok"]
        guide, ctype = get_static("/guide")
        assert b"decide_cell" in guide and "text/html" in ctype
        asset, ctype = get_static("/world-view.js")
        assert b"CellWorldView" in asset and "javascript" in ctype
        rejected = request("/api/service/apply", {"url": "http://localhost:9000/decide"},
                           headers={"Host": "localhost:8081", "Origin": "https://example.com"},
                           expected_status=403)
        assert not rejected["ok"] and state.controller_type == "未设置"
        assert request("/api/profile", {"name": "新玩家", "color": "#112233"})["ok"]
        assert state.player_name == "新玩家" and state.player_color == "#112233"
        state.connected = True
        state.player_id = 1
        state.loop = object()
        def schedule(coro, loop):
            coro.close()
            return CompletedFuture()
        with patch("client.http_server.asyncio.run_coroutine_threadsafe", side_effect=schedule):
            sent = request("/api/profile", {"name": "更新昵称", "color": "#abcdef"})
        assert sent["pending"] and state.profile_pending
        request_id = state.profile_pending
        finish(client.handle("player_updated", {"player_id": 1, "name": "更新昵称",
                                                "color": "#ABCDEF", "request_id": request_id}))
        assert state.profile_pending is None and state.player_name == "更新昵称"
        state.world = WorldState(8, 8).arrays
        state.world.owner[2, 3] = state.world.species[2, 3] = 1
        state.world.cell_type[2, 3] = 1
        state.world.owner[4, 5] = state.world.species[4, 5] = 300
        state.players[300] = {"name": "另一个玩家", "color": "#123456"}
        payload = request("/api/state")
        assert payload["players"][0]["color"] == "#ABCDEF"
        assert np.frombuffer(base64.b64decode(payload["owner_b64"]), dtype="<i4").reshape(8, 8)[2, 3] == 1
        assert np.frombuffer(base64.b64decode(payload["owner_b64"]), dtype="<i4").reshape(8, 8)[4, 5] == 300
        assert np.frombuffer(base64.b64decode(payload["type_b64"]), dtype="<i2").reshape(8, 8)[2, 3] == 1
        state.connected = False
        state.loop = None
        assert set(request("/api/presets")["presets"]) == set(PRESETS)
        config = PRESETS["hunter"]
        assert request("/api/compose/apply", {"config": config})["ok"]
        assert request("/api/state")["controller_type"] == "组合模式"
        preview = request("/api/preview", {"config": config, "ticks": 8})
        assert preview["ok"] and preview["ticks"] == 8
        custom = "def decide(cells, neighborhood, env, constraints, tick):\n    return []"
        assert request("/api/rules", {"source": custom})["ok"]
        assert request("/api/compose/apply", {"config": PRESETS["balanced"]})["ok"]
        assert request("/api/rules")["source"] == custom
        assert request("/api/service/apply", {"url": "http://localhost:9000/decide"})["ok"]
        assert request("/api/state")["controller_type"] == "本地模型"
        bad = request("/api/service/apply", {"url": "http://example.com:9000/decide"})
        assert not bad["ok"] and request("/api/state")["controller_type"] == "本地模型"
        assert request("/api/compose/apply", {"config": config})["ok"]
        assert executor.service_url is None
    finally:
        executor.close()
    print("CONSOLE API TEST PASSED")


if __name__ == "__main__":
    main()
