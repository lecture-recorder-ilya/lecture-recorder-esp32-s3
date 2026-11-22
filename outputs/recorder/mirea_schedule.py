"""Профиль студента и публичное расписание РТУ МИРЭА."""

import json
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


WORK = Path(__file__).resolve().parents[2] / 'work'
PROFILE = WORK / 'mirea-profile.json'
CACHE = WORK / 'mirea-schedule.json'
SITE = 'https://schedule-of.mirea.ru'
TZ = ZoneInfo('Europe/Moscow')
REFRESH_SECONDS = 6 * 3600
MAX_PAYLOAD = 1024 * 1024
LOCK = threading.Lock()
last_error = ('', 0)


@lru_cache(maxsize=4)
def _read(path, revision):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def read(path):
    try:
        return _read(path, path.stat().st_mtime_ns)
    except OSError:
        return {}


def save(path, value):
    from study_store import save as save_json
    save_json(path, value)


def group_code(value):
    if not isinstance(value, str):
        return ''
    return value.strip().upper().translate(str.maketrans('‐‑–—−', '-----'))


def profile():
    data = read(PROFILE)
    return {'configured': bool(data.get('configured')), 'group': data.get('group', ''), 'course': data.get('course')}


def set_profile(value):
    if value.get('skip') is True:
        save(PROFILE, {'configured': True})
        return profile()
    group = group_code(value.get('group'))
    if not re.fullmatch(r'[А-ЯЁA-Z0-9]{1,12}(?:-[А-ЯЁA-Z0-9]{1,8}){2,4}', group):
        raise ValueError('Введи код группы в формате ИКБО-01-26.')
    course = value.get('course')
    if type(course) is not int or not 1 <= course <= 6:
        raise ValueError('Выбери курс с 1-го по 6-й.')
    save(PROFILE, {'configured': True, 'group': group, 'course': course})
    return profile()


def _download(path):
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/bin/curl', '--disable', '-fsS', '--proto', '=https',
                                 '--max-time', '5', '--max-filesize', str(MAX_PAYLOAD), SITE + path],
                                capture_output=True, timeout=6)
        if result.returncode:
            raise OSError('Расписание МИРЭА сейчас недоступно.')
        content = result.stdout
    else:
        with urlopen(SITE + path, timeout=5) as response:
            if not response.url.startswith(SITE + '/'):
                raise ValueError('Расписание перенаправило запрос на неизвестный сайт.')
            content = response.read(MAX_PAYLOAD + 1)
    if len(content) > MAX_PAYLOAD:
        raise ValueError('Расписание слишком большое.')
    return content.decode('utf-8-sig')


def _schedule(group):
    query = urlencode({'limit': 15, 'match': group})
    data = json.loads(_download('/schedule/api/search?' + query))
    rows = data.get('data', []) if isinstance(data, dict) else []
    gid = next((row['id'] for row in rows if isinstance(row, dict) and row.get('scheduleTarget') == 1
                and group_code(row.get('targetTitle')) == group and type(row.get('id')) is int and row['id'] > 0), None)
    if gid is None:
        raise ValueError('Группа не найдена в расписании МИРЭА.')
    return parse_ical(_download(f'/schedule/api/ical/1/{gid}'), group)


def cached_calendar(legacy, info=None):
    group = (info if info is not None else profile())['group']
    if not group:
        return legacy
    cache = read(CACHE)
    if cache.get('group') == group:
        return cache
    if group_code(legacy.get('group')) == group:
        return legacy
    return {'group': group, 'timezone': TZ.key, 'entries': []}


def load_calendar(legacy):
    global last_error
    info = profile()
    group = info['group']
    if not group:
        return legacy
    with LOCK:
        fallback = cached_calendar(legacy, info)
        now = time.time()
        if now - fallback.get('updated', 0) < REFRESH_SECONDS:
            return fallback
        if last_error[0] == group and now - last_error[1] < 60:
            return dict(fallback, offline=True, error='Расписание МИРЭА сейчас недоступно.')
        try:
            data = dict(_schedule(group), updated=now)
            save(CACHE, data)
            return data
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
            last_error = (group, now)
            message = str(error) if isinstance(error, ValueError) else 'Расписание МИРЭА сейчас недоступно.'
            return dict(fallback, offline=True, error=message)


def _fields(text):
    event = None
    for line in re.split(r'\r?\n', re.sub(r'\r?\n[ \t]', '', text)):
        if line == 'BEGIN:VEVENT':
            event = defaultdict(list)
        elif line == 'END:VEVENT' and event is not None:
            yield event
            event = None
        elif event is not None:
            header, separator, value = line.partition(':')
            if separator:
                name, _, params = header.partition(';')
                event[name].append((params, value))


