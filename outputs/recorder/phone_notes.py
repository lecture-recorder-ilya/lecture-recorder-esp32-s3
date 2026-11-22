import hashlib
import json
import math
import re
import time
from contextlib import nullcontext
from pathlib import Path
from urllib.error import HTTPError


def read_document(root, name, paths, errors):
    import lesson_schedule
    from phone_sync import encode_body
    from transcript_quality import annotate
    from summary_sources import reconcile
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
            report = reconcile(annotate(report, decisions))
            rows = report.get('segments') or []
            if not isinstance(rows, list):
                raise ValueError('Некорректные строки расшифровки')
            clean = {k: report[k] for k in ('subject', 'topic', 'teacher', 'overview')
                     if isinstance(report.get(k), str) and report[k].strip()}
            clean.update({k: report[k] for k in ('summary', 'summary_evidence', 'homework', 'homework_review', 'formulas', 'formula_review', 'warnings', 'sections')
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
            return value, raw
        except (OSError, ValueError, TypeError) as error:
            errors.append(path.name + ': ' + str(error)[:100])
    return None


def documents(root, errors=None, *, revisioned=False):
    from phone_sync import atomic, encode_body, ledger_lock
    errors = errors if errors is not None else []
    selected = {}
    for path in (root / 'analysis').glob('*.json'):
        stem = path.name.removesuffix('.json').removesuffix('.live').removesuffix('.transcript')
        if re.fullmatch(r'lecture-[0-9-]+', stem):
            selected.setdefault(stem + '.wav', []).append(path)
    for name, paths in sorted(selected.items()):
        state_path = root / 'study/phone-note-sync' / (name + '.json')
        try:
            if revisioned:
                state_path.parent.mkdir(parents=True, exist_ok=True)
            # Читаем текущую редакцию и присваиваем ей номер до сетевой отправки.
            with ledger_lock(state_path) if revisioned else nullcontext():
                packet = read_document(root, name, paths, errors)
                if packet is None:
                    continue
                value, raw = packet
                if revisioned:
                    try:
                        previous = json.loads(state_path.read_text())
                    except FileNotFoundError:
                        previous = {}
                    draft = value['report']['draft']
                    if draft and previous.get('draft') is False:
                        continue
                    content = hashlib.sha256(raw).hexdigest()
                    revision = int(previous.get('revision', 0))
                    changed = previous.get('content') != content
                    if changed:
                        revision = max(revision + 1, time.time_ns() // 1000)
                    value['sync_revision'] = str(revision)
                    raw = encode_body('/notes', value)
                    if changed:
                        atomic(state_path, dict(content=content, revision=revision, draft=draft))
        except (OSError, ValueError) as error:
            errors.append(name + ': ' + str(error)[:100])
            continue
        yield value, hashlib.sha256(raw).hexdigest()


def recording_targets(ledger, device, offered):
    groups = {}
    for local, entry in ledger.items():
        groups.setdefault(entry.get('source_name', local), []).append((local, entry))
    listed = {item['name']: item.get('sha256') for item in offered}
    targets = dict.fromkeys(listed)
    for remote, entries in groups.items():
        targets.setdefault(remote, None)
        for local, entry in entries:
            targets[local] = None
            if remote in listed:
                belongs = entry.get('sha256') == listed[remote]
            else:
                belongs = device in entry.get('devices', []) or ('devices' not in entry and len(entries) == 1)
            if belongs:
                targets[local] = remote
    return targets

def push(base, token, root=None, *, device_id=None, offered=()):
    from phone_sync import request, source_id, encode_body
    root = root or Path(__file__).resolve().parent
    with request(base, token, '/notes-index') as response:
        revisioned = getattr(response, 'headers', {}).get('X-ClipMic-Note-Revisions') == '1'
        known = json.load(response)
    ledger = root.parent.parent / 'work/phone-imports.json'
    entries = json.loads(ledger.read_text()) if ledger.exists() else {}
    targets = recording_targets(entries, source_id(token, device_id), offered)
    count = 0
    errors = []
    for value, digest in documents(root, errors, revisioned=revisioned):
        remote = targets.get(value['file'], value['file'])
        if remote is None:
            continue
        if remote != value['file']:
            value['file'] = remote
            digest = hashlib.sha256(encode_body('/notes', value)).hexdigest()
        if known.get(remote) == digest:
            continue
        try:
            with request(base, token, '/notes', value) as response:
                answer = json.load(response)
        except HTTPError as error:
            if error.code != 409:
                raise
            error.close()
            errors.append(remote + ' · на телефоне уже сохранена другая или более новая версия')
            continue
        if answer.get('sha256') != digest:
            raise ValueError('Телефон не подтвердил сохранение текста')
        count += 1
    if errors:
        raise ValueError('Пропущено файлов: ' + str(len(errors)) + ' · ' + errors[0])
    return count
