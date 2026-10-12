import sys,socket,select,threading,time,wave,json
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import recorder as r
r.ai_service.auto=False
actual=dict(r.settings)
r.settings=dict(actual,ip='127.0.0.1');r.settings.pop('hostname',None)
r.FILES=Path('work/reconnect-live');r.FILES.mkdir(exist_ok=True)
listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',8766));listener.listen();listener.settimeout(15)
connected=threading.Event();attempts=[];errors=[]
def proxy():
 try:
  for number in (1,2):
   client,_=listener.accept();up=socket.create_connection((actual['ip'],8766),timeout=3)
   attempts.append(number)
   if number==2:connected.set()
   begin=time.monotonic()
   try:
    while not r.stop_recording.is_set():
     if number==1 and time.monotonic()-begin>1:break
     ready,_,_=select.select([client,up],[],[],.1)
     for source in ready:
      data=source.recv(4096)
      if not data:return
      (up if source is client else client).sendall(data)
   finally:client.close();up.close()
 except Exception as exc:errors.append(type(exc).__name__)
 finally:listener.close()
p=threading.Thread(target=proxy,daemon=True);p.start()
r.stop_recording.clear();r.state.update(error='',file='',busy=True)
t=threading.Thread(target=r.capture,args=('wifi',));t.start()
try:
 assert connected.wait(14),errors
 time.sleep(1)
finally:
 r.stop_recording.set();t.join(3);p.join(2)
assert not t.is_alive() and len(attempts)==2 and not r.state['error'],(errors,r.state['error'])
file=r.FILES/r.state['file'];gaps=json.loads(file.with_suffix('.gaps.json').read_text());assert len(gaps)==1
with wave.open(str(file)) as w:
 pcm=w.readframes(w.getnframes());assert w.getnframes()==r.state['samples'];assert any(pcm)
assert r.state['samples']>16000 and gaps[0]['duration']>1
print('PASS: real ESP stream resumed after forced TCP disconnect; same WAV; gap',gaps[0]['duration'],'seconds; audio',r.state['seconds'],'seconds')
