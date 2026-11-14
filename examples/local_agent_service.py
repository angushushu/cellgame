"""Local CellGame HTTP adapter example (a hand-written policy, not an ML model).

Replace choose_actions() with model inference while keeping the JSON contract.
Run from the project directory: python examples/local_agent_service.py
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def choose_actions(observation):
    actions = []
    for cell, env in zip(observation["cells"], observation["env"]):
        x, y, _, _, energy = cell
        if env[1] > 0 and energy < 20:
            actions.append([x, y, x, y, 3, 0, 0])
    return actions


def respond(observation):
    if not isinstance(observation, dict) or observation.get("version") != 1:
        raise ValueError("unsupported observation version")
    if type(observation.get("tick")) is not int:
        raise ValueError("tick must be an integer")
    return {"tick": observation["tick"], "actions": choose_actions(observation)}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path != "/decide":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 8 * 1024 * 1024:
                raise ValueError("invalid request size")
            observation = json.loads(self.rfile.read(length))
            body = json.dumps(respond(observation)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, KeyError, TypeError) as exc:
            self.send_error(400, str(exc))


if __name__ == "__main__":
    print("CellGame example adapter listening on http://127.0.0.1:9000/decide", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 9000), Handler).serve_forever()
