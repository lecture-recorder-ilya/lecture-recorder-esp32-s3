"""Persistent study metadata. Original microphone WAVs are never rewritten."""
import contextlib
import fcntl
import json
import math
import os
import re
import threading
import uuid
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock()

def read(path, default=None):
    try:return json.loads(path.read_text())
    except (OSError, ValueError):return {} if default is None else default

def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)

@contextlib.contextmanager
def transaction():
    with LOCK:
        (ROOT/'study').mkdir(exist_ok=True)
        with (ROOT/'study/store.lock').open('a') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX)
            yield

def audio(name):
    if not isinstance(name,str) or Path(name).name!=name or re.search(r'[/\\\x00]',name) or not name.endswith('.wav'):
        raise ValueError('Некорректное имя записи')
    path=ROOT/'recordings'/name
    if not path.is_file():raise ValueError('Запись не найдена')
    return path

def note_path(name):
    audio(name)
    return ROOT/'study'/(Path(name).stem+'.notes.json')

def notes(name):return read(note_path(name),{'markers':[],'photos':[]})

def duration(name):
    with wave.open(str(audio(name))) as wav:return wav.getnframes()/wav.getframerate()

def timestamp(value, limit):
    if isinstance(value,bool):raise ValueError('Некорректное время')
    value=float(value)
    if not math.isfinite(value) or not 0<=value<=limit+.1:raise ValueError('Время вне записи')
    return round(value,2)

def marker(body, active=None):
    name=body.get('file');limit=active['seconds'] if active and active.get('recording') and active.get('file')==name else duration(name)
    start=timestamp(body.get('start',0),limit)
    title=body.get('title','')
    if not isinstance(title,str):raise ValueError('Некорректное название')
    with transaction():
        data=notes(name);items=data.setdefault('markers',[])
        ident=body.get('id')
        item=next((v for v in items if v['id']==ident),None)
        if ident and not item:raise ValueError('Метка не найдена')
        if not item:
            item={'id':uuid.uuid4().hex};items.append(item)
        item.update(start=start,title=title[:500])
        items.sort(key=lambda v:v['start']);save(note_path(name),data)
    return data

def add_photo(name, start, data, active=None):
    limit=active['seconds'] if active and active.get('recording') and active.get('file')==name else duration(name)
    start=timestamp(start,limit)
    if len(data)>12*1024*1024:raise ValueError('Фото больше 12 МБ')
    if data.startswith(b'\xff\xd8\xff'):suffix='.jpg'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):suffix='.png'
    elif data.startswith(b'RIFF') and data[8:12]==b'WEBP':suffix='.webp'
    else:raise ValueError('Выбери JPEG, PNG или WebP')
    ident=uuid.uuid4().hex+suffix
    with transaction():
        folder=ROOT/'study/photos';folder.mkdir(parents=True,exist_ok=True)
        (folder/ident).write_bytes(data)
        meta=notes(name);meta.setdefault('photos',[]).append({'id':ident,'start':start})
        save(note_path(name),meta)
    return meta

def photo_time(body,active=None):
    name=body.get('file')
    limit=active['seconds'] if active and active.get('recording') and active.get('file')==name else duration(name)
    start=timestamp(body.get('start'),limit)
    with transaction():
        data=notes(name)
        photo=next((v for v in data.get('photos',[]) if v['id']==body.get('id')),None)
        if not photo:raise ValueError('Фото не найдено')
        photo['start']=start;photo.setdefault('matching',{})['method']='manual';save(note_path(name),data)
    return data

def overrides():return read(ROOT/'study/folders.json')

def folder_name(value):
    if not isinstance(value,str) or not value.strip() or len(value)>180 or len(value.encode('utf-8'))>240 or value in ('.','..') or re.search(r'[/\\\x00]',value):
        raise ValueError('Некорректное название папки')
    return value.strip()

def report_aliases(name,folder,remove=False):
    directory=ROOT/'lessons'/folder_name(folder)
    if not directory.exists():return
    stem=Path(name).stem
    sources=[ROOT/'analysis'/(stem+suffix) for suffix in ('.json','.md','.transcript.json')]
    sources.extend([ROOT/'study'/(stem+'.notes.json'),(ROOT/'recordings'/name).with_suffix('.gaps.json')])
    for source in sources:
        target=directory/source.name
        if remove:
            if target.is_symlink() and target.resolve()==source.resolve():target.unlink()
        elif source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(os.path.relpath(source,directory))

