"""Edge cases (round 4 playtest):
1. bad rules (syntax error) -> /api/rules ok:false, client keeps running
2. slow rules (decide sleeps 5s) -> executor timeout, empty intentions,
   client keeps playing next tick, error surfaced in state
3. disconnect + reconnect with the same name -> new player_id, fresh cells
4. spectator with no players -> empty world snapshot, page still serves
Usage: python tests/edge_test.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PY = sys.executable
WS, HTTP = 18820, 18120


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def wait_http(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{url} never came up")


def main():
    server = subprocess.Popen(
        [PY, "-m", "server.main", "--port", str(WS), "--http-port", str(HTTP),
         "--tick-ms", "1000"], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = None
    try:
        wait_http(f"http://127.0.0.1:{HTTP}/")
        # 4. spectator with no players
        snap = get(f"http://127.0.0.1:{HTTP}/api/snapshot")
        assert snap["players"] == [], f"expected no players, got {snap['players']}"
        print("4. empty world snapshot with no players: OK")

        # start a console client (default grazer)
        client = subprocess.Popen(
            [PY, "-m", "client.main", "--server", f"ws://127.0.0.1:{WS}",
             "--name", "edge1", "--http-port", "18121"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_http("http://127.0.0.1:18121/")
        time.sleep(4)
        st = get("http://127.0.0.1:18121/api/state")
        assert st["connected"] and st["player_id"], f"console did not connect: {st}"
        pid1 = st["player_id"]
        print(f"console connected as player {pid1}, cells: "
              f"{[p for p in st['players'] if p['player_id'] == pid1]}")

        # 1. bad rules
        bad = "def decide(:\n  broken!!!\n"
        res = post("http://127.0.0.1:18121/api/rules", {"source": bad})
        assert not res["ok"], f"bad rules should fail: {res}"
        print(f"1. bad rules rejected with error: {res['error'][:80]}")
        time.sleep(3)
        st = get("http://127.0.0.1:18121/api/state")
        assert st["connected"], "client died after bad rules"
        print("   client still connected after bad rules: OK")

        # 2. slow rules (5s sleep > 2s timeout)
        slow = ("import time, numpy as np\n"
                "def decide(cells, neighborhood, env, constraints, tick):\n"
                "    time.sleep(5)\n"
                "    return np.empty((0, 7), np.int32)\n")
        res = post("http://127.0.0.1:18121/api/rules", {"source": slow})
        assert res["ok"], f"slow rules should load: {res}"
        time.sleep(4)
        st = get("http://127.0.0.1:18121/api/state")
        assert st["connected"], "client died after slow rules"
        assert st["last_exec_error"] and "超时" in st["last_exec_error"], \
            f"timeout not surfaced: {st['last_exec_error']}"
        print(f"2. slow rules timed out, surfaced as: {st['last_exec_error']}")
        # restore good rules so the client plays again
        grazer = get("http://127.0.0.1:18121/api/species?name=grazer")["source"]
        res = post("http://127.0.0.1:18121/api/rules", {"source": grazer})
        assert res["ok"]
        # the slow thread keeps its 5s sleep; allow time for the pool
        # to drain (one 2s timeout) and a good run to clear the error
        recovered = False
        for _ in range(10):
            time.sleep(1)
            st = get("http://127.0.0.1:18121/api/state")
            if not st["last_exec_error"]:
                recovered = True
                break
        assert recovered, f"still erroring: {st['last_exec_error']}"
        print("   good rules restored, executor recovered: OK")

        # 3. disconnect + reconnect (same name)
        client.terminate()
        client.wait(timeout=5)
        client = None
        time.sleep(5)  # let the server kill the cells (next tick)
        snap = get(f"http://127.0.0.1:{HTTP}/api/snapshot")
        from shared.protocol import b64_to_array
        owner = b64_to_array(snap["arrays"]["owner"])
        import numpy as np
        assert int((owner == pid1).sum()) == 0, "dead player's cells remain!"
        print(f"3. after disconnect, player {pid1} cells = 0: OK")
        client = subprocess.Popen(
            [PY, "-m", "client.main", "--server", f"ws://127.0.0.1:{WS}",
             "--name", "edge1", "--http-port", "18121"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_http("http://127.0.0.1:18121/")
        time.sleep(4)
        st = get("http://127.0.0.1:18121/api/state")
        assert st["connected"] and st["player_id"] != pid1, \
            f"reconnect should get a new id: {st}"
        print(f"   reconnected as new player {st['player_id']} with fresh cells: OK")
        print("EDGE TEST PASSED")
    finally:
        if client is not None:
            client.terminate()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


if __name__ == "__main__":
    main()
