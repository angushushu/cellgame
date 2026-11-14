"""Profile validation and live protocol behavior with in-memory sockets."""
import asyncio
import queue
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client.net import ClientState, GameClient
from server.net import GameServer
from server.world import WorldState
from shared.profiles import validate_profile
from shared.protocol import decode_msg, encode_msg


def finish(coro):
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("unexpected async suspension in fake socket")


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration
    async def send(self, message):
        self.sent.append(decode_msg(message))


class FakeSession:
    def __init__(self, state):
        self.state = state
        self.sent = []
        self.observed = None
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def send(self, message):
        self.sent.append(decode_msg(message))
    def __aiter__(self):
        return self
    async def __anext__(self):
        self.observed = (self.state.connected, self.state.connecting)
        raise StopAsyncIteration


def main():
    assert validate_profile("  小细胞  ", "#aabbcc") == ("小细胞", "#AABBCC")
    for name, color in (("", "#ABCDEF"), ("a\nb", "#ABCDEF"), ("a", "red"), ("a", "#000000extra")):
        try:
            validate_profile(name, color)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid profile accepted")
    commands = queue.Queue()
    server = GameServer(commands, queue.Queue())
    server.apply_snapshot(WorldState(16, 16).snapshot_arrays())
    other = FakeSocket([])
    spectator = FakeSocket([])
    server.players[2] = {"ws": other, "name": "另一位", "color": "#445566", "rules": ""}
    server.spectators.add(spectator)
    ws = FakeSocket([
        encode_msg("hello", player_name="旧名字", player_color="#112233"),
        encode_msg("update_profile", name="", color="#ABCDEF", request_id="invalid"),
        encode_msg("update_profile", name="新名字", color="#aabbcc", request_id="r1"),
    ])
    asyncio.run(server.handle_game(ws))
    kinds = [kind for kind, _ in ws.sent]
    assert "welcome" in kinds and "player_updated" in kinds and "error" in kinds
    welcome = next(data for kind, data in ws.sent if kind == "welcome")
    updated = next(data for kind, data in ws.sent if kind == "player_updated")
    error = next(data for kind, data in ws.sent if kind == "error")
    assert welcome["player_name"] == "旧名字" and welcome["player_color"] == "#112233"
    assert any(p["player_id"] == 2 and p["color"] == "#445566" for p in welcome["players"])
    assert updated["name"] == "新名字" and updated["color"] == "#AABBCC" and updated["request_id"] == "r1"
    assert error["code"] == "profile_error" and error["request_id"] == "invalid"
    assert any(kind == "player_updated" and msg["color"] == "#AABBCC" for kind, msg in other.sent)
    assert any(kind == "player_updated" and msg["color"] == "#AABBCC" for kind, msg in spectator.sent)
    events = []
    while not commands.empty():
        events.append(commands.get_nowait())
    assert [e[0] for e in events] == ["join", "profile", "leave"]
    state = ClientState()
    client = GameClient(state, None)
    finish(client.handle("welcome", welcome))
    state.profile_pending = "r1"
    finish(client.handle("player_updated", updated))
    assert state.player_name == "新名字" and state.player_color == "#AABBCC"
    assert state.profile_pending is None and state.players[1]["color"] == "#AABBCC"
    state = ClientState()
    session = FakeSession(state)
    client = GameClient(state, None)
    with patch("client.net.connect", return_value=session), patch("client.net.asyncio.get_running_loop", return_value=object()):
        finish(client.connect_and_run("ws://localhost:8765", "玩家"))
    assert session.observed == (True, False), "connecting must clear while connected"
    print("PROFILE TEST PASSED")


if __name__ == "__main__":
    main()
