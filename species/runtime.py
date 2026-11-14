"""Load either a beginner single-cell rule or the advanced batch API.

Every loaded rule is called as
``decide(cells, neighborhood, env, constraints, tick, observation=None)``.
``observation`` is the v2 observation in non-legacy worlds and ``None``
otherwise. A batch ``decide`` receives it only if it declares an
``observation`` parameter (or ``**kwargs``), so older rules are unaffected.
"""
import inspect
import numpy as np

from cellgame.shared.models import INTENTION_DTYPE, MAX_ACTION
from cellgame.shared.protocol import integer_rows

from cellgame.species.simple import run_cells


def _accepts_observation(fn):
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "observation" or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def _select_rule(namespace):
    batch = namespace.get("decide")
    if callable(batch):
        if _accepts_observation(batch):
            return lambda c, n, e, k, t, o: batch(c, n, e, k, t, observation=o)
        return lambda c, n, e, k, t, o: batch(c, n, e, k, t)
    single = namespace.get("decide_cell")
    if callable(single):
        return lambda c, n, e, k, t, o: run_cells(single, c, n, e, k, t, o)
    for name, scale in (("decide_entity", "entity"), ("decide_unity", "unity")):
        unit_rule = namespace.get(name)
        if callable(unit_rule):
            from cellgame.species.units import run_units
            return lambda c, n, e, k, t, o, rule=unit_rule, scale=scale: run_units(rule, scale, c, n, e, k, t, o)
    raise ValueError("规则必须定义 decide_cell、decide_entity、decide_unity 或 decide 函数")


def load_rule(source, filename="<player_rules>"):
    namespace = {}
    exec(compile(source, filename, "exec"), namespace)
    version = namespace.get("PLAYER_API_VERSION", 1)
    if type(version) is not int or version != 1:
        raise ValueError("不支持的 PLAYER_API_VERSION；当前为 1")
    rule = _select_rule(namespace)

    def decide(cells, neighborhood, env, constraints, tick, observation=None):
        return rule(cells, neighborhood, env, constraints, tick, observation)

    decide.rule_namespace = namespace
    return decide

def world_size(batch):
    constraints = batch.get("constraints") or {}
    return constraints.get("world_w", 256), constraints.get("world_h", 256)


def to_intentions(result, cells=None, world_w=256, world_h=256):
    """Convert a decide() return value -- (n, 7) int array
    [src_x, src_y, tgt_x, tgt_y, action, strength, param] -- into an
    INTENTION_DTYPE structured array, dropping invalid rows. Rows whose
    src is not one of the player's own cells are dropped (a full (n, 7)
    return leaves zero rows for idle cells; those are not real moves)."""
    if result is None:
        return np.empty((0,), dtype=INTENTION_DTYPE)
    arr = integer_rows(result, 7, world_w * world_h, allow_single=True)
    ok = (arr[:, 4] >= 0) & (arr[:, 4] <= MAX_ACTION) \
        & (arr[:, 0] >= 0) & (arr[:, 0] < world_w) & (arr[:, 1] >= 0) & (arr[:, 1] < world_h) \
        & (arr[:, 2] >= 0) & (arr[:, 2] < world_w) & (arr[:, 3] >= 0) & (arr[:, 3] < world_h)
    ok &= (arr[:, 6] >= 0) & (arr[:, 6] <= 2147483647)
    if cells is not None:
        owned = set(zip(cells[:, 0].astype(int), cells[:, 1].astype(int)))
        ok &= np.array([(int(x), int(y)) in owned
                        for x, y in zip(arr[:, 0], arr[:, 1])], dtype=bool)
    arr = arr[ok]
    out = np.empty(len(arr), dtype=INTENTION_DTYPE)
    if len(arr):
        out["src_x"] = arr[:, 0]
        out["src_y"] = arr[:, 1]
        out["tgt_x"] = arr[:, 2]
        out["tgt_y"] = arr[:, 3]
        out["action"] = arr[:, 4]
        out["strength"] = 0  # a proposal has no client-authoritative strength
        out["param"] = arr[:, 6]
    return out
