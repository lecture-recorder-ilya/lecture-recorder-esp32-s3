import hashlib
import json
import math
import re
from pathlib import Path


def documents(root, errors=None):
    import lesson_schedule
    errors = errors if errors is not None else []
    selected = {}
    for path in (root / 'analysis').glob('*.json'):
        stem = path.name.removesuffix('.json').removesuffix('.live')
        if re.fullmatch(r'lecture-[0-9-]+', stem):
            selected.setdefault(stem + '.wav', []).append(path)
    for name, paths in sorted(selected.items()):
        value = None
        for path in sorted(paths, key=lambda p: p.name.endswith('.live.json')):
            try:
                report = json.loads(path.read_text())
                if not isinstance(report, dict):
                    raise ValueError('Некорректный формат расшифровки')
                rows = report.get('segments') or []
                if not isinstance(rows, list):
                    raise ValueError('Некорректные строки расшифровки')
                clean = {k: report[k] for k in ('subject', 'topic', 'teacher', 'overview')
                         if isinstance(report.get(k), str) and report[k].strip()}
                clean.update({k: report[k] for k in ('summary', 'homework', 'formulas', 'warnings')
                              if isinstance(report.get(k), list)})
                clean['segments'] = []
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get('text'), str):
                        continue
                    segment = {k: row[k] for k in ('text', 'original_text') if isinstance(row.get(k), str)}
                    segment.update({k: row[k] for k in ('start', 'end') if type(row.get(k)) in (int, float) and math.isfinite(row[k])})
                    original = row.get('context_review', {}).get('original_text') if isinstance(row.get('context_review'), dict) else None
                    if isinstance(original, str) and original != row['text']:
                        segment['original_text'] = original
                    if row.get('needs_review') is True:
                        segment['needs_review'] = True
                    clean['segments'].append(segment)
                if not clean['segments'] and not clean.get('summary'):
                    continue
                clean['draft'] = path.name.endswith('.live.json')
                meta = lesson_schedule.metadata(name) or {}
                lesson = {k: meta[k] for k in ('subject', 'teacher', 'date', 'start') if meta.get(k)}
                value = {'file': name, 'lesson': lesson, 'report': clean}
                raw = json.dumps(value).encode()
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('Текст слишком большой для телефона')
                break
            except (OSError, ValueError, TypeError) as error:
                errors.append(path.name + ': ' + str(error)[:100])
                value = None
        if value is not None:
            yield value, hashlib.sha256(raw).hexdigest()


def push(base, token, root=None):
    from phone_sync import request
    root = root or Path(__file__).resolve().parent
    with request(base, token, '/notes-index') as response:
        known = json.load(response)
    count = 0
    errors = []
    for value, digest in documents(root, errors):
        if known.get(value['file']) == digest:
            continue
        with request(base, token, '/notes', value) as response:
            answer = json.load(response)
        if answer.get('sha256') != digest:
            raise ValueError('Телефон не подтвердил сохранение текста')
        count += 1
    if errors:
        raise ValueError('Пропущено файлов: ' + str(len(errors)) + ' · ' + errors[0])
    return count
