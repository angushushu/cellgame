"""World manifest: the contract a world declares to its clients.

Implemented sections: world size, perception (legacy / radius / blanket),
observation, visibility, ecology.metabolism and per-action rules. Every other
section of docs/WORLD_MANIFEST_zh.md is rejected with an explicit message, so
a world never silently promises behavior the server does not enforce.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .models import Action

MANIFEST_VERSION = 1
PERCEPTION_MODELS = ("legacy", "radius", "blanket")
METRICS = ("chebyshev", "euclidean")
MAX_RADIUS = 8
# 512 keeps a legacy full snapshot and a fully perceived tile list well under
# the clients' 32 MB message limit.
MIN_WORLD_SIZE, MAX_WORLD_SIZE = 16, 512
ROLE_NAMES = ("boundary", "interior")   # role codes 1 and 2
VISIBILITY_LEVELS = ("all", "boundary_only", "none")
MAX_METABOLISM = 10

_ACTION_TARGETS = {
    Action.MOVE: "neighbor", Action.ATTACK: "neighbor", Action.REPRODUCE: "neighbor",
    Action.EAT: "self", Action.CHANGE: "self", Action.DIE: "self", Action.SET_STATE: "self",
    Action.BOND: "neighbor", Action.UNBOND: "neighbor", Action.TRANSFER: "bonded_neighbor",
    Action.MOVE_GROUP: "component", Action.SENSE: "self",
}
DEFAULT_VISIBILITY = {"others_interior": "visible", "state": "all", "energy": "all",
                      "type": "all", "spectator": "full"}
DEFAULT_SENSE = {"cost_per_radius": 1, "max_radius": 4}

# Sections described in the spec but not yet enforced by the server.
_FUTURE_SECTIONS = ("session", "cell_types", "layers", "bonds", "offline", "mutable")
_KNOWN_SECTIONS = ("manifest_version", "id", "name", "world", "perception", "observation", "combat",
                   "visibility", "ecology", "actions")


class ManifestError(ValueError):
    """A manifest override is malformed or asks for an unsupported feature."""


def _action_table(model: str = "legacy") -> list[dict[str, Any]]:
    table = []
    for action in Action:
        entry = {"name": action.name.lower(), "id": int(action), "target": _ACTION_TARGETS[action],
                 "enabled": action != Action.SENSE, "actor_roles": list(ROLE_NAMES)}
        if action == Action.SENSE:
            entry.update(DEFAULT_SENSE)
        if model == "blanket" and action in (Action.SENSE, Action.EAT):
            # Interior cells cannot perceive the outside or the resource layer
            # under them: a wider radius would do nothing, and a free EAT
            # attempt would reveal the hidden food. Worlds may opt eating in.
            entry["actor_roles"] = ["boundary"]
        table.append(entry)
    return table


def default_manifest() -> dict[str, Any]:
    """The legacy world: full 0.1.x behavior, observation format v1."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "id": "legacy",
        "name": "经典世界",
        "world": {"width": 256, "height": 256, "topology": "bounded"},
        "perception": {"model": "legacy"},
        "observation": {"version": 1, "coordinates": "absolute"},
        "visibility": dict(DEFAULT_VISIBILITY),
        "ecology": {"metabolism": {"boundary": 1, "interior": 1}},
        "actions": _action_table(),
        "combat": {"bonded_support_percent": 0},
    }


