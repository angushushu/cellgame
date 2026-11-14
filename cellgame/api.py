"""Public integration facade, contract 1.0.0-rc.1.

Importing this module opens no socket, starts no process and loads no GUI.
WorldState is a reference world implementation, not a frozen storage layout.
"""
from cellgame.shared.contract import (
    CONTRACT_VERSION, PROTOCOL_VERSION, PLAYER_API_VERSION, WORLD_API_VERSION,
    CONTROLLER_VERSION, describe_contract, protocol_schema, negotiate_protocol,
)
from cellgame.shared.models import Action, INTENTION_DTYPE
from cellgame.shared.protocol import encode_msg, decode_msg, array_to_b64, b64_to_array, ProtocolError
from cellgame.shared.manifest import build_manifest, manifest_hash
from cellgame.shared.observation import validate_observation, expand_observation, observation_to_json, intentions_to_v2, to_legacy_batch
from cellgame.species.simple import Cell, Neighbor, Percept
from cellgame.species.units import Entity, Unity, make_entities
from cellgame.species.runtime import load_rule, to_intentions
from cellgame.server.world import WorldState
from cellgame.server.world_rules import WorldRuleEngine, WorldView, apply_world_params, run_tick_event
from cellgame.server.kernel import resolve_tick
from cellgame.server.perception import gather_observation

__all__ = [
    "CONTRACT_VERSION", "PROTOCOL_VERSION", "PLAYER_API_VERSION", "WORLD_API_VERSION", "CONTROLLER_VERSION",
    "describe_contract", "protocol_schema", "negotiate_protocol", "Action", "INTENTION_DTYPE",
    "encode_msg", "decode_msg", "array_to_b64", "b64_to_array", "ProtocolError",
    "build_manifest", "manifest_hash", "validate_observation", "expand_observation", "observation_to_json", "intentions_to_v2", "to_legacy_batch",
    "load_rule", "to_intentions", "make_entities", "gather_observation",
    "Cell", "Neighbor", "Percept", "Entity", "Unity", "WorldState", "WorldRuleEngine", "WorldView",
    "apply_world_params", "run_tick_event", "resolve_tick",
]
