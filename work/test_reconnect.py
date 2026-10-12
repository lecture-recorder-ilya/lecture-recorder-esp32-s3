import sys,tempfile,threading,time,wave,json
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import recorder as r
r.ai_service.auto=False
r.settings={'token':'test'}
def frame(value):
 return b'PCM1'+(4).to_bytes(2,'little')+int(value).to_bytes(2,'little',signed=True)*2
class Fake:
 attempts=0
 def __init__(self):
  Fake.attempts+=1
  self.number=Fake.attempts
  self.data=bytearray(frame(111 if self.number==1 else 222))
 def write(self,data):pass
 def readline(self):return b'STREAM 16000\n'
 def read(self,n):
  if self.data:
   part=self.data[:n];del self.data[:n];return part
  if self.number==1:raise ConnectionResetError('signal lost')
  time.sleep(.01)
  return b''
 def close(self):pass
with tempfile.TemporaryDirectory() as directory:
 r.FILES=Path(directory);r.NetworkStream=Fake;r.stop_recording.clear()
 r.state.update(error='',file='',recording=False,busy=True)
 t=threading.Thread(target=r.capture,args=('wifi',));t.start()
 deadline=time.monotonic()+7
 while time.monotonic()<deadline and Fake.attempts<2:time.sleep(.02)
 assert Fake.attempts>=2
 deadline=time.monotonic()+1
 while time.monotonic()<deadline and r.state['samples']<4:time.sleep(.02)
 r.stop_recording.set();t.join(2);assert not t.is_alive()
 files=list(Path(directory).glob('*.wav'));assert len(files)==1
 with wave.open(str(files[0])) as w:
  pcm=w.readframes(w.getnframes());assert pcm[:4]==(111).to_bytes(2,'little',signed=True)*2
  assert pcm[-4:]==(222).to_bytes(2,'little',signed=True)*2
 gaps=json.loads(files[0].with_suffix('.gaps.json').read_text());assert gaps[0]['duration']>=1.9
 assert not r.state['recording'] and not r.state['reconnecting'] and not r.state['error']
 print('PASS: reconnect appends to one WAV, inserts timed silence, saves gap metadata, stops promptly')
 class Offline:
  def __init__(self):raise OSError('offline')
 r.NetworkStream=Offline;r.stop_recording.clear();r.state.update(error='',file='',busy=True)
 t=threading.Thread(target=r.capture,args=('wifi',));t.start();time.sleep(.1)
 assert r.state['reconnecting'];r.stop_recording.set();t.join(1);assert not t.is_alive()
 print('PASS: stop cancels initial connection retries')
class Slow:
 closed=threading.Event()
 def __init__(self):time.sleep(.8)
 def close(self):Slow.closed.set()
r.NetworkStream=Slow;r.stop_recording.clear();r.state.update(error='',file='',busy=True)
t=threading.Thread(target=r.capture,args=('wifi',));t.start();time.sleep(.1)
start=time.monotonic();r.stop_recording.set();t.join(.5);assert not t.is_alive()
assert time.monotonic()-start<.5
assert Slow.closed.wait(1)
print('PASS: stop cancels a stalled connection and closes a late socket')
