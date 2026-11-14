"""M1 over the wire: a radius-perception server rejects old clients clearly,
sends observations instead of the full map, accepts v2 intentions, and the
stock client plays in it."""
import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cellgame.shared.models import Action
from cellgame.shared.observation import EMPTY, expand_observation
from cellgame.shared.protocol import decode_msg, encode_msg

try:
    from websockets.asyncio.client import connect
except ImportError:  # websockets < 13
    from websockets.client import connect

WS_PORT, HTTP_PORT, CLIENT_PORT = 18965, 18966, 18967
URL = f"ws://127.0.0.1:{WS_PORT}"


async def receive(ws, wanted, timeout=8.0):
    """Return (message type, payload) for the first wanted message, and the
    set of every type seen before it."""
    seen = set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mtype, payload = decode_msg(await asyncio.wait_for(ws.recv(), timeout))
        seen.add(mtype)
        if mtype in wanted:
            return mtype, payload, seen
    raise AssertionError(f"no {wanted} within {timeout}s (saw {seen})")


async def old_client_is_rejected():
    async with connect(URL) as ws:
        await ws.send(encode_msg("hello", player_name="old", protocol_version=1))
        mtype, payload, seen = await receive(ws, {"error", "welcome"})
        assert mtype == "error" and payload["code"] == "protocol_unsupported", payload
        assert "welcome" not in seen
        try:
            await asyncio.wait_for(ws.recv(), 3)
        except Exception:
            return  # closed by the server
        raise AssertionError("server kept an unsupported client connected")


async def future_client_is_rejected():
    async with connect(URL) as ws:
        await ws.send(encode_msg("hello", player_name="future", protocol_version=99))
        mtype, payload, _ = await receive(ws, {"error", "welcome"})
        assert mtype == "error" and payload["code"] == "protocol_unsupported", payload


async def new_client_plays_with_v2():
    async with connect(URL, max_size=32 * 1024 * 1024) as ws:
        await ws.send(encode_msg("hello", player_name="v2", protocol_version=99, protocol_versions=[99,2]))
        _, welcome, _ = await receive(ws, {"welcome"})
        manifest = welcome["manifest"]
        assert welcome["protocol_version"] == 2 and welcome["intention_format"] == 2
        assert welcome["contract_version"] == "1.0.0-rc.1"
        assert manifest["perception"] == {"model": "radius", "radius": 2, "metric": "chebyshev"}
        assert welcome["manifest_hash"].startswith("sha256:")
        _, wire, seen = await receive(ws, {"observation"})
        assert not seen & {"world_snapshot", "world_delta", "sense_batch"}, seen
        assert wire["version"] == 2 and wire["manifest"] == welcome["manifest_hash"]
        assert "percepts" not in wire and len(wire["tiles"]) >= 25
        obs = expand_observation(wire, manifest)
        cells, percepts = obs["cells"], obs["percepts"]
        assert len(cells) > 0 and len(percepts) == 25 * len(cells)

        move = None
        for row, cell in enumerate(cells):
            for p in percepts[percepts["observer"] == row]:
                if p["occupant"] == EMPTY and max(abs(int(p["dx"])), abs(int(p["dy"]))) == 1:
                    move = (int(cell["cell_id"]), int(p["dx"]), int(p["dy"]),
                            int(cell["x"]) + int(p["dx"]), int(cell["y"]) + int(p["dy"]))
                    break
            if move:
                break
        assert move, "no free neighbor"
        cell_id, dx, dy, tx, ty = move
        rows = np.array([[cell_id, int(Action.MOVE), dx, dy, 0]], dtype=np.int32)
        # A malformed or future proposal must not consume the current/future tick.
        await ws.send(encode_msg("intentions", tick=obs["tick"], format=2, data=[[cell_id,0.1,dx,dy,0]]))
        _, error, _ = await receive(ws, {"error"})
        assert error["code"] == "bad_intentions"
        await ws.send(encode_msg("intentions", tick=obs["tick"]+10_000, format=2, data=[]))
        _, error, _ = await receive(ws, {"error"})
        assert error["code"] == "bad_tick"
        await ws.send(encode_msg("intentions", tick=obs["tick"], format=2, data=rows))
        # A second message for the same tick is dropped, not processed.
        await ws.send(encode_msg("intentions", tick=obs["tick"], format=2, data="garbage"))
        await ws.send(encode_msg("intentions", tick=obs["tick"] + 10_000, format=2, data="garbage"))
        _, error, _ = await receive(ws, {"error"})
        assert error["code"] == "bad_intentions", error
        for _ in range(4):
            _, nxt, seen = await receive(ws, {"observation"})
            assert not seen & {"world_snapshot", "world_delta"}, seen
            moved = nxt["cells"][nxt["cells"]["cell_id"] == cell_id]
            if len(moved) and (int(moved[0]["x"]), int(moved[0]["y"])) == (tx, ty):
                return
        raise AssertionError("cell did not move with a v2 intention")


def stock_client_plays():
    client = subprocess.Popen(
        [sys.executable, "-m", "client.main", "--server", URL, "--name", "stock",
         "--rules", "species/grazer.py", "--http-port", str(CLIENT_PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        last = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{CLIENT_PORT}/api/state", timeout=2) as r:
                    last = json.load(r)
                if last.get("connected") and last.get("tick", 0) >= 3 and last.get("last_exec_ms") is not None:
                    assert not last.get("last_exec_error"), last["last_exec_error"]
                    assert last.get("perception", {}).get("model") == "radius", last.get("perception")
                    mine = [p for p in last.get("players", []) if p.get("cells")]
                    assert mine, last.get("players")
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.3)
        raise AssertionError(f"stock client did not play: {last}")
    finally:
        client.terminate()
        client.wait(timeout=5)


def main():
    server = subprocess.Popen(
        [sys.executable, "-m", "server.main", "--host", "127.0.0.1", "--port", str(WS_PORT),
         "--http-port", str(HTTP_PORT), "--tick-ms", "500",
         "--perception", "radius", "--sense-radius", "2"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        asyncio.run(old_client_is_rejected())
        asyncio.run(future_client_is_rejected())
        asyncio.run(new_client_plays_with_v2())
        subprocess.run([sys.executable, "-m", "cellgame.examples.protocol_agent", "--server", URL, "--ticks", "2"], cwd=ROOT, timeout=15, check=True)
        stock_client_plays()
        print("PROTOCOL V2 E2E TEST PASSED")
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    main()
