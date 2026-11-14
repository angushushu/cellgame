"""Game WebSocket client (spec section 3, client side).

Owns the connection to the game server: hello, submit_rules,
sense_batch -> executor -> intentions, world_snapshot / world_delta
into a local world mirror. State is shared with the local console HTTP
server through a thread-safe ClientState.
"""
import asyncio
import base64
import threading

import numpy as np

from cellgame.shared.chat import CHAT_HISTORY_LIMIT
from cellgame.shared.manifest import is_legacy
from cellgame.shared.models import INTENTION_DTYPE, WorldArrays
from cellgame.shared.observation import (
    expand_observation, intentions_to_v2, observation_to_world, remember, to_legacy_batch,
    visual_events,
)
from cellgame.shared.protocol import decode_msg, encode_msg
from cellgame.shared.contract import PROTOCOL_VERSION, SUPPORTED_PROTOCOLS
from cellgame.shared.profiles import default_color
from cellgame.shared.tick_utils import apply_delta

try:
    from websockets.asyncio.client import connect
except ImportError:  # websockets < 13
    from websockets.client import connect



class ClientState:
    """Thread-safe state shared between the asyncio game client and the
    local console HTTP server."""

    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.connecting = False
        self.connection_error = None
        self.player_id = None
        self.manifest = None       # None until welcome; servers before 0.2 send none
        self.known = None          # non-legacy worlds: remembered map (WorldArrays)
        self.seen = None           # 0 never seen, 1 perceived now, 2 remembered
        self.previous_cells = None # own cells in the previous observation (animations)
        self.player_name = "player"
        self.player_color = None
        self.profile_pending = None
        self.profile_error = None
        self.server_url = "ws://localhost:8765"
        self.tick = 0
        self.world = None          # WorldArrays mirror
        self.players = {}          # pid -> {"name": ..., "color": ...}
        self.log = []              # (tick, text)
        self.rules_source = ""
        self.custom_rules_source = ""
        self.rules_status = "未加载规则"
        self.controller_type = "未设置"
        self.controller_endpoint = ""
        self.composition_config = None
        self.last_sense_tick = -1
        self.last_sense_cells = 0
        self.constraints = {}      # world rules from the latest observation
        self.last_exec_ms = None
        self.last_exec_error = None
        self.organism_stats = {}
        self.visual_events = []
        self.visual_seq = 0
        self.chat_messages = []
        self.chat_session = 0
        self.chat_available = False
        self.chat_pending = None
        self.chat_error = None
        self.chat_last_result = None
        self.loop = None
        self.ws = None
        self._pending_submit = None  # (source, species_name) to send

    def add_log(self, text):
        with self.lock:
            self.log.append((self.tick, text))
            self.log = self.log[-200:]

    def queue_submit(self, source, species_name):
        with self.lock:
            self._pending_submit = (source, species_name)

    def take_pending_submit(self):
        with self.lock:
            item = self._pending_submit
            self._pending_submit = None
            return item


