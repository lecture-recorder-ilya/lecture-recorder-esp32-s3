"""Schedule metadata is separate from AI conclusions; times use Moscow."""
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
DATA=json.loads((ROOT/('schedule.json' if (ROOT/'schedule.json').exists() else 'schedule.example.json')).read_text())
LESSONS=ROOT/'lessons'
TZ=ZoneInfo(DATA['timezone'])
organizing_lock=threading.Lock()

def match(moment):
    local=moment.astimezone(TZ)
    found=[e for e in DATA['entries'] if e['date']==local.strftime('%Y-%m-%d') and e['start']<=local.strftime('%H:%M')<e['end']]
    return found[0] if len(found)==1 else None

def metadata(name):
    m=re.match(r'lecture-(\d{4}-\d\d-\d\d)-(\d\d)-(\d\d)-(\d\d)-\d+\.wav$',name)
    if not m:return None
    date,hour,minute,second=m.groups()
    moment=datetime.fromisoformat(date+'T'+hour+':'+minute+':'+second).replace(tzinfo=TZ)
    entry=match(moment)
    if entry:
        teachers=list(dict.fromkeys(v['teacher'] for v in entry['variants'] if v.get('teacher')))
        folder=f"{date} {entry['start'].replace(':','-')} — {entry['subject']} — {entry['type']}"
        folder=re.sub(r'[/\\\x00]', '-',folder)
        return dict(entry,folder=folder,teacher=teachers[0] if len(teachers)==1 else None,teachers=teachers,
                    label=f"{date} · {entry['start']}–{entry['end']} · {entry['subject']} · {entry['type']}",source='schedule')
    return dict(date=date,folder=date+' — Вне расписания',label=date+' · Вне расписания',subject=None,type=None,
                teacher=None,teachers=[],variants=[],source='unmatched')

def current():
    now=datetime.now(TZ)
    entry=match(now)
    future=[e for e in DATA['entries'] if e['date']>now.strftime('%Y-%m-%d') or (e['date']==now.strftime('%Y-%m-%d') and e['start']>now.strftime('%H:%M'))]
    upcoming=min(future,key=lambda e:(e['date'],e['start'])) if future else None
    return dict(group=DATA['group'],current=entry,next=upcoming,timezone=DATA['timezone'],
                first=min(e['date'] for e in DATA['entries']),last=max(e['date'] for e in DATA['entries']))

def organize(name):
    with organizing_lock:
        _organize(name)

def _organize(name):
    meta=metadata(name)
    audio=ROOT/'recordings'/name
    if not meta or not audio.is_file():return
    folder=LESSONS/meta['folder'];folder.mkdir(parents=True,exist_ok=True)
    destination=folder/name
    if not destination.exists():os.link(audio,destination)
    sources=[audio.with_suffix('.gaps.json')]
    sources += [ROOT/'analysis'/(audio.stem+suffix) for suffix in ('.json','.md','.transcript.json')]
    for source in sources:
        target=folder/source.name
        if source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(os.path.relpath(source,folder))
    manifest=dict(meta,recordings=sorted(p.name for p in folder.glob('*.wav')))
    temporary=folder/'занятие.json.tmp';temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2));temporary.replace(folder/'занятие.json')

def organize_existing():
    for audio in (ROOT/'recordings').glob('*.wav'):organize(audio.name)