def move(name, folder, meta=None):
    source=audio(name);folder=folder_name(folder)
    with transaction():
        values=overrides();old=values.get(name,{}).get('folder') or (meta or {}).get('folder')
        target=ROOT/'lessons'/folder;target.mkdir(parents=True,exist_ok=True)
        destination=target/name
        if destination.exists() and not os.path.samefile(source,destination):raise ValueError('В папке уже есть другой файл с таким именем')
        if not destination.exists():os.link(source,destination)
        value=dict(meta or {},folder=folder,label=folder,source='manual')
        values[name]=value;save(ROOT/'study/folders.json',values)
        report_aliases(name,folder)
        if old and old!=folder:
            oldpath=ROOT/'lessons'/folder_name(old)/name
            if oldpath.exists() and os.path.samefile(source,oldpath):oldpath.unlink()
            report_aliases(name,old,remove=True)
        refresh_manifest(folder,value)
        if old and old!=folder:refresh_manifest(old,dict(meta or {}))
    return value

def refresh_manifest(folder, meta):
    path=ROOT/'lessons'/folder_name(folder)
    if not path.exists():return
    save(path/'занятие.json',dict(meta,recordings=sorted(p.name for p in path.glob('*.wav'))))

def enrich(status):
    changed=overrides();teachers=read(ROOT/'study/teachers.json');lessons=status.setdefault('lessons',{})
    for name in status.get('files',[]):
        base=lessons.get(name) or {};meta=dict(changed.get(name) or base)
        result=read(ROOT/'analysis'/(Path(name).stem+'.json'))
        key=meta.get('folder',name)
        # An explicitly named teacher is persisted once; schedule/manual names win.
        if not meta.get('teacher') and result.get('teacher') and result.get('evidence',{}).get('teacher'):
            with transaction():
                teachers=read(ROOT/'study/teachers.json')
                if key not in teachers:
                    teachers[key]={'name':result['teacher'],'quote':result['evidence']['teacher'],'file':name}
                    save(ROOT/'study/teachers.json',teachers)
        if not meta.get('teacher') and key in teachers:
            meta['teacher']=teachers[key]['name'];meta['teacher_source']='speech';meta['teacher_quote']=teachers[key]['quote']
        meta.setdefault('teachers',[])
        meta['topic']=result.get('topic') or meta.get('title') or result.get('subject') or meta.get('subject') or 'Тема пока не определена'
        meta['overview']=result.get('overview') or ''
        meta['key_points']=(result.get('summary') or [])[:3]
        meta['has_summary']=bool(result.get('overview') or result.get('summary'))
        draft=read(ROOT/'analysis'/(Path(name).stem+'.live.json'))
        transcript=read(ROOT/'analysis'/(Path(name).stem+'.transcript.json'))
        meta['has_draft']=bool(draft.get('segments') or transcript.get('segments'))
        meta['draft_updated']=draft.get('updated',0)
        meta['material_revision']=[p.stat().st_mtime_ns if p.exists() else 0 for p in (ROOT/'analysis'/(Path(name).stem+'.json'),ROOT/'analysis'/(Path(name).stem+'.live.json'),ROOT/'analysis'/(Path(name).stem+'.transcript.json'),ROOT/'study'/(Path(name).stem+'.notes.json'))]
        record_notes=notes(name)
        meta['markers']=record_notes.get('markers',[])
        meta['photos']=record_notes.get('photos',[])
        if record_notes.get('parts'):
            meta['merged_parts']=record_notes['parts']
            meta['source_records']=record_notes.get('source_records',[])
            if not result.get('topic'):meta['topic']=(meta.get('subject') or 'Занятие')+' · занятие целиком'
            if meta.get('start') and meta.get('folder')==f"{meta['date']} {meta['start'].replace(':','-')} — {meta.get('subject')} — {meta.get('type')}":
                meta['label']=f"{meta['date']} · {meta['start']}–{meta['end']} · {meta['subject']} · {meta['type']}"
        if name in changed:
            report_aliases(name,meta['folder'])
            # The old recorder may still create its original schedule hardlink.
            old=base.get('folder')
            if old and old!=meta.get('folder'):
                oldpath=ROOT/'lessons'/folder_name(old)/name
                if oldpath.exists() and os.path.samefile(audio(name),oldpath):oldpath.unlink()
                report_aliases(name,old,remove=True)
        lessons[name]=meta
    status['study_folders']=sorted(set(v.get('folder') for v in lessons.values() if v.get('folder')))
    return status

