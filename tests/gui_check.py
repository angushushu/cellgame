"""GUI check (verification step 3).

The GUIs are web pages, so 'launch' means: the servers start, the
pages serve HTTP 200 with the expected markers, and the console API
answers. Also verifies every Python module imports cleanly.
Usage: python tests/gui_check.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PY = sys.executable


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def wait_http(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            return get(url)
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{url} never came up")


def main():
    # 1. imports
    for mod in ("shared.models", "shared.protocol", "shared.tick_utils",
                "shared.arbiter", "server.world", "server.world_rules",
                "server.sim_process", "server.net", "server.main",
                "client.executor", "client.preview", "client.net",
                "client.http_server", "client.main",
                "species.grazer", "species.hunter", "species.wall"):
        __import__(mod)
    print("all modules import cleanly")

    server = subprocess.Popen(
        [PY, "-m", "server.main", "--port", "18766", "--http-port", "18081",
         "--tick-ms", "1000"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = subprocess.Popen(
        [PY, "-m", "client.main", "--server", "ws://127.0.0.1:18766",
         "--name", "checker", "--rules", "species/grazer.py",
         "--http-port", "18082"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        status, body = wait_http("http://127.0.0.1:18081/")
        assert status == 200 and "世界控制台" in body, "spectator page bad"
        print("spectator page (server :18081): HTTP 200, marker found")
        status, body = wait_http("http://127.0.0.1:18082/")
        assert status == 200 and "物种实验室" in body, "console page bad"
        print("console page (client :18082): HTTP 200, marker found")
        status, state_raw = get("http://127.0.0.1:18082/api/state")
        state = json.loads(state_raw)
        assert status == 200 and "connected" in state, "console API bad"
        print("console /api/state answers:", state["connected"] and "connected"
              or "not connected yet (server may still be handshaking)")
        status, res = post("http://127.0.0.1:18082/api/preview",
                           {"ticks": 50})
        assert res.get("ok"), f"preview API failed: {res}"
        print(f"console preview API: ok, {res['ticks']} ticks, "
              f"final cells={res['final_cells']}")
        print("GUI CHECK PASSED")
    finally:
        client.terminate()
        server.terminate()


if __name__ == "__main__":
    main()
