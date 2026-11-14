"""Authoritative chat identity, rate limits and read-only spectators."""
import asyncio
import queue
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cellgame.client.net import ClientState, GameClient
from cellgame.server.net import GameServer
from cellgame.server.world import WorldState
from cellgame.shared.protocol import encode_msg, decode_msg

class Socket:
    def __init__(self, messages=()): self.messages=iter(messages); self.sent=[]
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self.messages)
        except StopIteration: raise StopAsyncIteration
    async def send(self, raw): self.sent.append(decode_msg(raw))

async def check():
    server=GameServer(queue.Queue(),queue.Queue())
    server.apply_snapshot(WorldState(8,8).snapshot_arrays())
    server.chat_clock=lambda:100.0
    observer=Socket()
    server.spectators.add(observer)
    sender=Socket([
        encode_msg('hello',player_name='真实名字',player_color='#12ab34'),
        encode_msg('chat_send',text='大家好',request_id='one',name='伪造名字',player_id=999,color='#000000'),
        encode_msg('chat_send',text='太快',request_id='two'),
        encode_msg('chat_send',text='x'*201,request_id='three'),
        encode_msg('chat_send',text='bad\ntext',request_id='four'),
    ])
    await server.handle_game(sender)
    events=[data for kind,data in sender.sent if kind=='chat_message']
    assert len(events)==1
    assert events[0]['name']=='真实名字' and events[0]['player_id']==1 and events[0]['color']=='#12AB34'
    assert events[0]['text']=='大家好' and events[0]['request_id']=='one'
    errors={data['request_id']:data['message'] for kind,data in sender.sent if kind=='chat_error'}
    assert '太快' in errors['two'] and '200' in errors['three'] and '控制' in errors['four']
    assert any(kind=='chat_message' and msg['text']=='大家好' for kind,msg in observer.sent)
    assert len(server.chat_history)==1
    # Spectators receive history, but cannot send public messages.
    spectator=Socket([encode_msg('chat_send',text='不能发送',request_id='x')])
    await server.handle_spectator(spectator)
    history=next(msg['messages'] for kind,msg in spectator.sent if kind=='chat_history')
    assert history[0]['text']=='大家好' and len(server.chat_history)==1
    # Server memory is bounded and old entries are evicted.
    for i in range(120): server.chat_history.append({'id':i})
    assert len(server.chat_history)==100 and server.chat_history[0]['id']==20
    # Older servers without the feature flag must not offer sending.
    state=ClientState(); client=GameClient(state,None)
    await client.handle('welcome', {'player_id':7, 'players':[]})
    assert state.chat_available is False
    await client.handle('welcome', {'player_id':7, 'players':[], 'features':{'chat':True}})
    assert state.chat_available is True
    state.chat_pending='ours'
    await client.handle('chat_error', {'request_id':'other','message':'wrong'})
    assert state.chat_pending=='ours'
    await client.handle('chat_error', {'request_id':'ours','message':'rejected'})
    assert state.chat_pending is None and state.chat_last_result=={'request_id':'ours','error':'rejected'}
    state.chat_pending='next'
    message={'id':1,'player_id':7,'name':'Me','text':'hello','request_id':'next','color':'#123456','timestamp':0}
    await client.handle('chat_message',message)
    await client.handle('chat_history',{'messages':[message]})
    assert len(state.chat_messages)==1 and state.chat_last_result=={'request_id':'next','error':None}
    print('CHAT PROTOCOL TEST PASSED')

if __name__=='__main__': asyncio.run(check())
