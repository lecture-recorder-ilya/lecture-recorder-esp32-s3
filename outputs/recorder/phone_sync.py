"""Automatic USB / local Wi-Fi / Bluetooth import; acknowledge only durable verified copies."""
import fcntl,hashlib,hmac,json,os,re,secrets,shutil,socket,subprocess,threading,time,wave
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent.parent/'work'
CONFIG=WORK/'phone-sync.json';LEDGER=WORK/'phone-imports.json';FILES=ROOT/'recordings'
state={'connected':False,'message':'Ожидаю телефон · Wi-Fi / Bluetooth / USB','imported':0};started=False
STATUS=WORK/'phone-sync-status.json'
def status():
 try:return json.loads(STATUS.read_text())
 except (OSError,ValueError):return dict(state)
def atomic(path,value):
 temp=path.with_suffix(path.suffix+'.tmp')
 with temp.open('w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 temp.replace(path);sync_dir(path.parent)
def sync_dir(path):
 fd=os.open(path,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def validate(path):
 with wave.open(str(path)) as w:
  if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):raise ValueError('Неподдерживаемый WAV телефона')
  if path.stat().st_size!=44+2*w.getnframes():raise ValueError('Неполный WAV телефона')
def auth_headers(token,method,route,body=b'',extra=None):
 headers=dict(extra or {});stamp=str(int(time.time()));nonce=secrets.token_hex(16)
 signed='\n'.join((method,route,stamp,nonce,headers.get('Range',''),hashlib.sha256(body).hexdigest()))
 headers.update({'X-Lecture-Time':stamp,'X-Lecture-Nonce':nonce,'X-Lecture-Signature':hmac.new(token.encode(),signed.encode(),hashlib.sha256).hexdigest(),'Content-Type':'application/json'})
 return headers
def request(base,token,route,data=None,extra=None):
 body=json.dumps(data).encode() if data is not None else None
 headers=auth_headers(token,'POST' if body is not None else 'GET',route,body or b'',extra)
 if base=='http://127.0.0.1:8781':headers['Authorization']='Bearer '+token # Legacy APK; USB loopback only.
 return urlopen(Request(base+route,data=body,headers=headers),timeout=60)
def discover_wifi(token):
 nonce=secrets.token_hex(16);expected=hmac.new(token.encode(),('DISCOVER\n'+nonce+'\n8780').encode(),hashlib.sha256).hexdigest()
 destinations={'255.255.255.255'}
 try:
  info=subprocess.run(['/sbin/ifconfig'],capture_output=True,timeout=3,check=True).stdout.decode()
  destinations.update(re.findall(r'broadcast ([0-9.]+)',info))
 except (OSError,subprocess.SubprocessError):pass
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
  udp.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1);udp.settimeout(.4)
  for ip in destinations:
   try:udp.sendto(('LECTURES1 '+nonce).encode(),(ip,8783))
   except OSError:pass
  until=time.monotonic()+1.5
  while time.monotonic()<until:
   try:
    message,peer=udp.recvfrom(1024);parts=message.decode('ascii').split()
    if len(parts)==4 and parts[:3]==['LECTURES1',nonce,'8780'] and hmac.compare_digest(parts[3],expected):return 'http://'+peer[0]+':8780'
   except (OSError,ValueError):pass
 return None
