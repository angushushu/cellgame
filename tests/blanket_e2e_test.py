"""M2 over the wire: the deep-dive preset serves blanket observations with
roles, sense and events; the stock client plays it with a known-map view; and
a world with spectator visibility "none" keeps its map from the dashboard."""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cellgame.shared.models import Action
from cellgame.shared.observation import BOUNDARY, EVENT_RESULT, R_OK, expand_observation
from cellgame.shared.protocol import decode_msg, encode_msg

try:
    from websockets.asyncio.client import connect
except ImportError:  # websockets < 13
    from websockets.client import connect

WS, HTTP, CLIENT_HTTP = 19065, 19066, 19067
WS2, HTTP2 = 19075, 19076


def start_server(port, http_port, *extra):
    return subprocess.Popen(
        [sys.executable, "-m", "server.main", "--host", "127.0.0.1", "--port", str(port),
         "--http-port", str(http_port), "--tick-ms", "500", *extra],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


async def receive(ws, wanted, timeout=8.0):
    deadline = time.monotonic() + timeout
    seen = set()
    while time.monotonic() < deadline:
        mtype, payload = decode_msg(await asyncio.wait_for(ws.recv(), timeout))
        seen.add(mtype)
        if mtype in wanted:
            return mtype, payload, seen
    raise AssertionError(f"no {wanted} (saw {seen})")


async def sense_round_trip():
    async with connect(f"ws://127.0.0.1:{WS}", max_size=32 * 1024 * 1024) as ws:
        await ws.send(encode_msg("hello", player_name="diver", protocol_version=2))
        _, welcome, _ = await receive(ws, {"welcome"})
        manifest = welcome["manifest"]
        assert manifest["id"] == "deep-dive" and manifest["perception"]["model"] == "blanket"
        _, wire, _ = await receive(ws, {"observation"})
        cells = wire["cells"]
        assert set(cells["role"].tolist()) <= {BOUNDARY, 2} and BOUNDARY in cells["role"]
        cell = cells[cells["role"] == BOUNDARY][0]
        cid = int(cell["cell_id"])
        rows = np.array([[cid, int(Action.SENSE), 0, 0, 3]], dtype=np.int64)
        await ws.send(encode_msg("intentions", tick=wire["tick"], format=2, data=rows))
        _, nxt, _ = await receive(ws, {"observation"})
        mine = nxt["cells"][nxt["cells"]["cell_id"] == cid]
        assert len(mine) and int(mine[0]["sense_radius"]) == 3, nxt["cells"]
        results = [e for e in nxt["events"] if e["kind"] == EVENT_RESULT and int(e["cell_id"]) == cid]
        assert results and int(results[0]["code"]) == R_OK, nxt["events"]
        expanded = expand_observation(nxt, manifest)
        row = int(np.where(nxt["cells"]["cell_id"] == cid)[0][0])
        assert (expanded["percepts"]["observer"] == row).sum() >= 16


def stock_client_plays():
    client = subprocess.Popen(
        [sys.executable, "-m", "client.main", "--server", f"ws://127.0.0.1:{WS}", "--name", "stock",
         "--rules", "species/grazer.py", "--http-port", str(CLIENT_HTTP)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline, last = time.monotonic() + 30, None
        while time.monotonic() < deadline:
            try:
                last = get_json(f"http://127.0.0.1:{CLIENT_HTTP}/api/state")
                if last.get("connected") and last.get("tick", 0) >= 4 and last.get("seen_b64"):
                    assert not last.get("last_exec_error"), last["last_exec_error"]
                    assert last["perception"]["model"] == "blanket"
                    seen = np.frombuffer(__import__("base64").b64decode(last["seen_b64"]), dtype=np.uint8)
                    assert (seen == 1).any() and (seen == 0).any()
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.3)
        raise AssertionError(f"stock client did not play deep-dive: {last}")
    finally:
        client.terminate()
        client.wait(timeout=5)


async def spectator_sees_no_map():
    async with connect(f"ws://127.0.0.1:{WS2}/spectate") as ws:
        _, _, seen = await receive(ws, {"chat_history"})
        assert "world_snapshot" not in seen
        try:
            while True:
                mtype, _ = decode_msg(await asyncio.wait_for(ws.recv(), 2))
                assert mtype not in ("world_snapshot", "world_delta"), mtype
        except asyncio.TimeoutError:
            pass


def hidden_dashboard():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{HTTP2}/api/snapshot", timeout=3)
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError("snapshot should be forbidden")
    status = get_json(f"http://127.0.0.1:{HTTP2}/api/players")
    assert status["map_visibility"] == "none"
    # The seed rebuilds the starting food map; world-wide totals reveal activity.
    assert "seed" not in status["settings"] and "world_parameters" not in status["settings"]
    assert status["totals"] is None
    asyncio.run(spectator_sees_no_map())


def main():
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / "private_world.py"
        private.write_text(
            "from cellgame.server.worlds.deep_dive import MANIFEST as BASE, on_epoch, on_event\n"
            "MANIFEST = {**BASE, 'visibility': {**BASE['visibility'], 'spectator': 'none'}}\n",
            encoding="utf-8")
        servers = [start_server(WS, HTTP, "--world-preset", "deep-dive"),
                   start_server(WS2, HTTP2, "--world-rules", str(private))]
        try:
            time.sleep(2)
            asyncio.run(sense_round_trip())
            stock_client_plays()
            hidden_dashboard()
            print("BLANKET E2E TEST PASSED")
        finally:
            for server in servers:
                server.terminate()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
