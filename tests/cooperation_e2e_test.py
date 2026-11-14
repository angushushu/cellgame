"""Exercise cooperation through the real server, client, and console API."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def get(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def main():
    server = subprocess.Popen([sys.executable, '-m', 'server.main', '--port', '18865', '--http-port', '18866', '--tick-ms', '500'], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = None
    try:
        time.sleep(1)
        client = subprocess.Popen([sys.executable, '-m', 'client.main', '--server', 'ws://127.0.0.1:18865', '--name', 'cooperation', '--rules', 'species/cooperative.py', '--http-port', '18867'], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 25
        last = None
        while time.monotonic() < deadline:
            try:
                last = get('http://127.0.0.1:18867/api/state')
                if last['connected'] and last.get('bonds_b64') and any(base64.b64decode(last['bonds_b64'])):
                    assert not last['last_exec_error'], last['last_exec_error']
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.3)
        else:
            raise AssertionError(f'no connected cells reached the console: {last}')
        source = get('http://127.0.0.1:18867/api/species?name=cooperative')
        assert 'bond=True' in source['source']
        print('COOPERATION E2E TEST PASSED')
    finally:
        if client:
            client.terminate()
            client.wait(timeout=5)
        server.terminate()
        server.wait(timeout=5)

if __name__ == '__main__':
    main()
