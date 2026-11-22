"""Ожидающие выбора пары записи переживают закрытие окна и перезапуск."""

import re
from pathlib import Path

import study_store

FILES = Path(__file__).resolve().parent / 'recordings'
NAME = re.compile(r'lecture-\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d-\d+\.wav')


def marker(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('Некорректное имя записи.')
    return (FILES / name).with_suffix('.lesson-pending.json')


def begin(name):
    study_store.save(marker(name), {'file': name})


def awaiting(name):
    return isinstance(name, str) and bool(NAME.fullmatch(name)) and marker(name).is_file()


def pending(active=''):
    result = []
    for path in FILES.glob('lecture-*.lesson-pending.json'):
        name = path.name.removesuffix('.lesson-pending.json') + '.wav'
        if name == active or not NAME.fullmatch(name):
            continue
        try:
            if (FILES / name).stat().st_size > 44:
                result.append(name)
        except FileNotFoundError:
            pass
    return sorted(result, reverse=True)


def recording(name):
    if not awaiting(name):
        raise ValueError('Эта запись уже обработана или недоступна.')
    audio = FILES / name
    if audio.stat().st_size <= 44:
        raise ValueError('В записи нет звука.')
    return audio


def finish(name):
    marker(name).unlink(missing_ok=True)


def discard(name):
    audio = recording(name)
    audio.unlink()
    root = FILES.parent
    for path in (
        audio.with_suffix('.gaps.json'),
        audio.with_suffix('.recovery.json'),
        root / 'analysis' / (audio.stem + '.live.json'),
        root / 'study' / (audio.stem + '.notes.json'),
        root / 'study' / (audio.stem + '.passive-teacher.json'),
        root / 'study' / (audio.stem + '.speakers.json'),
    ):
        path.unlink(missing_ok=True)
    finish(name)
