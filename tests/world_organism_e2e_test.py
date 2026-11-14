"""Verify actual clients receive server settings and organism hover metadata."""
import base64, json, subprocess, sys, time, urllib.request
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def get(url):
    with urllib.request.urlopen(url,timeout=3) as r: return json.load(r)
def wait(fn,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            result=fn()
            if result:return result
        except (OSError,ValueError,KeyError):pass
        time.sleep(.1)
    raise AssertionError('timeout waiting for world and organism')
def main():
    py=sys.executable
    server=subprocess.Popen([py,'-m','cellgame','server','--host','127.0.0.1','--port','19365','--http-port','19366','--tick-ms','1000','--move-cost','7','--eat-gain','2'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    client=None
    try:
        wait(lambda:get('http://127.0.0.1:19366/api/players').get('world_ready'))
        client=subprocess.Popen([py,'-m','cellgame','client','--server','ws://127.0.0.1:19365','--http-port','19367'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        state=wait(lambda:(s if s.get('connected') and s.get('owner_b64') and s.get('player_id') else None) if (s:=get('http://127.0.0.1:19367/api/state')) else None)
        settings=wait(lambda:(s if s.get('constraints',{}).get('move_cost')==7 else None) if (s:=get('http://127.0.0.1:19366/api/players')) else None)
        assert settings['constraints']['eat_gain']==2
        def find_cell():
            s=get('http://127.0.0.1:19367/api/state')
            owners=np.frombuffer(base64.b64decode(s['owner_b64']),dtype='<i4').reshape(s['world_h'],s['world_w'])
            for y,x in zip(*np.where(owners==s['player_id'])):
                url=f'/api/organism?x={x}&y={y}'
                item=get('http://127.0.0.1:19367'+url)['organism']
                if item and item['cells']>=1 and item['energy']>=0:
                    return int(x),int(y),item
        x,y,item=wait(find_cell)
        assert item['owner_name'] and item['origin'] in ('founder','birth','split') and 'children' in item
        print('LIVE WORLD CONFIG AND ORGANISM HOVER TEST PASSED')
    finally:
        if client:client.terminate();client.wait(timeout=5)
        server.terminate();server.wait(timeout=5)
if __name__=='__main__':main()