def import_one(item,base,token,files=FILES,ledger_path=LEDGER):
 if re.fullmatch(r'board-[0-9]{13}-[a-f0-9]{32}\.jpg',item.get('name','')):
  import board_photos
  return board_photos.import_one(item,base,token,root=files.parent)
 name=item['name'];size=item['bytes'];sha=item['sha256']
 if not re.fullmatch(r'lecture-[0-9-]+\.wav',name) or not isinstance(size,int) or not 44<=size<=4_200_000_044 or not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('Некорректные сведения записи')
 files.mkdir(exist_ok=True);target=files/name;ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
 if target.exists():
  if target.stat().st_size!=size or digest(target)!=sha:raise ValueError('На Mac уже есть другая запись с этим именем; телефон сохранён')
 else:
  if shutil.disk_usage(files).free<size+100*1024*1024:raise OSError('На Mac недостаточно места; телефон сохранён')
  temp=files/(name+'.phone-part');resume_meta=files/(name+'.phone-part.json')
  identity={'sha256':sha,'bytes':size}
  try:resume_ok=json.loads(resume_meta.read_text())==identity
  except (OSError,ValueError):resume_ok=False
  if not resume_ok or (temp.exists() and temp.stat().st_size>size):temp.unlink(missing_ok=True)
  atomic(resume_meta,identity);count=temp.stat().st_size if temp.exists() else 0
  if count<size:
   with request(base,token,'/file/'+name,extra={'Range':'bytes='+str(count)+'-'} if count else None) as response:
    if count and response.status!=206:count=0
    elif count and response.headers.get('Content-Range')!='bytes '+str(count)+'-'+str(size-1)+'/'+str(size):raise ValueError('Некорректное продолжение копии')
    with temp.open('ab' if count else 'wb') as f:
     try:
      for data in iter(lambda:response.read(65536),b''):
       count+=len(data)
       if count>size:raise ValueError('Размер записи изменился')
       f.write(data)
     finally:f.flush();os.fsync(f.fileno())
   if count!=size:raise OSError('Перенос прервался; продолжу при подключении')
  if digest(temp)!=sha:
   temp.unlink(missing_ok=True);resume_meta.unlink(missing_ok=True);raise ValueError('Копия не совпала; телефон сохранён')
  validate(temp)
  os.link(temp,target);temp.unlink();resume_meta.unlink(missing_ok=True);sync_dir(files)

 validate(target)
 with target.open('rb') as local:os.fsync(local.fileno())
 sync_dir(files)
 if name not in ledger:
  gaps=[{'start':float(g['start']),'duration':float(g['seconds'])} for g in item.get('gaps',[])]
  if gaps:atomic(target.with_suffix('.gaps.json'),gaps)
  atomic(target.with_suffix('.phone.json'),dict(source='android',sha256=sha,started_ms=item.get('started_ms'),error=item.get('error','')))
  import lesson_schedule
  lesson_schedule.organize(name)
  ledger[name]={'sha256':sha,'bytes':size,'queued':False};atomic(ledger_path,ledger)
 # A failed acknowledgement is retried against the already verified local copy.
 with request(base,token,'/ack',{'name':name,'sha256':sha}) as r:
  if not json.load(r).get('ok'):raise ValueError('Телефон не подтвердил очистку')
 queue_pending(ledger_path)
 return name
def queue_pending(ledger_path=LEDGER):
 ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
 for name,entry in ledger.items():
  if entry.get('queued'):continue
  try:
   with urlopen(Request('http://127.0.0.1:8765/analyze',data=json.dumps({'file':name}).encode(),headers={'Content-Type':'application/json'}),timeout=10) as r:json.load(r)
   ledger[name]['queued']=True;atomic(ledger_path,ledger)
  except OSError:pass
def candidates(cfg):
 token=cfg['token'];adb=shutil.which('adb') or '/opt/homebrew/bin/adb'
 def command(args):return subprocess.run([adb,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,check=True).stdout
 try:
  if cfg['serial']+'\tdevice' in command(['devices']).decode():
   command(['-s',cfg['serial'],'forward','tcp:8781','tcp:8780'])
   base='http://127.0.0.1:8781'
   try:
    with request(base,token,'/list') as r:json.load(r)
   except OSError:
    command(['-s',cfg['serial'],'shell','am','start-foreground-service','-n','ru.ilya.lecturerecorder/.CaptureService','-a','SYNC','--es','auth',token]);time.sleep(1)
   yield base,'USB'
 except (OSError,subprocess.SubprocessError):pass
 base=discover_wifi(token)
 if base:yield base,'Wi-Fi'
 # Bluetooth helper is a native accessory app with the macOS Bluetooth usage description.
 bridge=ROOT.parent/'Синхронизация Bluetooth.app'
 if bridge.exists():
  try:
   with socket.create_connection(('127.0.0.1',8782),timeout=.3):pass
  except OSError:
   subprocess.run(['/usr/bin/open','-g','-j',str(bridge)],capture_output=True,timeout=5)
   time.sleep(1)
  yield 'http://127.0.0.1:8782','Bluetooth'
def loop():
 guard=(WORK/'phone-sync.lock').open('a')
 try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:guard.close();return
 while True:
  try:
   if not CONFIG.exists():time.sleep(10);continue
   queue_pending();cfg=json.loads(CONFIG.read_text());connected=False
   for base,transport in candidates(cfg):
    try:
     with request(base,cfg['token'],'/list') as response:items=json.load(response)
     connected=True;state.update(connected=True,transport=transport,message='Телефон подключён · '+transport)
     for item in items:
      if not re.fullmatch(r'lecture-[0-9-]+\.wav|board-[0-9]{13}-[a-f0-9]{32}\.jpg',item.get('name','')):continue
      state['message']='Переношу запись · '+transport;atomic(STATUS,state)
      import_one(item,base,cfg['token']);state['imported']+=1
     state['message']='Всё перенесено · '+transport
     break
    except Exception:continue
   if not connected:state.update(connected=False,message='Ожидаю телефон · общая Wi-Fi сеть, Bluetooth или USB')
  except Exception:state.update(connected=False,message='Перенос ожидает подключения. Записи остаются на телефоне.')
  atomic(STATUS,state);time.sleep(10)
def start():
 global started
 if not started:started=True;threading.Thread(target=loop,daemon=True,name='Phone wireless import').start()
if __name__=='__main__':loop()
