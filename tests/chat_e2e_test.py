"""Exercise public chat through two real clients and the real game server."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = 'http://127.0.0.1:19166'
CLIENTS = ['http://127.0.0.1:19167', 'http://127.0.0.1:19168']


def api(base, path, body=None):
    request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode('utf8'),
                                     headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def wait_for(fn, timeout=20):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise AssertionError(f'condition not reached: {last}')


def main():
    py = sys.executable
    server = subprocess.Popen([py,'-m','cellgame','server','--host','127.0.0.1','--port','19165','--http-port','19166','--tick-ms','700'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    clients = []
    try:
        wait_for(lambda: api(SERVER,'/api/players').get('world_ready'))
        for port, name in ((19167,'Alpha'),(19168,'Beta')):
            clients.append(subprocess.Popen([py,'-m','cellgame','client','--server','ws://127.0.0.1:19165','--http-port',str(port),'--name',name],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for base in CLIENTS:
            wait_for(lambda: api(base,'/api/state').get('chat_available'))
        assert not api(CLIENTS[0],'/api/chat',{'text':'   '})['ok']
        assert not api(CLIENTS[0],'/api/chat',{'text':'x'*201})['ok']
        assert not api(CLIENTS[0],'/api/chat',{'text':'hello\nworld'})['ok']
        text = '<script>hello</script> 你好 🌱'
        assert api(CLIENTS[0],'/api/chat',{'text':text})['ok']
        for base in CLIENTS:
            state = wait_for(lambda: (s if any(m['text']==text for m in s['chat_messages']) else None) if (s:=api(base,'/api/state')) else None)
            message = next(m for m in state['chat_messages'] if m['text']==text)
            assert message['name']=='Alpha' and message['player_id']>0
        sender=wait_for(lambda: (s if not s['chat_pending'] else None) if (s:=api(CLIENTS[0],'/api/state')) else None)
        assert sender['chat_error'] is None
        # Server snapshots the current profile on each sent message.
        result=api(CLIENTS[0],'/api/profile',{'name':'新版名字','color':'#11aa33'})
        assert result['ok']
        wait_for(lambda: api(CLIENTS[0],'/api/state')['player_name']=='新版名字')
        time.sleep(1.05)
        assert api(CLIENTS[0],'/api/chat',{'text':'改名成功'})['ok']
        other=wait_for(lambda: (s if any(m['text']=='改名成功' for m in s['chat_messages']) else None) if (s:=api(CLIENTS[1],'/api/state')) else None)
        message=next(m for m in other['chat_messages'] if m['text']=='改名成功')
        assert message['name']=='新版名字' and message['color']=='#11AA33'
        # Rejoining restores the bounded server-side history.
        api(CLIENTS[1],'/api/disconnect',{})
        wait_for(lambda: not api(CLIENTS[1],'/api/state')['connected'])
        assert api(CLIENTS[1],'/api/connect',{'url':'ws://127.0.0.1:19165','name':'Beta'})['ok']
        other=wait_for(lambda: (s if s['connected'] and any(m['text']=='改名成功' for m in s['chat_messages']) else None) if (s:=api(CLIENTS[1],'/api/state')) else None)
        assert any(m['text']==text for m in other['chat_messages'])
        print('PUBLIC CHAT END-TO-END TEST PASSED')
    finally:
        for process in clients+[server]:
            process.terminate()
        for process in clients+[server]:
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()

if __name__=='__main__':
    main()
