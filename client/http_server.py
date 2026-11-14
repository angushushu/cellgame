"""Local console HTTP server (player console page).

Serves console.html plus a small JSON API the page polls once a second:
  GET  /                     console page
  GET  /api/state            connection, tick, players, world view, log
  GET  /api/species?name=X   one of the bundled example rule files
  POST /api/rules            {source} -> load into the executor
  POST /api/submit           {species_name} -> submit loaded rules
  POST /api/connect          {url, name} -> connect to a game server
  POST /api/disconnect       -> close the game connection
  POST /api/preview          {source?, ticks?} -> run 32x32 preview

Page <-> backend is plain HTTP polling (1s). No second WebSocket: the
page is local, polling is simpler and robust, and the tick is 3s anyway.
"""
import asyncio
import base64
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from .preview import run_preview_isolated
from cellgame.species.composer import PRESETS, build_source, validate_config
from cellgame.shared.profiles import default_color, validate_profile
from cellgame.shared.chat import validate_chat_text


from cellgame import __version__ as CLIENT_VERSION

WORLD_RULE_KEYS = ("reproduce_min_energy", "reproduce_cost", "child_energy", "move_cost",
                   "eat_gain", "attack_cost", "metabolism_interval", "reproduce_enabled")


class ConsoleServer:
    def __init__(self, state, executor, client, host="127.0.0.1", port=8081):
        self.state = state
        self.executor = executor
        self.client = client
        self.host = host
        self.port = port
        self.httpd = None

    # -- API helpers ---------------------------------------------------------
    def state_payload(self):
        st = self.state
        with st.lock:
            world = st.world
            tick = st.tick
            players = dict(st.players)
            log = list(st.log)
            connected = st.connected
            connecting = st.connecting
            connection_error = st.connection_error
            server_url = st.server_url
            player_name = st.player_name
            player_color = st.player_color
            profile_pending = bool(st.profile_pending)
            profile_error = st.profile_error
            pid = st.player_id
            last_sense = (st.last_sense_tick, st.last_sense_cells)
            exec_ms = st.last_exec_ms
            exec_err = st.last_exec_error
            rules_status = st.rules_status
            controller_type = st.controller_type
            controller_endpoint = st.controller_endpoint
            composition_config = st.composition_config
            visual_events = list(st.visual_events)
            visual_seq = st.visual_seq
            chat_messages = list(st.chat_messages)
            chat_session = st.chat_session
            chat_available = st.chat_available
            chat_pending = bool(st.chat_pending)
            chat_error = st.chat_error
            chat_last_result = st.chat_last_result
            manifest = st.manifest
            constraints = dict(st.constraints)
            known = st.known
            seen = None if st.seen is None else st.seen.copy()
        view_b64 = None
        owner_b64 = None
        type_b64 = None
        food_b64 = None
        biome_b64 = None
        material_b64 = None
        bonds_b64 = None
        organism_b64 = None
        stats = []
        seen_b64 = None
        # The map shows what the player knows; the statistics only what it sees now.
        stats_world, world = world, (known if known is not None else world)
        if seen is not None:
            seen_b64 = base64.b64encode(seen.tobytes()).decode("ascii")
        if world is not None:
            # 1 byte per cell: species id (mod 256) -- the page colors it
            view_b64 = base64.b64encode(
                (world.species.astype(np.uint8)).tobytes()).decode("ascii")
            owner_b64 = base64.b64encode(world.owner.astype("<i4").tobytes()).decode("ascii")
            type_b64 = base64.b64encode(world.cell_type.astype("<i2").tobytes()).decode("ascii")
            bonds_b64 = base64.b64encode(world.bonds.tobytes()).decode("ascii")
            biome_b64 = base64.b64encode(world.env_biome.tobytes()).decode("ascii")
            material_b64 = base64.b64encode(world.env_material.tobytes()).decode("ascii")
            organism_b64 = base64.b64encode(world.organism.astype("<i4").tobytes()).decode("ascii")
            # 1 byte per cell: food amount, scaled (0 = none)
            food_b64 = base64.b64encode(
                np.clip(world.env_food * 12, 0, 255).astype(np.uint8)
                .tobytes()).decode("ascii")
            owners, counts = np.unique(stats_world.owner, return_counts=True)
            for o, c in zip(owners.tolist(), counts.tolist()):
                if o <= 0:
                    continue
                mask = stats_world.owner == o
                profile = players.get(int(o), {})
                stats.append({
                    "player_id": int(o),
                    "name": profile.get("name", f"#{int(o)}"),
                    "color": profile.get("color", default_color(int(o))),
                    "cells": int(c),
                    "energy": int(stats_world.energy[mask].sum()),
                })
        return {
            "connected": connected,
            "visual_events": visual_events,
            "visual_seq": visual_seq,
            "chat_messages": chat_messages, "chat_session": chat_session,
            "chat_available": chat_available, "chat_pending": chat_pending,
            "chat_error": chat_error, "chat_last_result": chat_last_result,
            "connecting": connecting,
            "connection_error": connection_error,
            "server_url": server_url,
            "player_name": player_name,
            "player_color": player_color,
            "profile_pending": profile_pending,
            "profile_error": profile_error,
            "player_id": pid,
            "tick": tick,
            "perception": manifest["perception"] if manifest else {"model": "legacy"},
            "world_id": manifest["id"] if manifest else "legacy",
            "world_name": manifest["name"] if manifest else "经典世界",
            "client_version": CLIENT_VERSION,
            # The server's economic rules; species settings cannot change them.
            "world_rules": {key: constraints[key] for key in WORLD_RULE_KEYS if key in constraints},
            "players": stats,
            "view_b64": view_b64,
            "owner_b64": owner_b64,
            "type_b64": type_b64, "bonds_b64": bonds_b64, "organism_b64": organism_b64,
            "food_b64": food_b64, "biome_b64": biome_b64, "material_b64": material_b64,
            "seen_b64": seen_b64,
            "world_w": world.w if world is not None else 256,
            "world_h": world.h if world is not None else 256,
            "log": [[t, m] for t, m in log[-50:]],
            "last_sense_tick": last_sense[0],
            "last_sense_cells": last_sense[1],
            "last_exec_ms": exec_ms,
            "last_exec_error": exec_err,
            "rules_status": rules_status,
            "controller_type": controller_type,
            "controller_endpoint": controller_endpoint,
            "composition_config": composition_config,
        }

    def start(self):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self):
                n = int(self.headers.get("Content-Length") or 0)
                if not n:
                    return {}
                return json.loads(self.rfile.read(n).decode("utf-8"))

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    here = os.path.dirname(os.path.abspath(__file__))
                    with open(os.path.join(here, "console.html"), "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                elif self.path == "/world-view.js":
                    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    with open(os.path.join(root, "shared", "world_view.js"), "rb") as f:
                        self._send(200, f.read(), "text/javascript; charset=utf-8")
                elif self.path == "/guide":
                    here = os.path.dirname(os.path.abspath(__file__))
                    with open(os.path.join(here, "guide.html"), "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                elif self.path.startswith("/api/organism?"):
                    from urllib.parse import parse_qs, urlsplit
                    try:
                        params = parse_qs(urlsplit(self.path).query)
                        x, y = int(params["x"][0]), int(params["y"][0])
                        with srv.state.lock:
                            world = srv.state.world
                            if world is None or not (0 <= x < world.w and 0 <= y < world.h):
                                raise ValueError("坐标无效")
                            oid = int(world.organism[y, x])
                            item = srv.state.organism_stats.get(str(oid)) if oid else None
                            if item:
                                mask = world.organism == oid
                                item = {**item, "cells": int(mask.sum()), "energy": int(world.energy[mask].sum()),
                                        "owner_name": srv.state.players.get(item["owner"], {}).get("name", f"#{item['owner']}")}
                        self._send(200, json.dumps({"organism": item}))
                    except (KeyError, ValueError, IndexError):
                        self._send(400, json.dumps({"error": "坐标无效"}))
                elif self.path == "/api/contract":
                    from cellgame.shared.contract import describe_contract
                    self._send(200, json.dumps(describe_contract()))
                elif self.path == "/api/protocol-schema":
                    from cellgame.shared.contract import protocol_schema
                    self._send(200, json.dumps(protocol_schema()), "application/schema+json")
                elif self.path == "/api/state":
                    self._send(200, json.dumps(srv.state_payload()))
                elif self.path == "/api/rules":
                    self._send(200, json.dumps(
                        {"source": srv.state.custom_rules_source or srv.state.rules_source}))
                elif self.path == "/api/presets":
                    self._send(200, json.dumps({"presets": PRESETS}))
                elif self.path.startswith("/api/species"):
                    from urllib.parse import urlparse, parse_qs
                    name = parse_qs(urlparse(self.path).query).get("name", ["grazer"])[0]
                    safe = "".join(c for c in name if c.isalnum() or c in "_-")
                    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    path = os.path.join(root, "species", f"{safe}.py")
                    if not os.path.exists(path):
                        self._send(404, json.dumps({"error": "no such species"}))
                    else:
                        with open(path, encoding="utf-8") as f:
                            self._send(200, json.dumps({"name": safe, "source": f.read()}))
                else:
                    self._send(404, json.dumps({"error": "not found"}))

            def do_POST(self):
                # The console can load local Python rules; require JSON and
                # reject cross-origin browser requests before reading a body.
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    self._send(415, json.dumps({"ok": False, "error": "需要 application/json"}))
                    return
                origin = self.headers.get("Origin")
                host = self.headers.get("Host")
                if origin and (not host or origin != "http://" + host):
                    self._send(403, json.dumps({"ok": False, "error": "来源不允许"}))
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length < 0 or length > 2 * 1024 * 1024:
                    self._send(413, json.dumps({"ok": False, "error": "请求太大"}))
                    return
                try:
                    body = self._json()
                    if not isinstance(body, dict):
                        raise ValueError("请求必须为对象")
                except (ValueError, UnicodeDecodeError) as exc:
                    self._send(400, json.dumps({"ok": False, "error": str(exc)}))
                    return
                if self.path == "/api/rules":
                    source = body.get("source", "")
                    try:
                        srv.executor.load(source)
                        srv.state.rules_source = source
                        srv.state.custom_rules_source = source
                        srv.state.rules_status = "规则已加载"
                        srv.state.controller_type = "自定义代码"
                        srv.state.controller_endpoint = ""
                        srv.state.composition_config = None
                        srv.state.add_log("规则已加载（本地）")
                        self._send(200, json.dumps({"ok": True}))
                    except Exception as e:  # noqa: BLE001 - shown in console
                        srv.state.rules_status = f"加载失败: {e}"
                        self._send(200, json.dumps({"ok": False, "error": str(e)}))
                elif self.path == "/api/submit":
                    name = body.get("species_name", "species")
                    # one click: load the editor content first if given
                    if body.get("source"):
                        try:
                            srv.executor.load(body["source"])
                            srv.state.rules_source = body["source"]
                            srv.state.custom_rules_source = body["source"]
                            srv.state.rules_status = "规则已加载"
                            srv.state.controller_type = "自定义代码"
                            srv.state.controller_endpoint = ""
                            srv.state.composition_config = None
                        except Exception as e:  # noqa: BLE001
                            self._send(200, json.dumps(
                                {"ok": False, "error": str(e)}))
                            return
                    source = srv.state.rules_source
                    if not source:
                        self._send(200, json.dumps(
                            {"ok": False, "error": "先加载规则"}))
                    else:
                        loop = srv.state.loop
                        if loop is not None:
                            fut = asyncio.run_coroutine_threadsafe(
                                srv.client.submit_rules_now(source, name), loop)
                            try:
                                fut.result(timeout=5)
                            except Exception as e:  # noqa: BLE001
                                srv.state.queue_submit(source, name)
                        else:
                            srv.state.queue_submit(source, name)
                        self._send(200, json.dumps({"ok": True}))
                elif self.path == "/api/compose/source":
                    try:
                        self._send(200, json.dumps({"ok": True, "source": build_source(body.get("config"))}))
                    except (ValueError, TypeError) as e:
                        self._send(200, json.dumps({"ok": False, "error": str(e)}))
                elif self.path == "/api/compose/apply":
                    try:
                        config = validate_config(body.get("config"))
                        source = build_source(config)
                        srv.executor.load(source)
                        with srv.state.lock:
                            srv.state.rules_source = source
                            srv.state.rules_status = "组合物种已启用"
                            srv.state.controller_type = "组合模式"
                            srv.state.controller_endpoint = ""
                            srv.state.composition_config = config
                            srv.state.last_exec_error = None
                            srv.state.last_exec_ms = None
                        srv.state.add_log("组合物种已启用")
                        self._send(200, json.dumps({"ok": True}))
                    except Exception as e:
                        self._send(200, json.dumps({"ok": False, "error": str(e)}))
                elif self.path == "/api/service/apply":
                    try:
                        url = body.get("url", "")
                        srv.executor.load_service(url)
                        with srv.state.lock:
                            srv.state.rules_status = "本地模型已启用，等待下一次响应"
                            srv.state.controller_type = "本地模型"
                            srv.state.controller_endpoint = url
                            srv.state.composition_config = None
                            srv.state.last_exec_error = None
                            srv.state.last_exec_ms = None
                        srv.state.add_log("本地模型已启用，等待观察数据")
                        self._send(200, json.dumps({"ok": True}))
                    except Exception as e:
                        self._send(200, json.dumps({"ok": False, "error": str(e)}))
                elif self.path == "/api/chat":
                    request_id = None
                    try:
                        text = validate_chat_text(body.get("text"))
                        with srv.state.lock:
                            if not srv.state.connected or srv.state.ws is None:
                                raise ValueError("请先连接世界")
                            if not srv.state.chat_available:
                                raise ValueError("当前服务器不支持公屏聊天")
                            if srv.state.chat_pending:
                                raise ValueError("上一条消息尚未确认")
                            loop = srv.state.loop
                            if loop is None:
                                raise ValueError("客户端主循环未启动")
                            request_id = uuid.uuid4().hex
                            srv.state.chat_pending = request_id
                            srv.state.chat_error = None
                            srv.state.chat_last_result = None
                        future = asyncio.run_coroutine_threadsafe(srv.client.send_chat(text, request_id), loop)
                        def completed_chat(result):
                            if result.cancelled():
                                error = "消息发送已取消"
                            else:
                                exc = result.exception()
                                error = str(exc) if exc else None
                            if error:
                                with srv.state.lock:
                                    if srv.state.chat_pending == request_id:
                                        srv.state.chat_pending = None
                                        srv.state.chat_error = error
                                        srv.state.chat_last_result = {"request_id": request_id, "error": error}
                        future.add_done_callback(completed_chat)
                        self._send(200, json.dumps({"ok": True, "pending": True, "request_id": request_id}))
                    except Exception as exc:
                        if request_id is not None:
                            with srv.state.lock:
                                if srv.state.chat_pending == request_id:
                                    srv.state.chat_pending = None
                        self._send(200, json.dumps({"ok": False, "error": str(exc)}))
                elif self.path == "/api/profile":
                    try:
                        name, color = validate_profile(body.get("name"), body.get("color"))
                        with srv.state.lock:
                            if srv.state.connecting and not srv.state.connected:
                                raise ValueError("正在连接，请稍后保存")
                            if srv.state.profile_pending:
                                raise ValueError("上一次资料更新尚未确认")
                            connected = srv.state.connected
                            loop = srv.state.loop
                            if not connected:
                                srv.state.player_name = name
                                srv.state.player_color = color
                                srv.state.profile_error = None
                            else:
                                if loop is None:
                                    raise ValueError("客户端主循环未启动")
                                request_id = uuid.uuid4().hex
                                srv.state.profile_pending = request_id
                                srv.state.profile_error = None
                        if connected:
                            future = asyncio.run_coroutine_threadsafe(
                                srv.client.update_profile(name, color, request_id), loop)
                            def completed(result):
                                if result.cancelled():
                                    error = "资料更新已取消"
                                else:
                                    exc = result.exception()
                                    error = str(exc) if exc else None
                                if error:
                                    with srv.state.lock:
                                        if srv.state.profile_pending == request_id:
                                            srv.state.profile_pending = None
                                            srv.state.profile_error = error
                            future.add_done_callback(completed)
                        self._send(200, json.dumps({"ok": True, "pending": connected}))
                    except Exception as e:
                        if "request_id" in locals():
                            with srv.state.lock:
                                if srv.state.profile_pending == request_id:
                                    srv.state.profile_pending = None
                        self._send(200, json.dumps({"ok": False, "error": str(e)}))
                elif self.path == "/api/connect":
                    url = body.get("url", "ws://localhost:8765")
                    name = body.get("name", "player")
                    loop = srv.state.loop
                    if loop is not None:
                        with srv.state.lock:
                            busy = srv.state.connected or srv.state.connecting
                        if busy:
                            self._send(200, json.dumps({"ok": False, "error": "已有连接或正在连接"}))
                            return
                        future = asyncio.run_coroutine_threadsafe(
                            srv.client.connect_and_run(url, name), loop)
                        future.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)
                        self._send(200, json.dumps({"ok": True}))
                    else:
                        self._send(200, json.dumps(
                            {"ok": False, "error": "客户端主循环未启动"}))
                elif self.path == "/api/disconnect":
                    ws = srv.state.ws
                    loop = srv.state.loop
                    if ws is not None and loop is not None:
                        asyncio.run_coroutine_threadsafe(ws.close(), loop)
                    self._send(200, json.dumps({"ok": True}))
                elif self.path == "/api/preview":
                    try:
                        ticks = int(body.get("ticks", 200))
                        source = build_source(body["config"]) if "config" in body else body.get("source") or srv.state.rules_source
                    except Exception as e:
                        self._send(200, json.dumps({"ok": False, "error": str(e)}))
                        return
                    if not source:
                        self._send(200, json.dumps(
                            {"ok": False, "error": "先加载规则"}))
                    else:
                        try:
                            result = run_preview_isolated(source, ticks=ticks)
                            self._send(200, json.dumps({"ok": True, **result}))
                        except Exception as e:  # noqa: BLE001
                            self._send(200, json.dumps(
                                {"ok": False, "error": str(e)}))
                else:
                    self._send(404, json.dumps({"error": "not found"}))

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()
        print(f"[client] console page at http://{self.host}:{self.port}/",
              flush=True)
        return self.httpd