def merged(body, status):
    names=body.get('files')
    if not isinstance(names,list) or not 2<=len(names)<=30 or len(set(names))!=len(names):raise ValueError('Выбери от 2 до 30 разных отрывков')
    originals=list(names)
    original_notes={n:notes(n) for n in originals}
    first=(status.get('lessons') or {}).get(names[0]) or {}
    sources=list(dict.fromkeys(originals+[part for n in originals for part in notes(n).get('source_records',[])]))
    if body.get('chronological'):
        names=[part['file'] for n in names for part in (notes(n).get('parts') or [{'file':n}])]
        if len(set(names))!=len(names):raise ValueError('Этот отрывок уже входит в общую запись')
        if len(names)>200:raise ValueError('Слишком много отрывков для одной записи')
        names.sort()
        sources=list(dict.fromkeys(sources+names))
    if status.get('recording') and status.get('file') in names:raise ValueError('Дождись окончания выбранной записи')
    paths=[audio(n) for n in names]
    name='lecture-'+datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d-%H-%M-%S-%f')+'.wav'
    destination=ROOT/'recordings'/name;temporary=destination.with_suffix('.part')
    offsets=[];total=0;segments=[];complete=True;combined={'markers':[],'photos':[]};gaps=[]
    try:
        with wave.open(str(temporary),'wb') as out:
            out.setparams((1,2,16000,0,'NONE','not compressed'))
            for source in paths:
                with wave.open(str(source)) as inp:
                    if (inp.getnchannels(),inp.getsampwidth(),inp.getframerate())!=(1,2,16000):raise ValueError('Отрывки должны быть PCM16, моно, 16 кГц')
                    report=read(ROOT/'analysis'/(source.stem+'.json'))
                    meta=(status.get('lessons') or {}).get(source.name) or {}
                    offset=total/16000;offsets.append({'file':source.name,'start':offset,'duration':inp.getnframes()/16000,
                        'topic':report.get('topic') or report.get('subject') or meta.get('topic') or meta.get('subject') or 'Отрывок занятия',
                        'summary':report.get('overview') or ' '.join(str(v) for v in report.get('summary',[])[:3])})
                    while True:
                        pcm=inp.readframes(16000*30)
                        if not pcm:break
                        out.writeframesraw(pcm);total+=len(pcm)//2
                cache=read(ROOT/'analysis'/(source.stem+'.transcript.json'))
                complete=complete and bool(cache.get('complete',False))
                for segment in cache.get('segments',[]):
                    segments.append(dict(segment,id=len(segments),start=segment['start']+offset,end=segment['end']+offset))
                for gap in read(source.with_suffix('.gaps.json'),[]):gaps.append(dict(gap,start=gap['start']+offset))
        new_offsets={part['file']:part['start'] for part in offsets}
        for original in originals:
            annotation_notes=original_notes[original]
            old_parts=annotation_notes.get('parts') if body.get('chronological') else None
            for kind in combined:
                for item in annotation_notes.get(kind,[]):
                    leaf=original;local=item['start']
                    if old_parts:
                        part=next((v for v in reversed(old_parts) if v['start']<=local),old_parts[0])
                        leaf=part['file'];local-=part['start']
                    combined[kind].append(dict(item,id=uuid.uuid4().hex if kind=='markers' else item['id'],start=new_offsets[leaf]+local))
        os.replace(temporary,destination)
        if complete:
            save(ROOT/'analysis'/(destination.stem+'.transcript.json'),{'segments':segments,'complete':True,'completed_frames':total,'duration':total/16000,'engine':'Whisper · объединённые расшифровки'})
        save(note_path(name),dict(combined,parts=offsets,source_records=sources))
        if gaps:save(destination.with_suffix('.gaps.json'),gaps)
        move(name,body.get('folder') or first.get('folder') or 'Объединённые записи',first)
        return {'file':name,'parts':offsets,'duration':total/16000}
    finally:
        if temporary.exists():temporary.unlink()
