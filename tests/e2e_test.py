"""End-to-end test (verification step 2).

Starts the real server (1s ticks for speed), connects two real
headless clients with the grazer/hunter rules, verifies the
sense_batch -> intentions -> world-change flow over the wire, then
disconnects one client and verifies its cells die in the next ticks.
Also checks the spectator page serves HTTP 200.
Usage: python tests/e2e_test.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
WS_PORT = 18765
HTTP_PORT = 18080


def wait_http(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status
        except Exception:
            time.sleep(0.5)
    return None


async def spectator_probe():
    """Connect as a spectator, take a snapshot, watch a few deltas."""
    from websockets.asyncio.client import connect
    from shared.protocol import decode_msg, b64_to_array
    import numpy as np
    async with connect(f"ws://127.0.0.1:{WS_PORT}/spectate",
                      max_size=32 * 1024 * 1024) as ws:
        owner = None
        tick = -1
        seen_delta = False
        t0 = time.time()
        while time.time() - t0 < 15:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                continue
            mtype, payload = decode_msg(raw)
            if mtype == "world_snapshot":
                owner = b64_to_array(payload["arrays"]["owner"]).copy()
                tick = payload["tick"]
            elif mtype == "world_delta":
                tick = payload["tick"]
                seen_delta = True
                if owner is not None and len(payload["changes"]):
                    from shared.tick_utils import apply_delta
                    from shared.models import WorldArrays
                    # minimal apply: track owner only
                    ch = payload["changes"]
                    for row in ch:
                        x, y, o = int(row[0]), int(row[1]), int(row[2])
                        if int(row[7]) & 1:
                            owner[y, x] = o
                if seen_delta and tick >= 3 and owner is not None:
                    counts = {int(o): int((owner == o).sum())
                              for o in np.unique(owner) if o != 0}
                    return counts, tick
        return None, tick


async def main():
    server = subprocess.Popen(
        [PY, "-m", "server.main", "--port", str(WS_PORT),
         "--http-port", str(HTTP_PORT), "--tick-ms", "1000"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        status = await asyncio.to_thread(wait_http,
                                         f"http://127.0.0.1:{HTTP_PORT}/")
        assert status == 200, f"spectator page HTTP status {status}"
        print("spectator page: HTTP 200 OK")

        grazer = subprocess.Popen(
            [PY, "-m", "client.main", "--headless",
             "--server", f"ws://127.0.0.1:{WS_PORT}", "--name", "grazer1",
             "--rules", "species/grazer.py"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hunter = subprocess.Popen(
            [PY, "-m", "client.main", "--headless",
             "--server", f"ws://127.0.0.1:{WS_PORT}", "--name", "hunter1",
             "--rules", "species/hunter.py"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            counts, tick = await spectator_probe()
            assert counts, "spectator got no world data"
            print(f"live flow: tick={tick} cells per player={counts}")
            assert len(counts) >= 2, f"expected 2 players alive, got {counts}"
            assert all(c > 0 for c in counts.values()), "a player has 0 cells"
            print("sense_batch -> intentions -> world changes: OK")

            # disconnect the hunter; its cells must die within a few ticks
            hunter.terminate()
            hunter.wait(timeout=5)
            print("hunter client disconnected, waiting for death...")
            await asyncio.sleep(4)
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{HTTP_PORT}/api/players",
                    timeout=5) as r:
                players = json.loads(r.read())
            alive = {p["player_id"]: p["cells"] for p in players["players"]}
            print(f"players after disconnect: {alive}")
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{HTTP_PORT}/api/snapshot",
                    timeout=5) as r:
                snap = json.loads(r.read())
            from shared.protocol import b64_to_array
            owner = b64_to_array(snap["arrays"]["owner"]).copy()
            import numpy as np
            remaining = {int(o): int((owner == o).sum())
                         for o in np.unique(owner) if o != 0}
            print(f"world owner counts after disconnect: {remaining}")
            assert len(remaining) == 1, \
                f"expected 1 player left, got {remaining}"
            print("disconnect = death: OK")
            print("E2E TEST PASSED")
        finally:
            grazer.terminate()
            try:
                hunter.terminate()
            except Exception:
                pass
    finally:
        server.terminate()
        try:
            out, _ = server.communicate(timeout=5)
            print("--- server log (last 15 lines) ---")
            print("\n".join(out.strip().splitlines()[-15:]))
        except Exception:
            server.kill()


if __name__ == "__main__":
    asyncio.run(main())
