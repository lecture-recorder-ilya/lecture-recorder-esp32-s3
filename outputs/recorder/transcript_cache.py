import hashlib
import json
import math
import time
from pathlib import Path

WHISPER_ENGINE = 'Whisper-large-v3-turbo-context-v5-clean'


def context_identity(name, root):
    values = {}

    def visit(current, depth):
        if depth > 4 or current in values or Path(current).name != current:
            return
        path = root / 'study' / (Path(current).stem + '.notes.json')
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        parts = data.get('parts', [])
        values[current] = {'asr_terms': data.get('asr_terms', ''), 'parts': parts}
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get('file'), str):
                    visit(part['file'], depth + 1)

    visit(name, 0)
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def identity(audio_path, engine, root=None):
    digest = hashlib.sha256()
    with audio_path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    root = Path(root) if root else audio_path.parent.parent
    return {'audio_sha256': digest.hexdigest(), 'engine': engine,
            'context_sha256': context_identity(audio_path.name, root)}


def valid(data, expected, total, step):
    if not isinstance(data, dict) or data.get('identity') != expected or data.get('engine') != expected['engine']:
        return False
    frames = data.get('completed_frames')
    if type(frames) is not int or not 0 <= frames <= total:
        return False
    if type(data.get('complete')) is not bool or (data['complete'] and frames != total):
        return False
    if frames != total and frames % step:
        return False
    rows = data.get('segments')
    if not isinstance(rows, list):
        return False
    previous = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('text'), str):
            return False
        start, end = row.get('start'), row.get('end')
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end)):
            return False
        if not previous <= start < end <= frames / 16000 + .011:
            return False
        previous = start
    return True


def prepare(path, expected, total, step):
    if path.exists():
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            old = None
        if valid(old, expected, total, step):
            return old
        backup = path.with_name(path.stem + '.before-quality-' + str(time.time_ns()) + '.json')
        path.replace(backup)
    return {'engine': expected['engine'], 'identity': expected, 'segments': [],
            'complete': False, 'completed_frames': 0}


def checkpoint(expected, segments, duration, frames, complete=False):
    return {'engine': expected['engine'], 'identity': expected, 'segments': segments,
            'duration': duration, 'language': 'ru', 'complete': complete,
            'completed_frames': frames}
