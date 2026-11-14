"""Minimal language-independent protocol example; stdout is protocol-only."""
import json
import sys

for line in sys.stdin:
    try:
        observation = json.loads(line)
        actions = []
        for cell, env in zip(observation["cells"], observation["env"]):
            x, y, _, _, energy = cell
            if env[1] > 0:
                actions.append([x, y, x, y, 3, 0, 0])  # EAT
        print(json.dumps({"tick": observation["tick"], "actions": actions}),
              flush=True)
    except Exception as exc:
        print(f"agent error: {exc}", file=sys.stderr, flush=True)
