"""server.properties / client.properties: parsing, defaults file, precedence,
manifest overrides, and real server/client launches from config files."""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cellgame.client.settings import CLIENT_OPTIONS, resolve_client_settings
from cellgame.server.settings import SERVER_OPTIONS, resolve_server_settings
from cellgame.shared.properties import PropertiesError, parse_properties, render_properties


def expect_error(text, fragment):
    try:
        parse_properties(text, SERVER_OPTIONS)
    except PropertiesError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"expected PropertiesError for {text!r}")


def server_args(**given):
    """An argparse namespace where everything not given is None (= not on the command line)."""
    names = {option.dest for option in SERVER_OPTIONS} | {"config"}
    return Namespace(**{name: given.get(name) for name in names})


# -- parsing -----------------------------------------------------------------

def test_parse_comments_spacing_and_empty_values():
    props = parse_properties(
        "# 注释\n\n server-port = 9000 \nweb-port=9001\nseed=\nworld-rules=rules/my=world.py\n",
        SERVER_OPTIONS)
    assert props == {"server-port": 9000, "web-port": 9001, "world-rules": "rules/my=world.py"}


def test_parse_rejects_bad_input_with_line_numbers():
    expect_error("server-port=8765\nwrold-preset=lush\n", "第 2 行")
    expect_error("wrold-preset=lush", "wrold-preset")
    expect_error("server-port=abc", "server-port")
    expect_error("server-port=70000", "server-port")
    expect_error("world-preset=jungle", "world-preset")
    expect_error("perception=telepathy", "perception")
    expect_error("move-cost=101", "move-cost")
    expect_error("just some text", "key=value")


def test_default_file_round_trips():
    text = render_properties(SERVER_OPTIONS, "CellGame 服务器设置")
    assert text.startswith("# CellGame 服务器设置")
    assert "server-port=8765" in text and "world-preset=balanced" in text and "\nworld-rules=\n" in text
    parsed = parse_properties(text, SERVER_OPTIONS)
    assert parsed["server-port"] == 8765 and parsed["world-preset"] == "balanced"
    assert "world-rules" not in parsed and "perception" not in parsed
    client_text = render_properties(CLIENT_OPTIONS, "CellGame 客户端设置")
    assert parse_properties(client_text, CLIENT_OPTIONS)["server"] == "ws://localhost:8765"


# -- precedence ----------------------------------------------------------------

def test_command_line_beats_file_beats_default():
    props = {"server-port": 9000, "web-port": 9001, "tick-ms": 500, "move-cost": 4}
    settings = resolve_server_settings(server_args(port=7000), props, ROOT)
    assert settings["port"] == 7000           # command line
    assert settings["http_port"] == 9001      # file
    assert settings["tick_ms"] == 500
    assert settings["move_cost"] == 4
    assert settings["host"] == "0.0.0.0"      # default
    assert settings["attack_cost"] == 3


def test_world_rules_path_is_relative_to_the_file_and_beats_its_preset():
    with tempfile.TemporaryDirectory() as tmp:
        settings = resolve_server_settings(server_args(), {"world-rules": "mine.py", "world-preset": "lush"}, Path(tmp))
        assert Path(settings["world_rules"]) == Path(tmp) / "mine.py"
        settings = resolve_server_settings(server_args(world_preset="deep-dive"), {"world-rules": "mine.py"}, Path(tmp))
        assert settings["world_rules"] is None and settings["world_preset"] == "deep-dive"
        settings = resolve_server_settings(server_args(), {}, Path(tmp))
        assert settings["world_rules"] is None and settings["world_preset"] == "balanced"


def test_client_precedence():
    with tempfile.TemporaryDirectory() as tmp:
        props = {"server": "ws://10.0.0.5:9000", "web-port": 9100, "name": "amoeba", "rules": "r.py"}
        names = {option.dest for option in CLIENT_OPTIONS}
        args = Namespace(**{name: None for name in names}, config=None)
        args.name = "from-cli"
        settings = resolve_client_settings(args, props, Path(tmp))
        assert settings["server"] == "ws://10.0.0.5:9000" and settings["http_port"] == 9100
        assert settings["name"] == "from-cli" and Path(settings["rules"]) == Path(tmp) / "r.py"


def test_manifest_options_from_properties():
    from cellgame.server.main import manifest_for
    settings = resolve_server_settings(server_args(), {
        "world-preset": "deep-dive", "sense-radius": 2, "spectator-map": "full",
        "bonded-support-percent": 30}, ROOT)
    manifest = manifest_for(settings)
    assert manifest["perception"]["model"] == "blanket" and manifest["perception"]["external_radius"] == 2
    assert manifest["visibility"]["spectator"] == "full"
    assert manifest["combat"]["bonded_support_percent"] == 30
    radius = manifest_for(resolve_server_settings(server_args(), {"perception": "radius", "sense-radius": 3}, ROOT))
    assert radius["perception"] == {"model": "radius", "radius": 3, "metric": "chebyshev"}


# -- real launches ---------------------------------------------------------------

def get_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def wait_json(url, ok, timeout=25):
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        try:
            last = get_json(url)
            if ok(last):
                return last
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    raise AssertionError(f"{url} never satisfied the check: {last}")


def test_server_and_client_start_from_config_files():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        server_props = tmp / "server.properties"
        server_props.write_text("server-ip=127.0.0.1\nserver-port=19865\nweb-port=19866\n"
                                "tick-ms=500\nworld-preset=deep-dive\nbonded-support-percent=30\n", encoding="utf-8")
        client_props = tmp / "client.properties"
        client_props.write_text("server=ws://127.0.0.1:19865\nweb-port=19867\nname=configured\n", encoding="utf-8")
        created = tmp / "fresh" / "server.properties"
        processes = [
            subprocess.Popen([sys.executable, "-m", "server.main", "--config", str(server_props)], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
            subprocess.Popen([sys.executable, "-m", "client.main", "--config", str(client_props)], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        ]
        try:
            status = wait_json("http://127.0.0.1:19866/api/players", lambda s: s.get("world_ready"))
            assert status["settings"]["world_preset"] == "deep-dive" and status["map_visibility"] == "none"
            assert status["game_port"] == 19865 and status["settings"]["tick_ms"] == 500
            state = wait_json("http://127.0.0.1:19867/api/state", lambda s: s.get("connected") and s.get("tick", 0) >= 2)
            assert state["player_name"] == "configured" and state["perception"]["model"] == "blanket"
            # A missing config file named on the command line is created with defaults.
            created.parent.mkdir()
            maker = subprocess.run([sys.executable, "-m", "server.main", "--config", str(created), "--check-config"],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
            assert maker.returncode == 0, maker.stderr
            assert created.exists() and "server-port=8765" in created.read_text(encoding="utf-8")
            bad = tmp / "bad.properties"
            bad.write_text("server-port=oops\n", encoding="utf-8")
            failed = subprocess.run([sys.executable, "-m", "server.main", "--config", str(bad), "--check-config"],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
            assert failed.returncode != 0 and "server-port" in failed.stderr
        finally:
            for process in processes:
                process.terminate()
                process.wait(timeout=5)


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PROPERTIES TEST PASSED")


if __name__ == "__main__":
    main()
