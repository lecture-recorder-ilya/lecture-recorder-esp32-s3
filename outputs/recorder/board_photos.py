import fcntl,json,math,os,re,shutil,struct,subprocess,threading,time,wave
from pathlib import Path
from urllib.request import urlopen
import study_store as store
from board_match import locate,start_ms

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1]
STATE={'processing':False,'message':'Фото с телефона появятся после переноса'};STARTED=False
NAME=re.compile(r'board-([0-9]{13})-([a-f0-9]{32})\.jpg')

def folder(root=None):return (root or ROOT)/'study/board-inbox'
def job_path(ident,root=None):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('Некорректное фото')
    return folder(root)/(ident+'.json')
def image(ident,root=None):
    return job_path(ident,root).with_suffix('.jpg')
def save_job(job):
    import phone_sync as sync
    with store.transaction():
        path=job_path(job['id']);current=store.read(path)
        if current.get('matching',{}).get('method')=='manual':job['matching']=current['matching']
        sync.atomic(path,job)
def validate_jpeg(path):
    data=path.read_bytes()
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):raise ValueError('Неполное JPEG фото')
    offset=2
    while offset+4<=len(data):
        if data[offset]!=255:break
        marker=data[offset+1];offset+=2
        if marker==255:offset-=1;continue
        if marker in (0xda,0xd9):break
        length=struct.unpack('>H',data[offset:offset+2])[0]
        if length<2 or offset+length>len(data):break
        if marker in (0xc0,0xc1,0xc2):
            if length<8:break
            height,width=struct.unpack('>HH',data[offset+3:offset+7])
            if not 1<=width<=8192 or not 1<=height<=8192 or width*height>40_000_000:raise ValueError('Некорректный размер фото')
            return
        offset+=length
    raise ValueError('JPEG не содержит корректного изображения')

def import_one(item,base,token,root=None):
    import phone_sync as sync
    root=root or ROOT;match=NAME.fullmatch(item.get('name',''));size=item.get('bytes');sha=item.get('sha256')
    if not match or type(size) is not int or not 128<=size<=12*1024*1024 or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('Некорректные сведения фото')
    captured,ident=int(match[1]),match[2];dest=folder(root);dest.mkdir(parents=True,exist_ok=True);target=image(ident,root);path=job_path(ident,root)
    old=store.read(path)
    if old and old.get('sha256')!=sha:raise ValueError('На Mac другое фото с таким идентификатором; телефон сохранён')
    if target.exists():
        if target.stat().st_size!=size or sync.digest(target)!=sha:raise ValueError('Копия фото отличается; телефон сохранён')
    else:
        if shutil.disk_usage(dest).free<size+100*1024*1024:raise OSError('Недостаточно места; фото сохранено на телефоне')
        temp=target.with_suffix('.jpg.part');count=0
        with sync.request(base,token,'/file/'+item['name']) as response,temp.open('wb') as out:
            for chunk in iter(lambda:response.read(65536),b''):
                count+=len(chunk)
                if count>size:raise ValueError('Размер фото изменился')
                out.write(chunk)
            out.flush();os.fsync(out.fileno())
        if count!=size or sync.digest(temp)!=sha:raise ValueError('Фото перенесено не полностью; телефон сохранён')
        validate_jpeg(temp);os.link(temp,target);temp.unlink();sync.sync_dir(dest)
    validate_jpeg(target)
    if not old:
        old={'id':ident,'name':item['name'],'sha256':sha,'bytes':size,'captured_ms':captured,'state':'queued','source':'android','updated':time.time()}
        source=item.get('source_recording');offset=item.get('offset_seconds')
        if isinstance(source,str) and re.fullmatch(r'lecture-[0-9-]+\.wav',source) and type(offset) in (int,float) and math.isfinite(offset) and 0<=offset<=36*3600:old.update(source_recording=source,offset_seconds=offset)
        uncertainty=item.get('time_uncertainty_seconds',20)
        if type(uncertainty) in (int,float) and math.isfinite(uncertainty):old['time_uncertainty_seconds']=min(600,max(2,uncertainty))
        sync.atomic(path,old)
    with target.open('rb') as local:os.fsync(local.fileno())
    sync.sync_dir(dest)
    with sync.request(base,token,'/ack',{'name':item['name'],'sha256':sha}) as response:
        if not json.load(response).get('ok'):raise ValueError('Телефон не подтвердил перенос фото')
    return item['name']

def lectures(status=None):
    status=status or {};output=[]
    for path in (ROOT/'recordings').glob('lecture-*.wav'):
        if len(store.notes(path.name).get('parts',[]))>1:continue
        try:
            if status.get('recording') and status.get('file')==path.name:duration=float(status['seconds'])
            else:
                with wave.open(str(path)) as stream:duration=stream.getnframes()/stream.getframerate()
            started=start_ms(path.name,store.read(path.with_suffix('.phone.json')))
            report=store.read(ROOT/'analysis'/(path.stem+'.json')) or store.read(ROOT/'analysis'/(path.stem+'.live.json'))
            output.append({'file':path.name,'duration':duration,'started_ms':started,'segments':report.get('segments',[])})
        except (OSError,ValueError,wave.Error):continue
    return output

