"""Sim process: the tick pipeline (spec section 7).

Runs in its own process so NumPy tick work never blocks the asyncio
network loop. Talks to the main process over multiprocessing queues:
  cmd_queue  (main -> sim): ("join", pid, name), ("leave", pid),
                            ("intentions", pid, structured array)
  event_queue (sim -> main): ("snapshot", arrays_dict),
                            ("sense", pid, batch_dict),
                            ("delta", delta_dict),
                            ("player_joined", pid, name),
                            ("player_died", pid, reason),
                            ("tick", tick, summary_dict)

Per tick:
  1. arbitrate last window's intentions, apply, ecology step
  2. handle joins / leaves (leave -> kill_player immediately)
  3. world rules every epoch_interval ticks
  4. pack sense batches for all online players
  5. collect intentions until the deadline (2500/3000 ms)
  6. broadcast the world delta
A player that sends no intentions for 3 ticks in a row is treated as
disconnected (spec 3.2) and its cells die.
"""
import multiprocessing
import queue
import secrets
import time

import numpy as np

from cellgame.shared.manifest import build_manifest, is_legacy
from cellgame.shared.contract import MAX_SILENT_TICKS
from cellgame.shared.models import INTENTION_DTYPE
from cellgame.shared.protocol import encode_msg
from .perception import gather_observation
from .world import WorldState

from .kernel import resolve_tick

from .world_rules import WorldRuleEngine, apply_world_params, run_tick_event

TIMEOUT_TICKS = MAX_SILENT_TICKS  # consecutive silent ticks -> disconnect death


def _decode_intentions(world, pid, data, legacy):
    """Legacy worlds take INTENTION_DTYPE rows; others take v2 rows."""
    if legacy:
        return np.asarray(data, dtype=INTENTION_DTYPE)
    return world.intentions_from_v2(pid, data)


