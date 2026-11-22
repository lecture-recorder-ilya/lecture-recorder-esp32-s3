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
DATA.setdefault('group','')
DATA.setdefault('entries',[])
LESSONS=ROOT/'lessons'
TZ=ZoneInfo(DATA['timezone'])
organizing_lock=threading.Lock()

def match(moment):
    local=moment.astimezone(TZ)
    found=[e for e in DATA['entries'] if e['date']==local.strftime('%Y-%m-%d') and e['start']<=local.strftime('%H:%M')<e['end']]
    return found[0] if len(found)==1 else None

def recording_time(name):
    if not isinstance(name,str):return None
    m=re.fullmatch(r'lecture-(\d{4}-\d\d-\d\d)-(\d\d)-(\d\d)-(\d\d)-\d+\.wav',name)
    if not m:return None
    date,hour,minute,second=m.groups()
    try:return datetime.fromisoformat(date+'T'+hour+':'+minute+':'+second).replace(tzinfo=TZ)
    except ValueError:return None

def metadata(name):
    moment=recording_time(name)
    if moment is None:return None
    date=moment.date().isoformat()
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
    from mirea_schedule import cached_calendar
    calendar=cached_calendar(DATA)
    entries=calendar['entries']
    today,clock=now.strftime('%Y-%m-%d'),now.strftime('%H:%M')
    matches=[e for e in entries if e['date']==today and e['start']<=clock<e['end']]
    future=[e for e in entries if (e['date'],e['start'])>(today,clock)]
    upcoming=min(future,key=lambda e:(e['date'],e['start'])) if future else None
    return dict(group=calendar['group'],current=matches[0] if len(matches)==1 else None,next=upcoming,
                timezone=calendar['timezone'],first=min((e['date'] for e in entries),default=None),
                last=max((e['date'] for e in entries),default=None))

def organize(name):
    with organizing_lock:
        _organize(name)

def _organize(name):
    meta=metadata(name)
    audio=ROOT/'recordings'/name
    from recording_selection import awaiting
    if not meta or not audio.is_file() or awaiting(name):return
    from study_store import overrides, report_aliases
    assigned=overrides().get(name)
    if assigned:
        report_aliases(name,assigned['folder'])
        return
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


def assign_recording(name, lesson):
    from mirea_schedule import lesson_folder
    from study_store import move

    moment = recording_time(name)
    if moment is None:
        raise ValueError('Некорректное имя записи.')
    day = moment.date().isoformat()
    old = metadata(name)
    meta = {'folder': (old or {}).get('folder'), 'date': day, 'subject': None, 'type': None,
            'teacher': None, 'teachers': [], 'variants': [], 'start': '', 'end': ''}
    if lesson is None:
        return move(name, day + ' — Вне расписания', meta)
    if not isinstance(lesson, dict):
        raise ValueError('Некорректные сведения о паре.')

    def text(value, limit):
        if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
            raise ValueError('Некорректные сведения о паре.')
        return value.strip()

    subject = text(lesson.get('subject'), 200)
    if not subject:
        raise ValueError('Укажи название пары.')
    start = text(lesson.get('start', ''), 5)
    end = text(lesson.get('end', ''), 5)
    if lesson.get('date', day) != day or any(value and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value)
                                             for value in (start, end)):
        raise ValueError('Некорректная дата или время пары.')
    kind = text(lesson.get('type', ''), 48)
    group = text(lesson.get('group', ''), 48)
    room = text(lesson.get('room', ''), 96)
    variants = lesson.get('variants', [])
    if not isinstance(variants, list) or len(variants) > 16 or not all(isinstance(item, dict) for item in variants):
        raise ValueError('Некорректные сведения о паре.')
    variants = [
        {key: text(item.get(key, ''), 128) for key in ('teacher', 'room', 'building')}
        for item in variants
    ]
    if not variants and room:
        variants = [{'teacher': '', 'room': room}]
    teachers = list(dict.fromkeys(item['teacher'] for item in variants if item['teacher']))
    meta.update(subject=subject, type=kind, group=group, room=room, start=start, end=end, teachers=teachers,
                teacher=teachers[0] if len(teachers)==1 else None, variants=variants)
    return move(name, lesson_folder(meta), meta)
