"""Network layer (spec section 3) + spectator HTTP service.

One websockets server on the game port:
  path "/"          game clients (hello / submit_rules / intentions ...)
  path "/spectate"  spectators (snapshot once, then deltas, no login)
One stdlib HTTP server on the spectator port serves spectator.html and
a JSON polling fallback (GET /api/snapshot, GET /api/players).

The main process keeps a mirror copy of the world (updated from sim
deltas) so snapshots can be served without touching the sim process.
"""
import asyncio
import itertools
import time
from collections import deque
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from cellgame import __version__
from cellgame.shared.chat import CHAT_HISTORY_LIMIT, CHAT_INTERVAL_SECONDS, validate_chat_text
from cellgame.shared.manifest import build_manifest, is_legacy, manifest_hash
from cellgame.shared.models import WorldArrays
from cellgame.shared.profiles import default_color, validate_profile
from cellgame.shared.protocol import array_to_b64, decode_msg, encode_msg, integer_rows
from cellgame.shared.contract import PROTOCOL_VERSION, CONTRACT_VERSION, MAX_SILENT_TICKS, describe_contract, protocol_schema, negotiate_protocol
from cellgame.shared.tick_utils import apply_delta

try:
    from websockets.asyncio.server import serve
except ImportError:  # websockets < 13
    from websockets.server import serve



def _ws_path(ws, path_arg=None):
    if path_arg:
        return path_arg
    p = getattr(ws, "path", None)
    if p:
        return p
    req = getattr(ws, "request", None)
    if req is not None:
        return getattr(req, "path", "/")
    return "/"