def sim_loop(cmd_queue, event_queue, config):
    manifest = config.get("manifest")
    if manifest is None:
        manifest = build_manifest({"world": {"width": config.get("world_w", 256),
                                             "height": config.get("world_h", 256)}})
    legacy = is_legacy(manifest)
    world_run = secrets.token_hex(8)  # cell IDs are unique only within one run
    world = WorldState(
        manifest["world"]["width"], manifest["world"]["height"],
        seed=config.get("seed", 0),
    )
    world.configure(manifest)
    from cellgame.shared.world_parameters import validate_parameters
    world.constraints.update(validate_parameters(config.get("world_parameters", {})))
    rules = WorldRuleEngine(config["world_rules_path"])
    tick_period = config.get("tick_ms", 3000) / 1000.0
    deadline_ratio = config.get("deadline_ms", 2500) / config.get("tick_ms", 3000)
    epoch_interval = config.get("epoch_interval", 10)

    players = {}            # pid -> species name
    pending = {}            # pid -> (intentions array, player_ids array)
    silent_ticks = {}        # pid -> consecutive ticks with no intentions
    recording = None
    if config.get("record_path"):
        # Exclusive creation protects existing recordings from replacement.
        recording = open(config["record_path"], "x", encoding="utf-8", buffering=1)
        recording.write(encode_msg("replay_header", version=1, world_w=world.w,
                                   world_h=world.h, seed=config.get("seed", 0)) + "\n")

    def emit(event):
        if recording is not None and event[0] in {
            "snapshot", "delta", "player_joined", "player_updated", "player_died", "tick"
        }:
            recording.write(encode_msg(event[0], data=list(event[1:])) + "\n")
        event_queue.put(event)

    emit(("snapshot", world.snapshot_arrays()))

    # When the server process is killed outright (no shutdown command), this
    # process would otherwise keep simulating forever as an orphan.
    parent = multiprocessing.parent_process()
    while True:
        if parent is not None and not parent.is_alive():
            if recording is not None:
                recording.close()
            # Nobody reads the event queue any more; without this, exit would
            # wait forever for its feeder thread to flush into a full pipe.
            if hasattr(event_queue, "cancel_join_thread"):
                event_queue.cancel_join_thread()
            return
        t0 = time.monotonic()
        tick = world.tick

        # 1. arbitrate and apply last window's intentions, then ecology
        counts = resolve_tick(world, pending, rules)
        pending = {}

        # 2. joins / leaves (drain whatever arrived during the tick)
        while True:
            try:
                cmd = cmd_queue.get_nowait()
            except queue.Empty:
                break
            kind = cmd[0]
            if kind == "shutdown":
                if recording is not None:
                    recording.close()
                return
            if kind == "join":
                _, pid, name, *extra = cmd
                players[pid] = name
                silent_ticks[pid] = 0
                world.spawn_player(pid, pid)
                emit(("player_joined", pid, name, *extra))
            elif kind == "profile":
                _, pid, name, color = cmd
                if pid in players:
                    players[pid] = name
                    emit(("player_updated", pid, name, color))
            elif kind == "leave":
                _, pid = cmd
                if pid in players:
                    del players[pid]
                    silent_ticks.pop(pid, None)
                    world.kill_player(pid)
                    emit(("player_died", pid, "disconnect"))
            elif kind == "intentions":
                # Anything arriving between windows is late and cannot be
                # applied to a different snapshot.
                continue

        # 3. world rules observe the current tick before epoch updates.
        event_counts = dict(counts, ecology_deaths=world._last_ecology)
        event_error = run_tick_event(world, rules, event_counts)
        if event_error:
            emit(("log", f"world event rules: {event_error}"))
        if tick % epoch_interval == 0:
            params, err = rules.on_epoch(world.summary(), tick)
            if err:
                emit(("log", f"world rules: {err}"))
            elif params:
                apply_world_params(world, params)

        # 4. per-player perception: legacy sense batches or observation v2
        for pid in list(players):
            if legacy:
                emit(("sense", pid, world.gather_sense(pid)))
            else:
                emit(("observation", pid, gather_observation(world, pid, manifest, world_run)))
        world.end_observation_window()

        # 5. collect intentions until the deadline
        deadline = t0 + tick_period * deadline_ratio
        while time.monotonic() < deadline:
            try:
                cmd = cmd_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            kind = cmd[0]
            if kind == "shutdown":
                if recording is not None:
                    recording.close()
                return
            if kind == "intentions":
                _, pid, intent_tick, data = cmd
                if pid in players and intent_tick == tick:
                    try:
                        arr = _decode_intentions(world, pid, data, legacy)
                    except ValueError as exc:
                        emit(("log", f"player {pid} sent invalid intentions: {exc}"))
                        continue
                    pending[pid] = (arr, np.full(len(arr), pid, dtype=np.int32))
                    silent_ticks[pid] = 0
            elif kind == "join":
                _, pid, name, *extra = cmd
                players[pid] = name
                silent_ticks[pid] = 0
                world.spawn_player(pid, pid)
                emit(("player_joined", pid, name, *extra))
            elif kind == "profile":
                _, pid, name, color = cmd
                if pid in players:
                    players[pid] = name
                    emit(("player_updated", pid, name, color))
            elif kind == "leave":
                _, pid = cmd
                if pid in players:
                    del players[pid]
                    silent_ticks.pop(pid, None)
                    world.kill_player(pid)
                    emit(("player_died", pid, "disconnect"))

        # silent players: 3 missed windows -> disconnect death
        for pid in list(players):
            if pid not in pending and pid in silent_ticks:
                silent_ticks[pid] += 1
                if silent_ticks[pid] >= TIMEOUT_TICKS:
                    del players[pid]
                    del silent_ticks[pid]
                    world.kill_player(pid)
                    emit(("player_died", pid, "timeout"))

        # 6. broadcast delta
        delta = world.delta_since_last_sent()
        emit(("delta", delta))
        counts["ecology_deaths"] = getattr(world, "_last_ecology", 0)
        emit(("tick", tick, world.summary(), counts))

        elapsed = time.monotonic() - t0
        if elapsed < tick_period:
            time.sleep(tick_period - elapsed)
        world.tick += 1