def attach(job,match,manual=False):
    import phone_sync as sync
    source=image(job['id']);dest=ROOT/'study/photos'/(job['id']+'.jpg');dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():os.link(source,dest);sync.sync_dir(dest.parent)
    with store.transaction():
        current=store.read(job_path(job['id']))
        if current.get('matching',{}).get('method')=='manual' and not manual:match=current['matching']
        if not job.get('analysis') and current.get('analysis'):job['analysis']=current['analysis']
        name=match['file'];data=store.notes(name);photos=data.setdefault('photos',[]);old=next((p for p in photos if p['id']==dest.name),None)
        if old and not manual and old.get('matching',{}).get('method')=='manual':match=dict(match,start=old['start'],method='manual')
        item={'id':dest.name,'start':match['start'],'source':'phone-board','board_id':job['id'],'analysis':job.get('analysis',{}),'matching':match,'captured_ms':job['captured_ms']}
        if old:old.update(item)
        else:photos.append(item)
        photos.sort(key=lambda p:p['start']);note=store.note_path(name);store.save(note,data)
        with note.open('rb') as saved:os.fsync(saved.fileno())
        sync.sync_dir(note.parent)
        job.update(state='linked',matching=match,updated=time.time());sync.atomic(job_path(job['id']),job)
    return job

def assign(ident,name,start,active=None):
    import phone_sync as sync
    path=job_path(ident);job=store.read(path)
    if not job:raise ValueError('Фото не найдено')
    store.audio(name);limit=active['seconds'] if active and active.get('recording') and active.get('file')==name else store.duration(name);start=store.timestamp(start,limit)
    match={'file':name,'start':start,'method':'manual'}
    with store.transaction():
        job=store.read(path);previous=job.get('matching',{}).get('file');job['matching']=match;sync.atomic(path,job)
    if previous and previous!=name:
        with store.transaction():
            data=store.notes(previous);data['photos']=[p for p in data.get('photos',[]) if p.get('board_id')!=ident];store.save(store.note_path(previous),data)
    return attach(job,match,manual=True)

def public():
    jobs=sorted((store.read(p) for p in folder().glob('*.json')),key=lambda j:j.get('captured_ms',0),reverse=True)
    return dict(STATE,model_ready=(PROJECT/'work/models/board-vision-manifest.json').exists(),photos=[{k:j.get(k) for k in ('id','state','captured_ms','analysis','matching','error','updated')} for j in jobs[:100]])

def process(job,status=None):
    import phone_sync as sync
    path=job_path(job['id'])
    new_analysis=not job.get('analysis')
    if new_analysis:
        python=PROJECT/'work/vision-env/bin/python'
        if not python.exists() or not (PROJECT/'work/models/board-vision-manifest.json').exists():return
        if time.time()-job.get('last_attempt',0)<300:return
        with (PROJECT/'work/lecture-inference.lock').open('a') as guard:
            try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            job.update(state='reading',last_attempt=time.time(),updated=time.time());save_job(job);STATE.update(processing=True,message='Читаю фото доски на Mac…')
            try:
                env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
                result=subprocess.run([str(python),str(ROOT/'board_vision.py'),str(image(job['id']))],capture_output=True,text=True,timeout=900,env=env,check=True)
                job['analysis']=json.loads(result.stdout);job.pop('error',None)
            except (OSError,ValueError,subprocess.SubprocessError) as error:
                diagnostic=str(error)+'\n'+str(getattr(error,'stderr','') or '')
                (PROJECT/'work/board-vision-last-error.log').write_text(diagnostic[-10000:])
                job.update(state='error',error='Не удалось прочитать фото; снимок сохранён',updated=time.time());save_job(job);STATE.update(processing=False,message=job['error']);return
            finally:STATE['processing']=False
    if job.get('matching',{}).get('method')=='manual':attach(job,job['matching']);return
    match=locate(job,lectures(status))
    if match:
        if new_analysis or job.get('matching')!=match or job.get('state')!='linked':attach(job,match)
    elif new_analysis or job.get('state')!='waiting_lecture':job.update(state='waiting_lecture',updated=time.time());save_job(job)

def loop():
    (PROJECT/'work').mkdir(exist_ok=True)
    with (PROJECT/'work/board-photos.lock').open('a') as guard:
        try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        while True:
            try:
                try:
                    with urlopen('http://127.0.0.1:8765/status',timeout=3) as response:status=json.load(response)
                except OSError:status={}
                for path in sorted(folder().glob('*.json')):
                    job=store.read(path)
                    if not job or job.get('analysis') and job.get('state')=='linked' and job.get('matching',{}).get('method')=='manual':continue
                    if job.get('state')=='linked' and '+content' in job.get('matching',{}).get('method',''):continue
                    process(job,status)
                STATE.update(message='Фото доски разобраны на Mac')
            except Exception:STATE.update(processing=False,message='Фото сохранены; обработка продолжится автоматически')
            time.sleep(10)

def start():
    global STARTED
    if not STARTED:STARTED=True;threading.Thread(target=loop,daemon=True,name='Local board photo analysis').start()
