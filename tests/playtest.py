"""Playtest harness: run real matches (server + headless clients) and
record population/energy trajectories.

Usage:
  python tests/playtest.py --match grazer hunter --ticks 30 [--tick-ms 1000]
  python tests/playtest.py --match grazer hunter wall --ticks 30
Prints a per-5-tick trajectory table and the final outcome.
"""
import argparse
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


def run_match(species, ticks=30, tick_ms=1000, ws_port=18800, http_port=18100,
              seed=0):
    server = subprocess.Popen(
        [PY, "-m", "server.main", "--port", str(ws_port),
         "--http-port", str(http_port), "--tick-ms", str(tick_ms),
         "--seed", str(seed)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    clients = []
    try:
        wait_http(f"http://127.0.0.1:{http_port}/")
        for i, sp in enumerate(species):
            clients.append(subprocess.Popen(
                [PY, "-m", "client.main", "--headless",
                 "--server", f"ws://127.0.0.1:{ws_port}",
                 "--name", f"{sp}{i+1}", "--rules", f"species/{sp}.py"],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        # sample the world
        traj = []
        t0 = time.time()
        last_tick = -1
        while time.time() - t0 < ticks * tick_ms / 1000 + 15:
            try:
                snap = get(f"http://127.0.0.1:{http_port}/api/players")
            except Exception:
                time.sleep(0.5)
                continue
            tick = snap["tick"]
            if tick != last_tick and tick % 5 == 0:
                row = {p["name"]: (p["cells"], p["energy"])
                       for p in snap["players"]}
                traj.append((tick, row))
                last_tick = tick
            if tick >= ticks:
                break
            time.sleep(0.3)
        final = get(f"http://127.0.0.1:{http_port}/api/players")
        return traj, final, time.time() - t0
    finally:
        for c in clients:
            c.terminate()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", nargs="+", required=True)
    ap.add_argument("--ticks", type=int, default=30)
    ap.add_argument("--tick-ms", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ws-port", type=int, default=18800)
    ap.add_argument("--http-port", type=int, default=18100)
    args = ap.parse_args()
    traj, final, elapsed = run_match(
        args.match, ticks=args.ticks, tick_ms=args.tick_ms,
        ws_port=args.ws_port, http_port=args.http_port, seed=args.seed)
    print(f"match {' vs '.join(args.match)}: {args.ticks} ticks "
          f"in {elapsed:.1f}s (target {args.ticks * args.tick_ms / 1000:.0f}s)")
    for tick, row in traj:
        cells = "  ".join(f"{n}: {c}c/{e}e" for n, (c, e) in row.items())
        print(f"  tick {tick:3d}: {cells}")
    print("  final:", {p["name"]: (p["cells"], p["energy"])
                       for p in final["players"]})
    print("  totals:", final.get("totals", {}))


if __name__ == "__main__":
    main()