class GameClient:
    def __init__(self, state, executor):
        self.state = state
        self.executor = executor

    async def connect_and_run(self, url, player_name):
        st = self.state
        with st.lock:
            if st.connected or st.connecting:
                raise ValueError("已有服务器连接")
            st.connecting = True
            st.connection_error = None
            st.server_url = url
            st.player_name = player_name
        try:
            await self._connect_session(url, player_name)
        except Exception as exc:
            with st.lock:
                st.connection_error = str(exc)
            st.add_log(f"连接失败: {exc}")
            raise
        finally:
            with st.lock:
                st.connecting = False

    async def _connect_session(self, url, player_name):
        st = self.state
        async with connect(url, max_size=32 * 1024 * 1024) as ws:
            st.ws = ws
            st.loop = asyncio.get_running_loop()
            with st.lock:
                st.connected = True
                st.connecting = False
            st.add_log(f"已连接 {url}")
            await ws.send(encode_msg("hello", player_name=player_name,
                                     player_color=st.player_color,
                                     protocol_version=PROTOCOL_VERSION, protocol_versions=list(SUPPORTED_PROTOCOLS)))
            try:
                async for raw in ws:
                    try:
                        mtype, payload = decode_msg(raw)
                    except Exception:
                        continue
                    await self.handle(mtype, payload)
            finally:
                with st.lock:
                    st.connected = False
                    st.ws = None
                    st.chat_available = False
                    if st.chat_pending:
                        st.chat_error = "连接已断开，消息未确认"
                        st.chat_last_result = {"request_id": st.chat_pending, "error": st.chat_error}
                        st.chat_pending = None
                    if st.profile_pending:
                        st.profile_error = "连接已断开，资料未确认"
                        st.profile_pending = None
                st.add_log("与服务端断开（本局细胞已死亡）")

    async def handle(self, mtype, payload):
        st = self.state
        if mtype == "welcome":
            selected = payload.get("protocol_version", 1)
            if type(selected) is not int or selected not in SUPPORTED_PROTOCOLS:
                raise ValueError("服务器选择了本客户端不支持的协议版本")
            manifest = payload.get("manifest")
            with st.lock:
                st.player_id = payload["player_id"]
                st.manifest = manifest if isinstance(manifest, dict) else None
                st.world = None
                st.known = None
                st.seen = None
                st.previous_cells = None
                st.chat_available = payload.get("features", {}).get("chat") is True
                st.chat_messages = []
                st.chat_session += 1
                st.chat_pending = None
                st.chat_error = None
                st.chat_last_result = None
                st.player_name = payload.get("player_name", st.player_name)
                st.player_color = payload.get("player_color", default_color(st.player_id))
                st.players = {
                    int(p["player_id"]): {"name": p["name"], "color": p["color"]}
                    for p in payload.get("players", [])
                }
                st.players.setdefault(st.player_id, {"name": st.player_name, "color": st.player_color})
            st.add_log(f"加入成功，玩家 id={payload['player_id']}")
        elif mtype == "world_snapshot":
            arrays = {k: v for k, v in payload["arrays"].items()}
            import numpy as np
            from cellgame.shared.protocol import b64_to_array
            decoded = {k: b64_to_array(v) for k, v in arrays.items()}
            with st.lock:
                st.visual_events = []
                st.organism_stats = payload.get("organisms", {})
                st.world = WorldArrays.from_dict(
                    decoded, decoded["owner"].shape[1], decoded["owner"].shape[0])
                st.tick = payload["tick"]
        elif mtype == "sense_batch":
            await self.on_sense(payload)
        elif mtype == "observation":
            await self.on_observation(payload)
        elif mtype == "world_delta":
            with st.lock:
                if st.world is not None:
                    apply_delta(st.world, payload["changes"])
                    for field, value in payload.get("environment", {}).items():
                        setattr(st.world, field, value.copy())
                    st.tick = payload["tick"]
                    st.organism_stats.update(payload.get("organism_updates", {}))
                    for key in payload.get("organism_removed", []):
                        st.organism_stats.pop(key, None)
                    events = payload.get("visual_events", [])
                    if isinstance(events, list) and events:
                        st.visual_seq += 1
                        st.visual_events.append({"seq": st.visual_seq, "events": events[:256]})
                        st.visual_events = st.visual_events[-8:]
        elif mtype in ("chat_history", "chat_message"):
            messages = payload.get("messages", []) if mtype == "chat_history" else [payload]
            if isinstance(messages, list):
                with st.lock:
                    by_id = {m["id"]: m for m in st.chat_messages}
                    for message in messages[-CHAT_HISTORY_LIMIT:]:
                        if (not isinstance(message, dict) or type(message.get("id")) is not int
                                or message["id"] < 1 or not isinstance(message.get("name"), str)
                                or not isinstance(message.get("text"), str)):
                            continue
                        by_id[message["id"]] = message
                        if (message.get("player_id") == st.player_id
                                and message.get("request_id") == st.chat_pending):
                            st.chat_last_result = {"request_id": st.chat_pending, "error": None}
                            st.chat_pending = None
                            st.chat_error = None
                    st.chat_messages = sorted(by_id.values(), key=lambda m: m["id"])[-CHAT_HISTORY_LIMIT:]
        elif mtype == "chat_error":
            with st.lock:
                if st.chat_pending is not None and payload.get("request_id") == st.chat_pending:
                    st.chat_error = str(payload.get("message", "消息发送失败"))
                    st.chat_last_result = {"request_id": st.chat_pending, "error": st.chat_error}
                    st.chat_pending = None
        elif mtype == "player_joined":
            with st.lock:
                pid = payload["player_id"]
                st.players[pid] = {"name": payload["species_name"],
                                   "color": payload.get("color", default_color(pid))}
            st.add_log(f"玩家 {payload['species_name']} 加入")
        elif mtype == "player_updated":
            with st.lock:
                pid = payload["player_id"]
                st.players[pid] = {"name": payload["name"], "color": payload["color"]}
                if pid == st.player_id:
                    st.player_name = payload["name"]
                    st.player_color = payload["color"]
                    if st.profile_pending == payload.get("request_id"):
                        st.profile_pending = None
                        st.profile_error = None
            st.add_log(f"玩家资料已更新：{payload['name']}")
        elif mtype == "player_left":
            with st.lock:
                st.players.pop(payload["player_id"], None)
            st.add_log(f"玩家 #{payload['player_id']} 离开，细胞死亡 "
                       f"({payload.get('reason', '')})")
        elif mtype == "error":
            if payload.get("code") == "profile_error":
                with st.lock:
                    if st.profile_pending == payload.get("request_id"):
                        st.profile_pending = None
                        st.profile_error = payload.get("message", "资料更新失败")
            st.add_log(f"服务端错误: {payload.get('message')}")

    async def send_chat(self, text, request_id):
        st = self.state
        with st.lock:
            ws = st.ws
            available = st.connected and st.chat_available
        if ws is None or not available:
            raise ConnectionError("当前服务器未连接或不支持聊天")
        await ws.send(encode_msg("chat_send", text=text, request_id=request_id))
        def expire():
            with st.lock:
                if st.chat_pending == request_id:
                    st.chat_error = "服务器未确认消息，请检查连接"
                    st.chat_last_result = {"request_id": st.chat_pending, "error": st.chat_error}
                    st.chat_pending = None
        asyncio.get_running_loop().call_later(5, expire)

    async def update_profile(self, name, color, request_id):
        st = self.state
        with st.lock:
            ws = st.ws
        if ws is None:
            raise ConnectionError("服务器尚未连接")
        await ws.send(encode_msg("update_profile", name=name, color=color, request_id=request_id))
        def expire():
            with st.lock:
                if st.profile_pending == request_id:
                    st.profile_pending = None
                    st.profile_error = "服务器未确认资料更新，请检查服务器版本或连接"
        asyncio.get_running_loop().call_later(5, expire)

    async def on_observation(self, observation):
        """Observation v2: refresh the perceived map, run rules, answer in v2."""
        st = self.state
        with st.lock:
            manifest = st.manifest
            pid = st.player_id
        if manifest is None or is_legacy(manifest):
            st.add_log("服务端发送了观察 v2，但未声明非 legacy 世界清单，已忽略")
            return
        world = manifest["world"]
        try:
            expanded = expand_observation(observation, manifest)
            view = observation_to_world(observation, pid, world["width"], world["height"])
        except (KeyError, ValueError, IndexError) as exc:
            st.add_log(f"无法解析服务端观察: {exc}")
            return
        with st.lock:
            if st.known is None or (st.known.w, st.known.h) != (view.w, view.h):
                st.known = WorldArrays(view.w, view.h)
                st.seen = np.zeros((view.h, view.w), dtype=np.uint8)
            remember(st.known, st.seen, view, observation, pid)
            events = visual_events(st.previous_cells, observation, pid)
            st.previous_cells = observation["cells"]
            if events:
                st.visual_seq += 1
                st.visual_events.append({"seq": st.visual_seq, "events": events[:256]})
                st.visual_events = st.visual_events[-8:]
            st.world = view
            st.tick = observation["tick"]
        await self.on_sense(to_legacy_batch(expanded), expanded)

    async def on_sense(self, batch, observation=None):
        st = self.state
        n = len(batch["cells"])
        with st.lock:
            st.last_sense_tick = batch["tick"]
            st.last_sense_cells = n
            st.constraints = dict(batch.get("constraints") or {})
        if not self.executor.ns:
            # no rules loaded yet: answer with empty intentions so the
            # server does not count this as a timeout (heartbeat)
            intentions = np.empty((0,), dtype=INTENTION_DTYPE)
        else:
            intentions = await self.executor.run(batch)
        with st.lock:
            st.last_exec_ms = self.executor.last_duration_ms
            st.last_exec_error = self.executor.last_error
        if observation is None:
            message = encode_msg("intentions", tick=batch["tick"], data=intentions)
        else:
            message = encode_msg("intentions", tick=batch["tick"], format=2,
                                 data=intentions_to_v2(intentions, observation))
        if st.ws is not None:
            try:
                await st.ws.send(message)
            except Exception:
                pass
        # flush a pending rule submission right after the tick's work
        pending = st.take_pending_submit()
        if pending is not None and st.ws is not None:
            source, species_name = pending
            try:
                await st.ws.send(encode_msg(
                    "submit_rules", species_name=species_name))
                st.add_log(f"已提交规则 ({species_name})")
            except Exception:
                pass

    async def submit_rules_now(self, source, species_name):
        st = self.state
        if st.ws is None:
            st.queue_submit(source, species_name)
            return False
        await st.ws.send(encode_msg("submit_rules", species_name=species_name))
        return True
