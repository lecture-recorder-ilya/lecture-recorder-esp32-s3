import hashlib
import json
import math
import re
from pathlib import Path


def documents(root, errors=None):
    import lesson_schedule
    from phone_sync import encode_body
    from transcript_quality import annotate
    errors = errors if errors is not None else []
    selected = {}
    for path in (root / 'analysis').glob('*.json'):
        stem = path.name.removesuffix('.json').removesuffix('.live').removesuffix('.transcript')
        if re.fullmatch(r'lecture-[0-9-]+', stem):
            selected.setdefault(stem + '.wav', []).append(path)
    for name, paths in sorted(selected.items()):
        value = None
        for path in sorted(paths, key=lambda p: (p.name.endswith(('.live.json', '.transcript.json')), -p.stat().st_mtime_ns)):
            try:
                report = json.loads(path.read_text())
                if not isinstance(report, dict):
                    raise ValueError('Некорректный формат расшифровки')
                notes_path = root / 'study' / (Path(name).stem + '.notes.json')
                try:
                    decisions = json.loads(notes_path.read_text()).get('transcript_review', {})
                except (OSError, ValueError):
                    decisions = {}
                report = annotate(report, decisions)
                rows = report.get('segments') or []
                if not isinstance(rows, list):
                    raise ValueError('Некорректные строки расшифровки')
                clean = {k: report[k] for k in ('subject', 'topic', 'teacher', 'overview')
                         if isinstance(report.get(k), str) and report[k].strip()}
                clean.update({k: report[k] for k in ('summary', 'summary_evidence', 'homework', 'formulas', 'warnings', 'sections')
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
                    segment.update({key: row[key] for key in ('id', 'review_key', 'reviewed', 'quality', 'timing') if key in row})
                    clean['segments'].append(segment)
                if not clean['segments'] and not clean.get('summary'):
                    continue
                clean['draft'] = path.name.endswith(('.live.json', '.transcript.json'))
                meta = lesson_schedule.metadata(name) or {}
                try:
                    changed = json.loads((root / 'study/folders.json').read_text())
                    meta = changed.get(name) or meta
                except (OSError, ValueError):
                    pass
                lesson = {k: meta[k] for k in ('subject', 'teacher', 'date', 'start') if meta.get(k)}
                value = {'file': name, 'lesson': lesson, 'report': clean}
                raw = encode_body('/notes', value)
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
