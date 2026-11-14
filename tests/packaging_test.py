"""Install a built wheel away from the checkout and run the real programs.

Usage: python tests/packaging_test.py path/to/cellgame-<version>-py3-none-any.whl
Uses system site packages for the already-installed NumPy and websockets.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import re

# The version the wheel must report: the one in this source tree.
SOURCE_VERSION = re.search(r'__version__ = "([^"]+)"',
                           (Path(__file__).resolve().parents[1] / "cellgame" / "__init__.py").read_text(encoding="utf-8")).group(1)


def request(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.read()


def wait_json(url, condition=lambda _: True, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(request(url))
            if condition(value):
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    raise AssertionError(f'no expected response from {url}')


def main():
    wheel = Path(sys.argv[1]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='cellgame-installed-', dir=os.environ.get('CELLGAME_TEST_TEMP'), ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        envdir = root / 'env'
        subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(envdir)], check=True)
        scripts = envdir / ('Scripts' if os.name == 'nt' else 'bin')
        py = scripts / ('python.exe' if os.name == 'nt' else 'python')
        subprocess.run([str(py), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)],
                       cwd=root, check=True, stdout=subprocess.DEVNULL)
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        env['PYTHONUNBUFFERED'] = '1'
        info = subprocess.check_output([str(py), '-c', 'import cellgame; print(cellgame.__version__); print(cellgame.__file__)'],
                                       cwd=root, env=env, text=True)
        assert SOURCE_VERSION in info and str(envdir).lower() in info.lower(), (SOURCE_VERSION, info)
        subprocess.run([str(py), '-c',
            "import sys,json; from importlib.resources import files; from cellgame.api import describe_contract; "
            "assert not any(n.startswith('cellgame.client') for n in sys.modules); "
            "root=files('cellgame.shared'); "
            "assert json.loads(root.joinpath('contract-v1.json').read_text(encoding='utf8'))==describe_contract(); "
            "assert root.joinpath('schemas/transport-v2.schema.json').is_file(); "
            "assert root.joinpath('fixtures/observation-v2.json').is_file()"], cwd=root, env=env, check=True)
        registry = json.loads(subprocess.check_output([str(py), '-m', 'cellgame', 'contract'], cwd=root, env=env))
        assert registry['contract_version'] == '1.0.0-rc.1'
        for role in ('server', 'client'):
            assert b'--help' in subprocess.check_output([str(py), '-m', 'cellgame', role, '--help'], cwd=root, env=env)
        server_exe = scripts / ('cellgame-server.exe' if os.name == 'nt' else 'cellgame-server')
        client_exe = scripts / ('cellgame-client.exe' if os.name == 'nt' else 'cellgame-client')
        subprocess.run([str(server_exe), "--help"], cwd=root, env=env, capture_output=True, check=True)
        subprocess.run([str(client_exe), "--help"], cwd=root, env=env, capture_output=True, check=True)
        server_log = open(root / "server.log", "w+", encoding="utf8")
        client_log = open(root / "client.log", "w+", encoding="utf8")
        server = subprocess.Popen([str(py), '-m', 'cellgame', 'server', '--host', '127.0.0.1', '--port', '18965', '--http-port', '18966', '--tick-ms', '600', '--world-preset', 'lush'], cwd=root, env=env, stdout=server_log, stderr=subprocess.STDOUT)
        client = None
        try:
            wait_json('http://127.0.0.1:18966/api/players', lambda s: s.get('world_ready'))
            assert json.loads(request('http://127.0.0.1:18966/api/contract')) == registry
            client = subprocess.Popen([str(py), '-m', 'cellgame', 'client', '--server', 'ws://127.0.0.1:18965', '--http-port', '18967'], cwd=root, env=env, stdout=client_log, stderr=subprocess.STDOUT)
            state = wait_json('http://127.0.0.1:18967/api/state', lambda s: s.get('connected') and s.get('last_sense_tick', -1) >= 0 and s.get('visual_seq', 0) > 0 and s.get('chat_available'))
            assert json.loads(request('http://127.0.0.1:18967/api/contract')) == registry
            assert json.loads(request('http://127.0.0.1:18967/api/protocol-schema'))['$schema'].endswith('/2020-12/schema')
            assert not state.get('last_exec_error'), state.get('last_exec_error')
            page = request('http://127.0.0.1:18967/').decode('utf8')
            # Stable element ids, not wording: the console text changes between versions.
            assert '物种实验室' in page and 'id="effectsBtn"' in page and 'id="chatLog"' in page and 'id="world"' in page
            sent = json.loads(request('http://127.0.0.1:18967/api/chat', {'text':'packaging test'}))
            assert sent.get('ok'), sent
            wait_json('http://127.0.0.1:18967/api/state', lambda s: any(m.get('text') == 'packaging test' for m in s.get('chat_messages', [])))
            assert b'WorldView' in request('http://127.0.0.1:18967/world-view.js')
            assert 'decide_cell' in json.loads(request('http://127.0.0.1:18967/api/species?name=cooperative'))['source']
            result = json.loads(request('http://127.0.0.1:18967/api/preview', {'ticks': 5}))
            assert result.get('ok'), result
            print('PACKAGED INSTALL AND LIVE GAME TEST PASSED')
        except Exception:
            print('server exit status:', server.poll())
            for label, log in (("server", server_log), ("client", client_log)):
                log.flush(); log.seek(0)
                print(f"{label} output: {log.read()}")
            raise
        finally:
            for process in (client, server):
                if process is not None:
                    process.terminate()
                    process.wait(timeout=10)
            server_log.close(); client_log.close()

if __name__ == '__main__':
    main()