def _require_int(value: Any, key: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ManifestError(f"{key} 必须是 {low}–{high} 的整数")
    return value


def _require_choice(value: Any, key: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise ManifestError(f"{key} 必须是 {' / '.join(choices)}")
    return value


def _require_keys(section: Any, name: str, allowed: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise ManifestError(f"{name} 必须是对象")
    unknown = sorted(set(section) - set(allowed))
    if unknown:
        raise ManifestError(f"{name} 中不支持的字段: {', '.join(unknown)}")
    return section


def _world(override: Any, base: dict[str, Any]) -> dict[str, Any]:
    section = _require_keys(override, "world", ("width", "height", "topology"))
    result = {**base, **section}
    for key in ("width", "height"):
        _require_int(result[key], f"world.{key}", MIN_WORLD_SIZE, MAX_WORLD_SIZE)
    if result["topology"] != "bounded":
        raise ManifestError(f"world.topology={result['topology']!r} 尚未支持（当前仅 bounded）")
    return result


def _radius_and_metric(section: dict[str, Any], key: str) -> tuple[int, str]:
    radius = _require_int(section.get(key, 1), f"perception.{key}", 1, MAX_RADIUS)
    metric = _require_choice(section.get("metric", "chebyshev"), "perception.metric", METRICS)
    # The per-cell API needs the full 3x3 window; a euclidean disc of radius 1
    # would omit the diagonals and make them look empty to older rules.
    if metric == "euclidean" and radius < 2:
        raise ManifestError(f"euclidean 感知的 {key} 至少为 2，以覆盖完整的 3×3 邻域")
    return radius, metric


def _perception(override: Any) -> dict[str, Any]:
    if not isinstance(override, dict):
        raise ManifestError("perception 必须是对象")
    model = _require_choice(override.get("model", "legacy"), "perception.model", PERCEPTION_MODELS)
    if model == "legacy":
        _require_keys(override, "legacy perception", ("model",))
        return {"model": "legacy"}
    if model == "radius":
        section = _require_keys(override, "radius perception", ("model", "radius", "metric"))
        radius, metric = _radius_and_metric(section, "radius")
        return {"model": "radius", "radius": radius, "metric": metric}
    section = _require_keys(override, "blanket perception", ("model", "external_radius", "metric"))
    radius, metric = _radius_and_metric(section, "external_radius")
    return {"model": "blanket", "external_radius": radius, "metric": metric}


def _observation(override: Any) -> dict[str, Any]:
    section = _require_keys(override, "observation", ("coordinates",))
    coordinates = section.get("coordinates", "absolute")
    if coordinates != "absolute":
        raise ManifestError(f"observation.coordinates={coordinates!r} 将在后续阶段支持（当前仅 absolute）")
    return {"coordinates": coordinates}


def _visibility(override: Any, legacy: bool) -> dict[str, Any]:
    section = _require_keys(override, "visibility", tuple(DEFAULT_VISIBILITY))
    result = {**DEFAULT_VISIBILITY, **section}
    _require_choice(result["others_interior"], "visibility.others_interior", ("visible", "hidden"))
    for key in ("state", "energy", "type"):
        _require_choice(result[key], f"visibility.{key}", VISIBILITY_LEVELS)
    _require_choice(result["spectator"], "visibility.spectator", ("full", "none"))
    player_facing = {k: v for k, v in result.items() if k != "spectator"}
    if legacy and player_facing != {k: v for k, v in DEFAULT_VISIBILITY.items() if k != "spectator"}:
        raise ManifestError("legacy 感知会向玩家发送全图，不能限制玩家可见性；请使用 radius 或 blanket")
    return result


def _ecology(override: Any) -> dict[str, Any]:
    section = _require_keys(override, "ecology", ("metabolism",))
    metabolism = _require_keys(section.get("metabolism", {}), "ecology.metabolism", ROLE_NAMES)
    result = {"boundary": 1, "interior": 1, **metabolism}
    for role in ROLE_NAMES:
        _require_int(result[role], f"ecology.metabolism.{role}", 0, MAX_METABOLISM)
    return {"metabolism": result}


def _combat(override: Any) -> dict[str, Any]:
    section = _require_keys(override, "combat", ("bonded_support_percent",))
    support = _require_int(section.get("bonded_support_percent", 0), "combat.bonded_support_percent", 0, 100)
    return {"bonded_support_percent": support}


def _actions(override: Any, model: str) -> list[dict[str, Any]]:
    if not isinstance(override, dict):
        raise ManifestError("actions 必须是以行动名为键的对象，例如 {\"sense\": {\"enabled\": true}}")
    table = _action_table(model)
    by_name = {entry["name"]: entry for entry in table}
    for name, fields in override.items():
        if name not in by_name:
            raise ManifestError(f"未知的行动: {name}")
        allowed = ("enabled", "actor_roles") + (tuple(DEFAULT_SENSE) if name == "sense" else ())
        _require_keys(fields, f"actions.{name}", allowed)
        entry = by_name[name]
        if "enabled" in fields:
            if type(fields["enabled"]) is not bool:
                raise ManifestError(f"actions.{name}.enabled 必须是 true 或 false")
            entry["enabled"] = fields["enabled"]
        if "actor_roles" in fields:
            roles = fields["actor_roles"]
            if not isinstance(roles, list) or not roles or any(r not in ROLE_NAMES for r in roles):
                raise ManifestError(f"actions.{name}.actor_roles 必须是 boundary / interior 的非空列表")
            entry["actor_roles"] = [r for r in ROLE_NAMES if r in roles]
        if "cost_per_radius" in fields:
            entry["cost_per_radius"] = _require_int(fields["cost_per_radius"], "actions.sense.cost_per_radius", 0, 10)
        if "max_radius" in fields:
            entry["max_radius"] = _require_int(fields["max_radius"], "actions.sense.max_radius", 1, MAX_RADIUS)
    if model == "blanket" and "interior" in by_name["sense"]["actor_roles"]:
        raise ManifestError("blanket 世界中内部细胞看不到外部，sense 的 actor_roles 不能包含 interior")
    if model == "legacy" and by_name["sense"]["enabled"]:
        raise ManifestError("sense 行动需要 radius 或 blanket 感知；legacy 世界不支持")
    return table


def build_manifest(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge overrides onto the legacy default and validate the result.

    Returns a new dict; the input is never modified. Raises ManifestError.
    """
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ManifestError("世界清单必须是一个对象")
    overrides = copy.deepcopy(overrides)
    manifest = default_manifest()
    for key in overrides:
        if key in _FUTURE_SECTIONS:
            raise ManifestError(f"清单字段 {key} 尚未实现，见 docs/WORLD_MANIFEST_zh.md 的实施顺序")
        if key not in _KNOWN_SECTIONS:
            raise ManifestError(f"未知的清单字段: {key}")
    version = overrides.get("manifest_version", MANIFEST_VERSION)
    if type(version) is not int or version != MANIFEST_VERSION:
        raise ManifestError(f"manifest_version 必须是 {MANIFEST_VERSION}")
    for key in ("id", "name"):
        if key in overrides:
            value = overrides[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 64:
                raise ManifestError(f"{key} 必须是 1–64 个字符的字符串")
            manifest[key] = value
    if "world" in overrides:
        manifest["world"] = _world(overrides["world"], manifest["world"])
    if "perception" in overrides:
        manifest["perception"] = _perception(overrides["perception"])
        if "id" not in overrides and manifest["perception"]["model"] != "legacy":
            manifest["id"], manifest["name"] = "custom", "自定义世界"
    legacy = is_legacy(manifest)
    observation = _observation(overrides.get("observation", {}))
    manifest["observation"] = {"version": 1 if legacy else 2, "coordinates": observation["coordinates"]}
    manifest["visibility"] = _visibility(overrides.get("visibility", {}), legacy)
    manifest["ecology"] = _ecology(overrides.get("ecology", {}))
    manifest["actions"] = _actions(overrides.get("actions", {}), manifest["perception"]["model"])
    manifest["combat"] = _combat(overrides.get("combat", {}))
    return manifest


def is_legacy(manifest: dict[str, Any]) -> bool:
    return manifest["perception"]["model"] == "legacy"


def manifest_hash(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def base_radius(manifest: dict[str, Any]) -> int:
    perception = manifest["perception"]
    return {"legacy": 1, "radius": perception.get("radius"),
            "blanket": perception.get("external_radius")}[perception["model"]]


def window_offsets(radius: int, metric: str = "chebyshev") -> list[tuple[int, int]]:
    """(dx, dy) offsets within a radius in row-major order, including (0, 0)."""
    return [(dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
            if metric != "euclidean" or dx * dx + dy * dy <= radius * radius]


def perception_offsets(manifest: dict[str, Any]) -> list[tuple[int, int]]:
    """The default perceived window for this manifest."""
    return window_offsets(base_radius(manifest), manifest["perception"].get("metric", "chebyshev"))


@dataclass(frozen=True)
class WorldRules:
    """Server-side rules compiled from a manifest for fast checks."""
    enabled: frozenset[int]
    actor_role_mask: tuple[int, ...]   # per action id; bit (1 << role) allows that role
    sense_cost_per_radius: int
    sense_max_radius: int
    metabolism_boundary: int
    metabolism_interior: int
    needs_roles: bool
    bonded_support_percent: int = 0


def role_mask(names: list[str]) -> int:
    return sum(1 << (ROLE_NAMES.index(name) + 1) for name in names)


ALL_ROLES = role_mask(list(ROLE_NAMES))


def compile_rules(manifest: dict[str, Any]) -> WorldRules:
    actions = sorted(manifest["actions"], key=lambda entry: entry["id"])
    sense = next(entry for entry in actions if entry["name"] == "sense")
    masks = tuple(role_mask(entry["actor_roles"]) for entry in actions)
    metabolism = manifest["ecology"]["metabolism"]
    visibility = manifest["visibility"]
    needs_roles = (
        manifest["perception"]["model"] == "blanket"
        or any(mask != ALL_ROLES for mask in masks)
        or metabolism["boundary"] != metabolism["interior"]
        or visibility["others_interior"] != "visible"
        or any(visibility[key] == "boundary_only" for key in ("state", "energy", "type"))
    )
    return WorldRules(
        enabled=frozenset(entry["id"] for entry in actions if entry["enabled"]),
        actor_role_mask=masks,
        sense_cost_per_radius=sense["cost_per_radius"],
        sense_max_radius=sense["max_radius"],
        metabolism_boundary=metabolism["boundary"],
        metabolism_interior=metabolism["interior"],
        needs_roles=needs_roles,
        bonded_support_percent=manifest["combat"]["bonded_support_percent"],
    )


DEFAULT_RULES = compile_rules(default_manifest())