class GameServer:
    def __init__(self, cmd_queue, event_queue, host="0.0.0.0", port=8765,
                 http_port=8080, sim_proc=None, world_config=None, manifest=None):
        self.manifest = manifest or build_manifest()
        self.legacy = is_legacy(self.manifest)
        self.manifest_digest = manifest_hash(self.manifest)
        self.sim_proc = sim_proc
        self.cmd_queue = cmd_queue
        self.event_queue = event_queue
        self.host = host
        self.port = port
        self.http_port = http_port
        self.world_config = world_config or {}
        self.players = {}          # pid -> {"ws": ws, "name": str, "rules": str}
        self.spectators = set()    # websockets
        self._pid_counter = itertools.count(1)
        self._chat_counter = itertools.count(1)
        self.chat_clock = time.monotonic
        self.chat_history = deque(maxlen=CHAT_HISTORY_LIMIT)
        self.world = None          # WorldArrays mirror (None until snapshot)
        self.world_tick = 0
        self.totals = {"move": 0, "attack": 0, "reproduce": 0, "eat": 0,
                       "change": 0, "state": 0, "die": 0, "ecology_deaths": 0}
        self.latest_summary = {}
        self.organism_stats = {}
        self.log_lines = []
        self.loop = None

    def log(self, line):
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-200:]
        print(f"[server] {line}", flush=True)

    # -- world mirror ------------------------------------------------------
    def apply_snapshot(self, arrays_dict):
        self.world = WorldArrays.from_dict(
            arrays_dict, arrays_dict["owner"].shape[1], arrays_dict["owner"].shape[0])
        self.world_tick = 0

    def apply_delta_to_mirror(self, delta):
        if self.world is None:
            return
        apply_delta(self.world, delta["changes"])
        for field, value in delta.get("environment", {}).items():
            setattr(self.world, field, value.copy())
        self.world_tick = delta["tick"]
        self.organism_stats.update(delta.get("organism_updates", {}))
        for key in delta.get("organism_removed", []):
            self.organism_stats.pop(key, None)

    def snapshot_payload(self):
        if self.world is None:
            return None
        return {
            "tick": self.world_tick,
            "arrays": {f: array_to_b64(getattr(self.world, f))
                       for f in ("owner", "species", "cell_type", "state",
                                 "energy", "env_temp", "env_food", "env_biome", "env_material", "blocks", "bonds", "organism")},
            "organisms": self.organism_stats,
        }

    def players_summary(self):
        out = []
        if self.world is None:
            return out
        for pid, info in list(self.players.items()):
            mask = self.world.owner == pid
            public = self.map_public
            out.append({
                "player_id": pid,
                "name": info["name"],
                "color": info.get("color", default_color(pid)),
                "cells": int(mask.sum()) if public else None,
                "energy": (int(self.world.energy[mask].sum()) if mask.any() else 0) if public else None,
            })
        return out

    # -- websocket handlers --------------------------------------------------
    async def handler(self, ws, path_arg=None):
        path = _ws_path(ws, path_arg)
        if path == "/spectate":
            await self.handle_spectator(ws)
        else:
            await self.handle_game(ws)

    async def handle_game(self, ws):
        pid = None
        try:
            async for raw in ws:
                try:
                    mtype, payload = decode_msg(raw)
                except Exception:
                    await ws.send(encode_msg("error", code="bad_message",
                                             message="unparsable message"))
                    continue
                if mtype == "hello":
                    if pid is not None:
                        await ws.send(encode_msg("error", code="bad_message", message="已经加入世界"))
                        continue
                    try:
                        selected_protocol = negotiate_protocol(payload.get("protocol_version"), payload.get("protocol_versions"), legacy=self.legacy)
                    except ValueError:
                        model = self.manifest["perception"]["model"]
                        await ws.send(encode_msg(
                            "error", code="protocol_unsupported",
                            message=(f"此世界使用 {model} 感知，需要支持协议 v{PROTOCOL_VERSION} "
                                     "的新版客户端，请更新客户端。")))
                        await ws.close()
                        return
                    pid = next(self._pid_counter)
                    try:
                        name, color = validate_profile(payload.get("player_name", f"player{pid}"),
                                                       payload.get("player_color") or default_color(pid))
                    except ValueError as exc:
                        pid = None
                        await ws.send(encode_msg("error", code="bad_profile", message=str(exc)))
                        continue
                    self.players[pid] = {"ws": ws, "name": name, "color": color, "rules": ""}
                    self.cmd_queue.put(("join", pid, name, color))
                    # the sim's first snapshot event may still be in
                    # flight; wait briefly for the world mirror. Players in
                    # non-legacy worlds never receive it, so skip the work.
                    snap = None
                    for _ in range(30 if self.legacy else 0):
                        snap = self.snapshot_payload()
                        if snap is not None:
                            break
                        await asyncio.sleep(0.1)
                    world = self.manifest["world"]
                    await ws.send(encode_msg(
                        "welcome", player_id=pid, world_w=world["width"], world_h=world["height"],
                        tick_rate_ms=self.world_config.get("tick_ms", 3000),
                        intention_window_ms=self.world_config.get("deadline_ms", int(self.world_config.get("tick_ms", 3000) * 5 / 6)),
                        max_silent_ticks=MAX_SILENT_TICKS,
                        ruleset_summary="demo v0.2", player_name=name,
                        player_color=color, features={"chat": True},
                        protocol_version=selected_protocol, contract_version=CONTRACT_VERSION,
                        interfaces=describe_contract()["interfaces"],
                        intention_format=1 if self.legacy else 2,
                        manifest=self.manifest, manifest_hash=self.manifest_digest,
                        players=[{"player_id": p, "name": info["name"], "color": info["color"]}
                                 for p, info in self.players.items()]))
                    # Players in non-legacy worlds only learn what they perceive.
                    if snap is not None and self.legacy:
                        await ws.send(encode_msg("world_snapshot", **snap))
                    await ws.send(encode_msg("chat_history", messages=list(self.chat_history)))
                    self.log(f"player {pid} ({name}) joined")
                elif mtype == "update_profile" and pid is not None:
                    try:
                        name, color = validate_profile(payload.get("name"), payload.get("color"))
                    except ValueError as exc:
                        await ws.send(encode_msg("error", code="profile_error", message=str(exc),
                                                 request_id=payload.get("request_id")))
                        continue
                    self.players[pid]["name"] = name
                    self.players[pid]["color"] = color
                    self.cmd_queue.put(("profile", pid, name, color))
                    updated = encode_msg("player_updated", player_id=pid, name=name,
                                         color=color, request_id=payload.get("request_id"))
                    # A slow spectator or another player must not delay the
                    # originating client's confirmation.
                    await ws.send(updated)
                    await self.broadcast(updated, skip=pid)
                elif mtype == "chat_send" and pid is not None:
                    request_id = payload.get("request_id")
                    # Request IDs are opaque and bounded, never player-supplied identities.
                    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
                        await ws.send(encode_msg("chat_error", message="消息请求无效", request_id=None))
                        continue
                    try:
                        text = validate_chat_text(payload.get("text"))
                        now = self.chat_clock()
                        previous = self.players[pid].get("last_chat_time")
                        if previous is not None and now - previous < CHAT_INTERVAL_SECONDS:
                            raise ValueError("发送太快，请稍等一秒")
                    except ValueError as exc:
                        await ws.send(encode_msg("chat_error", message=str(exc), request_id=request_id))
                        continue
                    self.players[pid]["last_chat_time"] = now
                    info = self.players[pid]
                    message = {"id": next(self._chat_counter), "player_id": pid, "name": info["name"],
                               "color": info["color"], "text": text, "timestamp": time.time(),
                               "request_id": request_id}
                    self.chat_history.append(message)
                    # Keep chat independent of the simulation process.
                    await self.broadcast(encode_msg("chat_message", **message))
                elif mtype == "submit_rules":
                    if pid is not None:
                        self.players[pid]["rules"] = payload.get("source_code", "")
                        self.players[pid]["species_name"] = payload.get("species_name", "")
                        self.log(f"player {pid} submitted rules "
                                 f"({payload.get('species_name', '?')})")
                elif mtype == "intentions":
                    if pid is None:
                        continue
                    # One message per player per tick: later or repeated ticks
                    # are dropped here so a flood cannot crowd out the sim.
                    tick = payload.get("tick")
                    last = self.players[pid].get("last_intent_tick")
                    if type(tick) is not int or (last is not None and tick <= last):
                        continue
                    try:
                        if self.legacy:
                            from cellgame.shared.models import INTENTION_DTYPE
                            value = payload.get("data")
                            if isinstance(value, np.ndarray) and value.dtype.fields is not None:
                                if value.ndim != 1 or value.dtype.names != INTENTION_DTYPE.names:
                                    raise ValueError("无效的 v1 行动字段")
                                if any(value.dtype.fields[n][0].kind not in "iu" for n in value.dtype.names):
                                    raise ValueError("行动字段必须为整数")
                                value = np.column_stack([value[n] for n in value.dtype.names])
                            rows = integer_rows(value, 7, self.manifest["world"]["width"] * self.manifest["world"]["height"])
                            # No silent overflow when narrowing into the legacy struct.
                            for k, name in enumerate(INTENTION_DTYPE.names):
                                limit = np.iinfo(INTENTION_DTYPE.fields[name][0])
                                if np.any((rows[:, k] < limit.min) | (rows[:, k] > limit.max)):
                                    raise ValueError("行动字段超出范围")
                            arr = np.empty(len(rows), dtype=INTENTION_DTYPE)
                            for k, name in enumerate(INTENTION_DTYPE.names):
                                arr[name] = rows[:, k]
                        else:
                            arr = self.validate_v2_intentions(payload)
                    except (ValueError, TypeError, KeyError) as exc:
                        await ws.send(encode_msg("error", code="bad_intentions", message=str(exc)))
                        continue
                    observed_tick = self.players[pid].get("last_observation_tick")
                    if observed_tick is None or tick != observed_tick:
                        await ws.send(encode_msg("error", code="bad_tick", message="行动不属于当前观察时刻"))
                        continue
                    self.players[pid]["last_intent_tick"] = tick
                    self.cmd_queue.put(("intentions", pid, payload.get("tick"), arr))
                elif mtype == "ping":
                    await ws.send(encode_msg("pong"))
        finally:
            if pid is not None:
                self.players.pop(pid, None)
                self.cmd_queue.put(("leave", pid))
                self.log(f"player {pid} left (disconnect -> death)")

    def client_supported(self, version):
        try:
            negotiate_protocol(version, legacy=self.legacy)
            return True
        except ValueError:
            return False

    def validate_v2_intentions(self, payload):
        """Shape check only; ownership and legality are checked by the sim."""
        if type(payload.get("format")) is not int or payload["format"] != 2:
            raise ValueError("此世界需要 v2 格式的行动提议 [cell_id, action, dx, dy, param]")
        world = self.manifest["world"]
        arr = integer_rows(payload.get("data"), 5, world["width"] * world["height"])
        if len(arr) and (np.any((arr[:, 0] < 1) | (arr[:, 0] > 4294967295)) or
                         np.any((arr[:, 1] < 0) | (arr[:, 1] > 11)) or
                         np.any((arr[:, 2:4] < -8) | (arr[:, 2:4] > 8)) or
                         np.any((arr[:, 4] < 0) | (arr[:, 4] > 2147483647))):
            raise ValueError("行动字段超出协议范围")
        return arr

    def public_settings(self):
        """World settings for the dashboard. A private map also hides the seed
        (it rebuilds the starting food map) and the world parameters."""
        if self.map_public:
            return self.world_config
        return {k: v for k, v in self.world_config.items() if k not in ("seed", "world_parameters")}

    @property
    def map_public(self):
        return self.manifest["visibility"]["spectator"] == "full"

    async def handle_spectator(self, ws):
        self.spectators.add(ws)
        try:
            snap = None
            for _ in range(30 if self.map_public else 0):
                snap = self.snapshot_payload()
                if snap is not None:
                    break
                await asyncio.sleep(0.1)
            if snap is not None:
                await ws.send(encode_msg("world_snapshot", **snap))
            await ws.send(encode_msg("chat_history", messages=list(self.chat_history)))
            async for raw in ws:
                try:
                    mtype, _ = decode_msg(raw)
                except Exception:
                    continue
                if mtype == "ping":
                    await ws.send(encode_msg("pong"))
        finally:
            self.spectators.discard(ws)

    async def send_to_player(self, pid, msg):
        info = self.players.get(pid)
        if info is None:
            return
        try:
            await info["ws"].send(msg)
        except Exception:
            pass

    async def broadcast(self, msg, skip=None, include_players=True, include_spectators=True):
        async def send_one(ws):
            try:
                await asyncio.wait_for(ws.send(msg), timeout=1.0)
            except Exception:
                pass
        peers = [info["ws"] for pid, info in list(self.players.items())
                 if pid != skip and include_players]
        if include_spectators:
            peers.extend(list(self.spectators))
        if peers:
            await asyncio.gather(*(send_one(ws) for ws in peers))

    # -- sim event pump -------------------------------------------------------
    async def sim_event_pump(self):
        loop = asyncio.get_running_loop()
        while True:
            event = await loop.run_in_executor(None, self.event_queue.get)
            kind = event[0]
            if kind == "snapshot":
                self.apply_snapshot(event[1])
            elif kind == "sense":
                _, pid, batch = event
                if pid in self.players:
                    self.players[pid]["last_observation_tick"] = batch["tick"]
                await self.send_to_player(
                    pid, encode_msg("sense_batch", **batch))
            elif kind == "observation":
                _, pid, observation = event
                if pid in self.players:
                    self.players[pid]["last_observation_tick"] = observation["tick"]
                await self.send_to_player(pid, encode_msg("observation", **observation))
            elif kind == "delta":
                delta = event[1]
                self.apply_delta_to_mirror(delta)
                await self.broadcast(encode_msg("world_delta", **delta),
                                     include_players=self.legacy,
                                     include_spectators=self.map_public)
            elif kind == "player_joined":
                _, pid, name, *extra = event
                info = self.players.get(pid)
                color = (info["color"] if info else (extra[0] if extra else default_color(pid)))
                name = info["name"] if info else name
                await self.broadcast(encode_msg(
                    "player_joined", player_id=pid, species_name=name, color=color))
            elif kind == "player_died":
                _, pid, reason = event
                await self.broadcast(encode_msg(
                    "player_left", player_id=pid, reason=reason))
                self.log(f"player {pid} died ({reason})")
            elif kind == "tick":
                if len(event) > 2 and isinstance(event[2], dict):
                    self.latest_summary = event[2]
                if len(event) > 3 and isinstance(event[3], dict):
                    for k, v in event[3].items():
                        if k in self.totals:
                            self.totals[k] += int(v)
            elif kind == "log":
                self.log(event[1])

    # -- spectator HTTP ---------------------------------------------------------
    def start_http(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, ctype):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _local(self):
                import ipaddress
                try:
                    return ipaddress.ip_address(self.client_address[0]).is_loopback
                except (ValueError, AttributeError, IndexError):
                    return False

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    with open(__import__("os").path.join(
                            __import__("os").path.dirname(__file__),
                            "spectator.html"), "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                elif self.path == "/world-view.js":
                    os = __import__("os")
                    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    with open(os.path.join(root, "shared", "world_view.js"), "rb") as f:
                        self._send(200, f.read(), "text/javascript; charset=utf-8")
                elif self.path == "/api/contract":
                    self._send(200, json.dumps(describe_contract()), "application/json")
                elif self.path == "/api/protocol-schema":
                    self._send(200, json.dumps(protocol_schema()), "application/schema+json")
                elif self.path == "/api/admin/snapshot":
                    # Full world is available only from the host itself; public
                    # spectator policy still applies to all remote connections.
                    local = self._local()
                    snap = server.snapshot_payload() if local else None
                    if not local:
                        self._send(403, json.dumps({"error": "仅服务器本机可查看完整地图"}), "application/json")
                    elif snap is None:
                        self._send(503, json.dumps({"error": "no snapshot yet"}), "application/json")
                    else:
                        self._send(200, json.dumps(snap), "application/json")
                elif self.path == "/api/snapshot":
                    snap = server.snapshot_payload() if server.map_public else None
                    if not server.map_public:
                        self._send(403, json.dumps({"error": "此世界不对观察者公开地图"}),
                                   "application/json")
                    elif snap is None:
                        self._send(503, json.dumps({"error": "no snapshot yet"}),
                                   "application/json")
                    else:
                        self._send(200, json.dumps({
                            "tick": snap["tick"], "arrays": snap["arrays"],
                            "players": server.players_summary(),
                        }), "application/json")
                elif self.path.startswith("/api/organism?"):
                    from urllib.parse import parse_qs, urlsplit
                    if not server.map_public and not self._local():
                        self._send(403, json.dumps({"error": "此世界不对观察者公开地图"}), "application/json")
                        return
                    try:
                        params = parse_qs(urlsplit(self.path).query)
                        x, y = int(params["x"][0]), int(params["y"][0])
                        world = server.world
                        if world is None or not (0 <= x < world.w and 0 <= y < world.h):
                            raise ValueError("坐标无效")
                        oid = int(world.organism[y, x])
                        organism = server.organism_stats.get(str(oid)) if oid else None
                        if organism:
                            mask = world.organism == oid
                            organism = {**organism, "cells": int(mask.sum()), "energy": int(world.energy[mask].sum()),
                                        "owner_name": server.players.get(organism["owner"], {}).get("name", f"#{organism['owner']}")}
                        self._send(200, json.dumps({"organism": organism}), "application/json")
                    except (KeyError, ValueError, IndexError):
                        self._send(400, json.dumps({"error": "坐标无效"}), "application/json")
                elif self.path == "/api/players":
                    self._send(200, json.dumps({
                        "tick": server.world_tick,
                        "players": server.players_summary(),
                        "map_visibility": "full" if server.map_public else "none",
                        "version": __version__,
                        "totals": server.totals if server.map_public else None,
                        "mean_temp": server.latest_summary.get("mean_temp"),
                        "constraints": server.latest_summary.get("constraints", {}),
                        "game_port": server.port,
                        "http_port": server.http_port,
                        "settings": server.public_settings(),
                        "world_ready": server.world is not None,
                        "sim_alive": server.sim_proc.is_alive() if server.sim_proc is not None else True,
                        "log": server.log_lines[-40:],
                    }), "application/json")
                else:
                    self._send(404, "not found", "text/plain")

        httpd = ThreadingHTTPServer((self.host, self.http_port), Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        shown = "localhost" if self.host in ("0.0.0.0", "::") else self.host
        self.log(f"spectator page at http://{shown}:{self.http_port}/")
        return httpd

    async def watchdog(self):
        # the sim runs in another process; if it dies the world freezes
        # silently, so say so loudly instead of serving a stale world.
        while True:
            await asyncio.sleep(2)
            if self.sim_proc is not None and not self.sim_proc.is_alive():
                self.log("SIM PROCESS DIED -- world is frozen, restart server")
                return

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.start_http()
        asyncio.create_task(self.sim_event_pump())
        if self.sim_proc is not None:
            asyncio.create_task(self.watchdog())
        async with serve(self.handler, self.host, self.port,
                      max_size=32 * 1024 * 1024):  # full snapshots are ~2MB
            self.log(f"game server listening on ws://{self.host}:{self.port}")
            await asyncio.Future()  # run forever
