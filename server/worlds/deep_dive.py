"""深潜（deep-dive）：毯感知、感知收费、隐藏季节。

Select it with ``--world-preset deep-dive``. The world is designed so that
prediction pays without being rewarded directly (docs/WORLD_MANIFEST_zh.md §8):

- hidden state: most food grows in a fertile zone that nobody can see from afar,
  and other organisms' interiors are hidden;
- regularity: the zone circles the map with a fixed period;
- delay: a wider view (``sense``) only arrives with the next observation;
- information cost: ``sense`` costs energy per radius, and membrane (boundary)
  cells burn energy twice as fast as interior cells.
"""
import math

from cellgame.server.default_world_rules import on_epoch as base_on_epoch, after_actions, before_ecology

MANIFEST = {
    "id": "deep-dive",
    "name": "深潜",
    # Small enough that the fertile zone (0.3 × size from the centre) is
    # reachable from the central spawn area.
    "world": {"width": 128, "height": 128},
    "perception": {"model": "blanket", "external_radius": 1},
    # The fertile zone and other organisms' interiors are the hidden state the
    # world is built around; the spectator page must not reveal them.
    "visibility": {"others_interior": "hidden", "state": "boundary_only", "spectator": "none"},
    "ecology": {"metabolism": {"boundary": 2, "interior": 1}},
    # A bonded body defends as a whole: a cell's defence also counts half its
    # bonded neighbours' energy. Without it a sessile body is the easiest prey
    # there is (docs/WORLD_MANIFEST_zh.md §16).
    "combat": {"bonded_support_percent": 50},
    "actions": {
        "sense": {"enabled": True, "cost_per_radius": 1, "max_radius": 4},
        "eat": {"actor_roles": ["boundary"]},
    },
}

SEASON_TICKS = 120        # one full circle of the fertile zone
ZONE_RADIUS = 6
ZONE_FOOD_EVERY = 5       # ticks between food drops in the zone
ZONE_DROPS = 40


def fertile_center(tick, width, height):
    """Where the hidden fertile zone is at a given tick."""
    angle = 2 * math.pi * (tick % SEASON_TICKS) / SEASON_TICKS
    return (int(width / 2 + 0.3 * width * math.cos(angle)),
            int(height / 2 + 0.3 * height * math.sin(angle)))


def on_epoch(summary, tick):
    params = base_on_epoch(summary, tick)
    # A thin local trickle keeps blind organisms alive but hungry; the rich
    # food is in the fertile zone (tuned with tests/blanket_experiment.py).
    params.update(food_regrow=150, food_regrow_near_cells=20)
    return params


def on_event(event, world_view):
    tick = int(event.get("tick", 0))
    if tick % ZONE_FOOD_EVERY:
        return []
    constraints = event.get("summary", {}).get("constraints", {})
    width, height = constraints.get("world_w", 256), constraints.get("world_h", 256)
    cx, cy = fertile_center(tick, width, height)
    commands, state = [], tick * 2654435761 % 4294967296
    for _ in range(ZONE_DROPS):
        state = (state * 1103515245 + 12345) % 2147483648
        dx = state % (2 * ZONE_RADIUS + 1) - ZONE_RADIUS
        dy = (state // 97) % (2 * ZONE_RADIUS + 1) - ZONE_RADIUS
        if dx * dx + dy * dy <= ZONE_RADIUS * ZONE_RADIUS:
            commands.append({"type": "add_food", "x": cx + dx, "y": cy + dy, "amount": 6})
    return commands
