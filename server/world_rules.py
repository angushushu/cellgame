"""World Python rule engine (spec section 4.3).

Loads a rule file that defines on_epoch(world_summary, tick) -> dict
and optionally on_event(event, world_view) -> list. Rules run in the
sim process with a 100ms timeout (thread + join; a timed-out result is
discarded -- a thread cannot be force-killed, same caveat as the
client rule executor). Rules receive a summary dict and optionally a WorldView. Python code is not
sandboxed and has the process owner's normal privileges.
"""
import threading

import numpy as np
from cellgame.shared.world_parameters import DEFAULTS, validate_parameters


class WorldView:
    """Read-only view handed to world rules."""

    def __init__(self, arrays):
        # Snapshot isolates the simulation from a slow or misbehaving callback.
        self._a = arrays.copy()
        self.width, self.height = arrays.w, arrays.h

    def get_region(self, x, y, w, h):
        from cellgame.shared.models import WORLD_FIELDS, INTERNAL_FIELDS
        if any(type(n) is not int for n in (x, y, w, h)) or w < 0 or h < 0:
            raise ValueError("区域坐标须为整数，宽高不可为负")
        x0, y0 = max(0, min(self.width, x)), max(0, min(self.height, y))
        x1 = max(x0, min(self.width, x + w))
        y1 = max(y0, min(self.height, y + h))
        return {field: getattr(self._a, field)[y0:y1, x0:x1].copy() for field in WORLD_FIELDS + INTERNAL_FIELDS}


class WorldRuleEngine:
    def __init__(self, source_path, timeout=0.1):
        self.timeout = timeout
        self.source_path = source_path
        self.ns = {}
        with open(source_path, encoding="utf-8") as f:
            code = compile(f.read(), source_path, "exec")
        exec(code, self.ns)
        version = self.ns.get("WORLD_API_VERSION", 1)
        if type(version) is not int or version != 1:
            raise ValueError("不支持的 WORLD_API_VERSION；当前为 1")
        if not callable(self.ns.get("on_epoch")):
            raise ValueError(f"{source_path} must define on_epoch(summary, tick)")

    def _run_with_timeout(self, fn, *args):
        box = {}

        def target():
            try:
                box["result"] = fn(*args)
            except Exception as e:  # noqa: BLE001 - surfaced to the log
                box["error"] = e

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout=self.timeout)
        if t.is_alive():
            return None, "timeout"
        if "error" in box:
            return None, f"error: {box['error']}"
        return box.get("result"), None

    def on_epoch(self, world_summary, tick):
        result, err = self._run_with_timeout(self.ns["on_epoch"], world_summary, tick)
        return result, err

    def filter_actions(self, intentions, players, world_view, tick):
        fn = self.ns.get("filter_actions")
        if not callable(fn):
            return np.ones(len(intentions), dtype=bool), None
        result, err = self._run_with_timeout(fn, intentions.copy(), players.copy(), world_view, tick)
        if err:
            return None, err
        arr = np.asarray(result)
        if arr.dtype != np.bool_ or arr.shape != (len(intentions),):
            return None, "filter_actions 必须返回与动作等长的布尔序列"
        return arr, None

    def after_actions(self, events, world_view, tick):
        fn = self.ns.get("after_actions")
        if not callable(fn):
            return [], None
        result, err = self._run_with_timeout(fn, [dict(event) for event in events], world_view, tick)
        if err:
            return None, err
        if not isinstance(result, list):
            return None, "after_actions 必须返回命令列表"
        return result, None

    def before_ecology(self, world_view, tick):
        fn = self.ns.get("before_ecology")
        if not callable(fn):
            return [], None
        result, err = self._run_with_timeout(fn, world_view, tick)
        if err:
            return None, err
        if not isinstance(result, list):
            return None, "before_ecology 必须返回命令列表"
        return result, None

    def on_event(self, event, world_view):
        fn = self.ns.get("on_event")
        if not callable(fn):
            return [], None
        result, err = self._run_with_timeout(fn, event, world_view)
        return result if isinstance(result, list) else [], err


