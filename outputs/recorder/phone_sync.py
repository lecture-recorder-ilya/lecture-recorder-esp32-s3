import fcntl,hashlib,hmac,json,os,re,secrets,shutil,socket,subprocess,threading,time,wave
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import URLError,HTTPError
from http.client import IncompleteRead

ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent.parent/'work'
CONFIG=WORK/'phone-sync.json';LEDGER=WORK/'phone-imports.json';FILES=ROOT/'recordings'
state={'connected':False,'message':'Ожидаю телефон · Wi-Fi / Bluetooth / USB','imported':0};started=False
STATUS=WORK/'phone-sync-status.json'
MAX_NOTE_BYTES = 2 * 1024 * 1024
WAKE=threading.Event()
REVOKED=set()

def revoke(token):
 REVOKED.add(token)
 WAKE.set()
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
def auth_headers(token,method,route,body=b'',extra=None,body_digest=None):
 headers=dict(extra or {});stamp=str(int(time.time()));nonce=secrets.token_hex(16)
 signed='\n'.join((method,route,stamp,nonce,headers.get('Range',''),body_digest or hashlib.sha256(body).hexdigest()))
 headers.update({'X-Lecture-Time':stamp,'X-Lecture-Nonce':nonce,'X-Lecture-Signature':hmac.new(token.encode(),signed.encode(),hashlib.sha256).hexdigest(),'Content-Type':'application/json'})
 return headers
def encode_body(route, data):
 body = json.dumps(data).encode()
 if route == '/notes' and len(body) > MAX_NOTE_BYTES:
  # Keep the digest of documents already accepted by earlier phones.
  body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
  if len(body) > MAX_NOTE_BYTES:
   raise ValueError('Текст слишком большой для телефона')
 return body

def request(base,token,route,data=None,extra=None,timeout=None):
 if token in REVOKED:raise PermissionError('Сопряжение с телефоном удалено')
 body=encode_body(route,data) if data is not None else None
 headers=auth_headers(token,'POST' if body is not None else 'GET',route,body or b'',extra)
 return urlopen(Request(base+route,data=body,headers=headers),timeout=timeout if timeout is not None else 300 if route == '/notes' else 60)
def request_file(base,token,route,path,expected_digest=None):
 if token in REVOKED:raise PermissionError('Сопряжение с телефоном удалено')
 with path.open('rb') as body:
  size=os.fstat(body.fileno()).st_size;sha=hashlib.sha256()
  if not 0<size<=80*1024*1024:raise ValueError('Недопустимый размер APK')
  for block in iter(lambda:body.read(65536),b''):sha.update(block)
  digest=sha.hexdigest()
  if expected_digest is not None and digest!=expected_digest:raise ValueError('APK в кэше изменился')
  body.seek(0)
  headers=auth_headers(token,'POST',route,body_digest=digest)
  headers.update({'Content-Type':'application/vnd.android.package-archive','Content-Length':str(size),'X-Lecture-Body-SHA256':digest})
  with urlopen(Request(base+route,data=body,headers=headers,method='POST'),timeout=90) as response:
   return json.loads(response.read(8192))
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
def source_id(token, device_id=None):
 if isinstance(device_id,str) and re.fullmatch(r'[a-f0-9]{32}',device_id):
  return device_id
 return hmac.new(token.encode(), b'ClipMic import source', hashlib.sha256).hexdigest()

@contextmanager
def ledger_lock(path):
 with path.with_suffix(path.suffix+'.lock').open('a') as guard:
  fcntl.flock(guard,fcntl.LOCK_EX)
  yield

def local_recording_name(remote, sha, size, files, ledger):
 for name,entry in ledger.items():
  if entry.get('source_name',name)==remote and entry.get('sha256')==sha:
   return name
 target=files/remote
 if target.exists():
  if target.stat().st_size==size and digest(target)==sha:return remote
  try:validate(target)
  except (wave.Error,EOFError,ValueError) as error:
   raise ValueError('На Mac уже есть другой файл с этим именем; телефон сохранён') from error
  occupied=True
 else:
  try:partial=json.loads((files/(remote+'.phone-part.json')).read_text())
  except (OSError,ValueError):partial={}
  occupied=remote in ledger or bool(partial and partial.get('sha256')!=sha)
 if not occupied:return remote
 # Оставляем дату, время и исходные микросекунды доступными старым парсерам.
 return remote[:-4]+'-'+str(int(sha,16))+'.wav'