def _moment(field):
    params, value = field
    if len(value) == 8:
        return datetime.combine(datetime.strptime(value, '%Y%m%d').date(), datetime.min.time(), TZ)
    utc = value.endswith('Z')
    zone = timezone.utc if utc else TZ
    if not utc:
        match = re.search(r'(?:^|;)TZID=([^;]+)', params)
        if match and match[1].strip('"') != TZ.key:
            raise ValueError('Неизвестная часовая зона занятия.')
    clock = datetime.strptime(value.removesuffix('Z'), '%Y%m%dT%H%M%S')
    return clock.replace(tzinfo=zone).astimezone(TZ)


def _text(value):
    return re.sub(r'\\([nN,;\\])', lambda match: ' ' if match[1].lower() == 'n' else match[1], value).strip()


def _recurrence(event, start):
    values = event.get('RRULE', [])
    if values:
        rule = dict(part.split('=', 1) for part in values[0][1].split(';') if '=' in part)
        if set(rule) <= {'FREQ', 'INTERVAL', 'UNTIL', 'COUNT'} and rule.get('FREQ') in ('WEEKLY', 'DAILY'):
            interval = int(rule.get('INTERVAL', '1'))
            if interval > 0:
                step = timedelta(days=interval * (7 if rule['FREQ'] == 'WEEKLY' else 1))
                until = _moment(('', rule['UNTIL'])) if 'UNTIL' in rule else start + timedelta(days=180)
                if len(rule.get('UNTIL', '')) == 8:
                    until += timedelta(days=1) - timedelta(microseconds=1)
                count = min(400, int(rule.get('COUNT', '400')))
                for index in range(count):
                    moment = start + step * index
                    if moment > until:
                        break
                    yield moment
                return
    yield start


def _instances(event, start):
    excepted = set()
    for params, values in event.get('EXDATE', []):
        excepted.update(_moment((params, value)) for value in values.split(','))
    included = set(_recurrence(event, start))
    for params, values in event.get('RDATE', []):
        included.update(_moment((params, value)) for value in values.split(','))
    for moment in sorted(included):
        if moment not in excepted and moment.replace(hour=0, minute=0, second=0) not in excepted:
            yield moment


def lesson_folder(entry):
    day, start, subject, kind = (entry[key] for key in ('date', 'start', 'subject', 'type'))
    pieces = [day + (' ' + start.replace(':', '-') if start else ''), subject, kind]
    value = re.sub(r'[/\\\x00]', '-', ' — '.join(piece for piece in pieces if piece))
    return value[:180].encode('utf-8')[:240].decode('utf-8', errors='ignore').rstrip()


def parse_ical(text, group):
    if not text.startswith('BEGIN:VCALENDAR') or not text.rstrip().endswith('END:VCALENDAR'):
        raise ValueError('Источник вернул повреждённое расписание.')
    entries = {}
    for event in _fields(text):
        def field(key):
            return event.get(key, [('', '')])[0][1]

        if field('STATUS').upper() == 'CANCELLED' or not all('T' in field(key) for key in ('DTSTART', 'DTEND')):
            continue
        try:
            start = _moment(event['DTSTART'][0])
            duration = _moment(event['DTEND'][0]) - start
            if not timedelta(0) < duration < timedelta(days=1):
                continue
            kind = _text(field('CATEGORIES'))
            subject = _text(field('SUMMARY'))
            if kind and subject.startswith(kind + ' '):
                subject = subject[len(kind) + 1:]
            if not subject:
                continue
            description = re.search(r'(?i)Преподаватель:\s*([^\\\n]+)', field('DESCRIPTION'))
            room = _text(field('LOCATION'))
            variant = {'teacher': _text(description[1]) if description else '', 'room': room}
            for moment in _instances(event, start):
                day = moment.date().isoformat()
                begins, ends = moment.strftime('%H:%M'), (moment + duration).strftime('%H:%M')
                key = (day, begins, ends, subject, kind)
                entry = entries.setdefault(key, dict(zip(('date', 'start', 'end', 'subject', 'type'), key),
                                                      group=group, variants=[]))
                if variant not in entry['variants']:
                    entry['variants'].append(variant)
        except (ValueError, OverflowError):
            continue
    ordered = [entries[key] for key in sorted(entries)]
    for entry in ordered:
        entry['folder'] = lesson_folder(entry)
    return {'group': group, 'timezone': TZ.key, 'entries': ordered}


def suggest(entries, moment, seconds):
    final = moment + timedelta(seconds=seconds)
    options = []
    for i, entry in enumerate(entries):
        try:
            begins = datetime.fromisoformat(entry['date'] + 'T' + entry['start']).replace(tzinfo=TZ)
            ends = datetime.fromisoformat(entry['date'] + 'T' + entry['end']).replace(tzinfo=TZ)
        except (ValueError, KeyError):
            continue
        if begins <= moment < ends or timedelta(0) < begins - moment < timedelta(minutes=10) and final > begins + timedelta(minutes=1):
            options.append(i)
    return options[0] if len(options) == 1 else None