def apply_world_params(world, params):
    """Interpret an on_epoch return dict. Known keys:
    food_regrow (int): scatter that much food onto random cells.
    temp_delta (float): shift the whole temperature field.
    reproduce_enabled (bool): world constraint for the next ticks."""
    if not isinstance(params, dict):
        return
    # Only validated server rule results can alter world economics.
    for key in DEFAULTS:
        if key in params:
            try:
                world.constraints.update(validate_parameters({key: params[key]}, partial=True))
            except ValueError:
                pass
    rng = world.rng
    n = int(params.get("food_regrow", 0))
    if n > 0:
        xs = rng.integers(0, world.w, size=n)
        ys = rng.integers(0, world.h, size=n)
        safe = world.arrays.env_material[ys, xs] < 2
        amounts = rng.uniform(3, 10, size=n).astype(np.float32)
        np.add.at(world.arrays.env_food, (ys[safe], xs[safe]), amounts[safe])
    # Optional resource-rich habitats near currently occupied cells. The
    # setting is separate from global regrowth so world owners can disable it.
    local_n = max(0, min(int(params.get("food_regrow_near_cells", 0)), world.w * world.h))
    ys, xs = np.where(world.arrays.owner != 0)
    if local_n and len(xs):
        chosen = rng.integers(0, len(xs), size=local_n)
        xx = np.clip(xs[chosen] + rng.integers(-1, 2, size=local_n), 0, world.w - 1)
        yy = np.clip(ys[chosen] + rng.integers(-1, 2, size=local_n), 0, world.h - 1)
        safe = world.arrays.env_material[yy, xx] < 2
        amounts = rng.uniform(3, 10, size=local_n).astype(np.float32)
        np.add.at(world.arrays.env_food, (yy[safe], xx[safe]), amounts[safe])
    dt = float(params.get("temp_delta", 0.0))
    if dt:
        world.arrays.env_temp = np.clip(
            world.arrays.env_temp + dt, 0.0, 40.0).astype(np.float32)
    if "reproduce_enabled" in params:
        world.constraints["reproduce_enabled"] = bool(params["reproduce_enabled"])
    if "metabolism_interval" in params:
        world.constraints["metabolism_interval"] = max(0, int(params["metabolism_interval"]))


def apply_world_events(world, commands):
    """Apply bounded commands returned by on_event; ignore malformed commands."""
    if not isinstance(commands, list):
        return
    for command in commands[:1000]:
        if not isinstance(command, dict):
            continue
        try:
            if command.get("type") == "add_food":
                x, y = int(command["x"]), int(command["y"])
                amount = float(command["amount"])
                if 0 <= x < world.w and 0 <= y < world.h and np.isfinite(amount) and 0 <= amount <= 100:
                    world.arrays.env_food[y, x] += amount
            elif command.get("type") == "set_reproduction":
                if isinstance(command.get("enabled"), bool):
                    world.constraints["reproduce_enabled"] = command["enabled"]
        except (KeyError, ValueError, TypeError, OverflowError):
            continue


def apply_ecology_commands(world, commands):
    """Validate the whole batch, then execute bounded world-rule commands."""
    if len(commands) > 2 * world.w * world.h:
        raise ValueError("世界规则命令过多")
    for command in commands:
        if not isinstance(command, dict) or command.get("type") not in ("kill", "adjust_energy"):
            raise ValueError("不支持的世界规则命令")
        x, y = command.get("x"), command.get("y")
        if type(x) is not int or type(y) is not int or not (0 <= x < world.w and 0 <= y < world.h):
            raise ValueError("世界规则命令坐标无效")
        if command["type"] == "adjust_energy" and (type(command.get("amount")) is not int or abs(command["amount"]) > 100):
            raise ValueError("能量调整必须是 -100 到 100 的整数")
        if "cell_id" in command and type(command["cell_id"]) is not int:
            raise ValueError("cell_id 无效")
    for command in commands:
        x, y = command["x"], command["y"]
        if not world.arrays.owner[y, x]:
            continue
        if "cell_id" in command and int(world.arrays.cell_id[y, x]) != command["cell_id"]:
            continue
        if command["type"] == "kill":
            world.arrays.energy[y, x] = 0
        else:
            current = int(world.arrays.energy[y, x])
            world.arrays.energy[y, x] = max(-32768, min(32767, current + command["amount"]))


def run_tick_event(world, rules, counts):
    """Emit one post-ecology event before applying epoch rules."""
    event = {"type": "tick", "tick": world.tick,
             "counts": dict(counts), "summary": world.summary()}
    commands, error = rules.on_event(event, WorldView(world.arrays))
    if not error:
        apply_world_events(world, commands)
    return error