def import_one(item,base,token,files=FILES,ledger_path=LEDGER,device_id=None):
 if re.fullmatch(r'board-[0-9]{13}-[a-f0-9]{32}\.jpg',item.get('name','')):
  import board_photos
  return board_photos.import_one(item,base,token,root=files.parent)
 with ledger_lock(ledger_path):
  name=import_audio(item,base,token,files,ledger_path,source_id(token,device_id))
 queue_pending(ledger_path)
 return name

def import_audio(item,base,token,files,ledger_path,device):
 name=item.get('name');size=item.get('bytes');sha=item.get('sha256')
 if not isinstance(name,str) or not re.fullmatch(r'lecture-[0-9-]+\.wav',name) or type(size) is not int or not 44<=size<=4_200_000_044 or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('Некорректные сведения записи')
 files.mkdir(exist_ok=True);ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
 remote=name
 name=local_recording_name(remote,sha,size,files,ledger)
 target=files/name
 temp=files/(name+'.phone-part');resume_meta=files/(name+'.phone-part.json')
 if target.exists():
  if target.stat().st_size!=size or digest(target)!=sha:raise ValueError('На Mac уже есть другая запись с этим именем; телефон сохранён')
 else:
  identity={'sha256':sha,'bytes':size}
  try:resume_ok=json.loads(resume_meta.read_text())==identity
  except (OSError,ValueError):resume_ok=False
  if not resume_ok or (temp.exists() and temp.stat().st_size>size):temp.unlink(missing_ok=True)
  count=temp.stat().st_size if temp.exists() else 0
  if count<size:
   if shutil.disk_usage(files).free < size-count+100*1024*1024:
    raise OSError('На Mac недостаточно места; телефон сохранён')
   atomic(resume_meta,identity)
   with request(base,token,'/file/'+remote,extra={'Range':'bytes='+str(count)+'-'} if count else None) as response:
    if count and response.status!=206:count=0
    elif count and response.headers.get('Content-Range')!='bytes '+str(count)+'-'+str(size-1)+'/'+str(size):raise ValueError('Некорректное продолжение копии')
    with temp.open('ab' if count else 'wb') as f:
     try:
      for data in iter(lambda:response.read(65536),b''):
       count+=len(data)
       if count>size:raise ValueError('Размер записи изменился')
       f.write(data)
     finally:f.flush();os.fsync(f.fileno())
   if count!=size:raise ConnectionError('Перенос прервался; продолжу при подключении')
  if digest(temp)!=sha:
   temp.unlink(missing_ok=True);resume_meta.unlink(missing_ok=True);raise ValueError('Копия не совпала; телефон сохранён')
  validate(temp)
  os.link(temp,target)

 validate(target)
 # A restart can leave the partial linked to the already verified library file.
 if temp.exists() and temp.samefile(target):temp.unlink()
 if not temp.exists():resume_meta.unlink(missing_ok=True)
 with target.open('rb') as local:os.fsync(local.fileno())
 sync_dir(files)
 if name not in ledger:
  gaps=[{'start':float(g['start']),'duration':float(g['seconds'])} for g in item.get('gaps',[])]
  if gaps:atomic(target.with_suffix('.gaps.json'),gaps)
  atomic(target.with_suffix('.phone.json'),dict(source='android',source_name=remote,sha256=sha,started_ms=item.get('started_ms'),error=item.get('error','')))
  import lesson_schedule
  if item.get('lesson_decided') is True:
   lesson = item.get('lesson')
   if lesson is not None and not isinstance(lesson, dict):raise ValueError('Некорректные сведения о паре')
   lesson_schedule.assign_recording(name, lesson)
  else:
   lesson_schedule.organize(name)
  if item.get('imported') is True:
   import study_store
   from datetime import datetime
   from zoneinfo import ZoneInfo
   stamp=item.get('started_ms')
   moment=datetime.fromtimestamp(stamp/1000,ZoneInfo('Europe/Moscow')) if type(stamp) in (int,float) else datetime.now(ZoneInfo('Europe/Moscow'))
   meta={'date':moment.strftime('%Y-%m-%d'),'start':moment.strftime('%H:%M'),'end':'','type':'Лекция','subject':'Загруженная запись','title':str(item.get('title') or item.get('original_name') or 'Запись с телефона')[:160],'imported':True}
   study_store.move(name,meta['date']+' — Загруженные записи',meta)
  ledger[name]={'sha256':sha,'bytes':size,'queued':False}
 entry=ledger[name]
 if entry.get('sha256')!=sha:raise ValueError('Контрольная сумма не совпала с журналом импорта')
 if device not in entry.get('devices',[]):
  for other,previous in ledger.items():
   if other!=name and previous.get('source_name',other)==remote and device in previous.get('devices',[]):
    previous['devices'].remove(device)
  entry.setdefault('devices',[]).append(device)
  entry['source_name']=remote
  atomic(ledger_path,ledger)
 # A failed acknowledgement is retried against the already verified local copy.
 with request(base,token,'/ack',{'name':remote,'sha256':sha}) as r:
  if not json.load(r).get('ok'):raise ValueError('Телефон не подтвердил очистку')
 return name
