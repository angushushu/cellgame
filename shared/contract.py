"""GUI-independent public interface registry and schema.

Contract, transport, observations, controllers and rule hooks have independent
versions. The RC describes the supported surface; it does not claim all engine
internals or experimental Unity membership are stable.
"""
import copy

CONTRACT_VERSION = "1.0.0-rc.1"
PROTOCOL_VERSION = 2
SUPPORTED_PROTOCOLS = (1, 2)
PLAYER_API_VERSION = 1
WORLD_API_VERSION = 1
CONTROLLER_VERSION = 1
MAX_SILENT_TICKS = 3
MAX_MESSAGE_BYTES = 32 * 1024 * 1024
MAX_ARRAY_BYTES = 24 * 1024 * 1024


def negotiate_protocol(version=None, versions=None, *, legacy=False):
    """Choose an explicitly shared version. Never infer future compatibility."""
    if versions is not None:
        if (not isinstance(versions, list) or not versions or
                any(type(v) is not int or v < 1 for v in versions)):
            raise ValueError("protocol_versions must be a nonempty integer list")
        offered = set(versions)
    else:
        offered = {1 if version is None else version} if type(version) is int or version is None else set()
    candidates = offered & ({1, 2} if legacy else {2})
    if not candidates:
        raise ValueError("no shared protocol version")
    return max(candidates)


def describe_contract():
    from .models import Action, INTENTION_DTYPE
    from .observation import CELL_DTYPE, TILE_DTYPE, EVENT_DTYPE

    def fields(dtype):
        return [{"name": name, "dtype": dtype.fields[name][0].newbyteorder('<').str}
                for name in dtype.names]

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "release-candidate",
        "interfaces": {"transport": 2, "observations": [1, 2], "player_python": 1,
                       "world_python": 1, "local_controller": 1},
        "supported_protocols": list(SUPPORTED_PROTOCOLS),
        "encoding": {"envelope": {"type": "string", "payload": "object"},
                     "array_byteorder": "little", "array_order": "C",
                     "array_types": ["bool", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float32", "float64"],
                     "max_message_bytes": MAX_MESSAGE_BYTES, "max_array_bytes": MAX_ARRAY_BYTES},
        "tables": {"cells_v2": fields(CELL_DTYPE), "tiles_v2": fields(TILE_DTYPE),
                   "events_v2": fields(EVENT_DTYPE), "intentions_v1": fields(INTENTION_DTYPE),
                   "intentions_v2": ["cell_id", "action", "dx", "dy", "param"]},
        "actions": {a.name.lower(): int(a) for a in Action},
        "result_codes": {"ok": 0, "invalid": 1, "no_energy": 2, "duplicate": 3,
                         "disabled": 4, "blocked": 5, "contested": 6, "interrupted": 7, "role": 8},
        "occupants": {"empty": 0, "mine_bonded": 1, "mine": 2, "other": 3, "hidden": 4, "outside": 5},
        "player_entrypoints": ["decide_cell", "decide_entity", "decide_unity", "decide"],
        "world_hooks": {"on_epoch": "(summary, tick) -> parameters",
                        "filter_actions": "(intentions, players, world_view, tick) -> boolean mask",
                        "after_actions": "(events, world_view, tick) -> commands",
                        "before_ecology": "(world_view, tick) -> commands",
                        "on_event": "(event, world_view) -> commands"},
        "identity": {"cell": "(world_run, cell_id)", "entity": "(world_run, entity_id)",
                     "unity": "client-local view; no authoritative ID or membership protocol"},
        "roles": {"none": 0, "boundary": 1, "interior": 2},
        "event_kinds": {"result": 0, "born": 1, "died": 2},
        "death_causes": {"attack": 1, "ecology": 2, "self": 3},
        "bond_offsets": [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]],
        "intention_limits": {"max_per_cell_per_tick": 1, "cell_id": [1, 4294967295],
                             "param": [0, 2147483647], "wire_offset": [-8, 8],
                             "effective_neighbor_offset": [-1, 1], "max_silent_ticks": MAX_SILENT_TICKS},
        "extensions": {"biomes": "optional uint8, one per tiles row; 0 = unavailable",
                       "materials": "optional uint8, one per tiles row; 0 = ordinary or unavailable; check env_visible"},
        "authority": "server validates effects; player programs and local models propose actions",
        "gui_api": "experimental; /api/state and UI layout are not the game transport",
    }


_MESSAGE_REQUIRED = {
    "hello": [], "welcome": ["player_id", "world_w", "world_h"],
    "observation": ["version", "tick", "manifest", "cells", "tiles", "constraints"],
    "intentions": ["tick", "data"], "world_snapshot": ["tick", "arrays"],
    "world_delta": ["tick", "changes"], "sense_batch": ["tick", "cells", "neighborhood", "env", "constraints"],
    "error": ["message"], "ping": [], "pong": [],
}


def protocol_schema():
    """JSON Schema for the envelope and supported core message headers.

    Binary table layouts and semantic constraints live in describe_contract();
    this schema deliberately does not claim to validate decoded base64 tables.
    """
    integer = {"type": "integer", "minimum": 0}
    array_ref = {"$ref": "#/$defs/array"}
    headers = {
        "hello": {"protocol_version": {"type": "integer", "minimum": 1},
                  "protocol_versions": {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}}},
        "welcome": {"player_id": {"type": "integer", "minimum": 1}, "world_w": integer, "world_h": integer},
        "observation": {"version": {"const": 2}, "tick": integer,
                        "manifest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                        "cells": array_ref, "tiles": array_ref, "events": array_ref,
                        "materials": array_ref, "biomes": array_ref, "constraints": {"type": "object"}},
        "intentions": {"tick": integer, "format": {"type": "integer", "enum": [1, 2]},
                       "data": {"anyOf": [{"type": "array"}, array_ref]}},
        "sense_batch": {"tick": integer, "cells": array_ref, "neighborhood": array_ref, "env": array_ref,
                        "constraints": {"type": "object"}},
        "world_snapshot": {"tick": integer, "arrays": {"type": "object"}},
        "world_delta": {"tick": integer, "changes": array_ref},
        "error": {"message": {"type": "string"}, "code": {"type": "string"}},
    }
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "CellGame transport v2 / " + CONTRACT_VERSION,
            "type": "object", "required": ["type", "payload"],
            "properties": {"type": {"type": "string", "minLength": 1, "maxLength": 64},
                           "payload": {"type": "object"}},
            "$defs": {"array": {
                "type": "object", "required": ["__ndarray__"], "additionalProperties": False,
                "properties": {"__ndarray__": {
                    "type": "object", "required": ["dtype", "shape", "data"],
                    "properties": {"dtype": {"type": "string"},
                                   "shape": {"type": "array", "maxItems": 4, "items": integer},
                                   "data": {"type": "string", "contentEncoding": "base64"},
                                   "byteorder": {"const": "little"}, "order": {"const": "C"},
                                   "descr": {"type": "array", "minItems": 1, "maxItems": 64,
                                             "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                                       "items": {"type": "string"}}}}}}}},
            "allOf": []}
    for kind, required in _MESSAGE_REQUIRED.items():
        base["allOf"].append({"if": {"properties": {"type": {"const": kind}}},
                              "then": {"properties": {"payload": {"required": required,
                                                                   "properties": headers.get(kind, {})}}}})
    return copy.deepcopy(base)