def queue_pending(ledger_path=LEDGER):
 with ledger_lock(ledger_path):
  _queue_pending(ledger_path)

def _queue_pending(ledger_path):
 ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
 for name,entry in ledger.items():
  if entry.get('queued'):continue
  try:
   with urlopen(Request('http://127.0.0.1:8765/analyze',data=json.dumps({'file':name,'wait_models':True}).encode(),headers={'Content-Type':'application/json'}),timeout=10) as r:json.load(r)
   ledger[name]['queued']=True;atomic(ledger_path,ledger)
  except OSError:pass
def candidates(cfg):
 token=cfg['token'];adb=shutil.which('adb') or '/opt/homebrew/bin/adb'
 def command(args):return subprocess.run([adb,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,check=True).stdout
 try:
  if Path(adb).exists():
   serials=[line.split()[0] for line in command(['devices']).decode().splitlines() if len(line.split())==2 and line.split()[1]=='device'][:8]
   if cfg.get('serial') in serials:serials.remove(cfg['serial']);serials.insert(0,cfg['serial'])
   for serial in serials:
    try:
     command(['-s',serial,'forward','tcp:8781','tcp:8780']);base='http://127.0.0.1:8781'
     try:
      with request(base,token,'/list',timeout=2) as response:json.load(response)
     except HTTPError:continue
     except OSError:
      command(['-s',serial,'shell','am','start','-n','ru.ilya.lecturerecorder/.MainActivity'])
      time.sleep(.5)
      with request(base,token,'/list',timeout=2) as response:json.load(response)
     yield base,'USB'
     break
    except (OSError,ValueError,subprocess.SubprocessError):continue
 except (OSError,ValueError,subprocess.SubprocessError):pass
 saved=cfg.get('address')
 if isinstance(saved,str):
  try:
   import ipaddress
   saved=str(ipaddress.IPv4Address(saved))
   yield 'http://'+saved+':8780','Wi-Fi'
  except ValueError:pass
 base=discover_wifi(token)
 if base and base!='http://'+str(saved)+':8780':yield base,'Wi-Fi'
 # Bluetooth helper is a native accessory app with the macOS Bluetooth usage description.
 bridge=ROOT.parent/'Синхронизация Bluetooth.app'
 if bridge.exists():
  try:
   with socket.create_connection(('127.0.0.1',8782),timeout=.3):pass
  except OSError:
   subprocess.run(['/usr/bin/open','-g','-j',str(bridge)],capture_output=True,timeout=5)
   time.sleep(1)
  yield 'http://127.0.0.1:8782','Bluetooth'
class RetryQueue:
 def __init__(self):self.entries={}
 def key(self,item):return item.get('name'),item.get('sha256')
 def waiting(self,item,now):return self.entries.get(self.key(item),{}).get('after',0)>now
 def failed(self,item,error,now):
  key=self.key(item);attempts=self.entries.get(key,{}).get('attempts',0)+1
  self.entries[key]={'attempts':attempts,'after':now+min(300,10*2**min(attempts-1,5)),'message':str(error)[:160]}
 def succeeded(self,item):self.entries.pop(self.key(item),None)
 def retain(self,items):
  active={self.key(item) for item in items}
  self.entries={key:value for key,value in self.entries.items() if key in active}

def connection_error(error):
 if isinstance(error,HTTPError):return error.code in (401,403,408,429) or error.code>=500
 return isinstance(error,(URLError,ConnectionError,TimeoutError,IncompleteRead))

def sync_once(cfg,retries,now=None):
 from phone_notes import push
 fixed_time=now
 now=time.monotonic() if now is None else now
 token=cfg.get('token')
 if not isinstance(token,str) or not token:raise ValueError('Сначала настрой соединение телефона с Mac')
 last_error=None
 for base,transport in candidates(cfg):
  try:
   with request(base,token,'/list') as response:items=json.load(response)
   if not isinstance(items,list):raise ValueError('Телефон вернул некорректный список')
   items=[item for item in items if isinstance(item,dict) and isinstance(item.get('name'),str) and re.fullmatch(r'lecture-[0-9-]+\.wav|board-[0-9]{13}-[a-f0-9]{32}\.jpg',item['name']) and isinstance(item.get('sha256'),str)]
   retries.retain(items);errors=[];copied=0
   state.update(connected=True,transport=transport,pending=len(items),failed=0,message='Телефон подключён · '+transport)
   try:push(base,token,device_id=cfg.get('device_id'),offered=items)
   except Exception as error:
    if connection_error(error):raise
    errors.append('Текст: '+str(error)[:120])
   for item in items:
    if retries.waiting(item,now):
     errors.append(item['name']+': '+retries.entries[retries.key(item)]['message']);continue
    state['message']='Переношу '+item['name']+' · '+transport;atomic(STATUS,state)
    try:import_one(item,base,token,FILES,LEDGER,cfg.get('device_id'))
    except Exception as error:
     if connection_error(error):raise
     retries.failed(item,error,time.monotonic() if fixed_time is None else now)
     errors.append(item['name']+': '+str(error)[:120]);continue
    retries.succeeded(item);state['imported']+=1;copied+=1
   if copied:
    try:push(base,token,device_id=cfg.get('device_id'),offered=items)
    except Exception as error:
     if connection_error(error):raise
     errors.append('Текст: '+str(error)[:120])
   try:
    from phone_updates import push as push_update
    push_update(base,token)
   except Exception:
    state['update_message']='Обновление телефона повторю при следующем подключении'
   state.update(pending=len(items)-copied,failed=len(retries.entries),errors=list(dict.fromkeys(errors))[:10])
   state['message']=(('Ожидают переноса: '+str(state['pending'])+' · ' if state['pending'] else '')+'Повторю автоматически · '+errors[0]) if errors else 'Всё перенесено · '+transport
   return True
  except Exception as error:last_error=error
 state.update(connected=False,pending=0,failed=len(retries.entries),errors=[],message='Ожидаю телефон · общая Wi-Fi сеть, Bluetooth или USB'+(' · '+str(last_error)[:120] if last_error else ''))
 return False

def loop():
 WORK.mkdir(parents=True,exist_ok=True)
 guard=(WORK/'phone-sync.lock').open('a')
 try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:guard.close();return
 retries=RetryQueue()
 while True:
  try:
   if not CONFIG.exists():
    state.update(connected=False,message='Телефон не подключён. Добавь его в настройках Mac.');atomic(STATUS,state)
    WAKE.wait(10);WAKE.clear();continue
   queue_pending();cfg=json.loads(CONFIG.read_text())
   sync_once(cfg,retries)
  except Exception as error:state.update(connected=False,message='Перенос ожидает подключения · '+str(error)[:120])
  atomic(STATUS,state);WAKE.wait(10);WAKE.clear()
def start():
 global started
 if not started:started=True;threading.Thread(target=loop,daemon=True,name='Phone wireless import').start()
if __name__=='__main__':loop()
