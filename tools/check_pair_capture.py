"""Проверить паспорт трёх дистанций по JSON стенда ClipMic P1."""

import argparse
import math
from pathlib import Path

from evaluate_asr import audio_sha256
from prepare_asr_qa import load


DISTANCES = {1, 3, 5}
CHANNELS = ('ClipMic', 'phone')


def filled(value):
    return isinstance(value, str) and bool(value.strip())


def measured(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def check(path):
    series = load(path)
    reference = series['reference']
    if reference['reference_type'] not in ('scripted', 'manual_verified') or not filled(reference['text']):
        raise ValueError('Нужен один общий дословный эталон на всю серию.')
    if reference['reference_type'] == 'manual_verified' and not all(
            filled(reference.get(key)) for key in ('reviewer', 'checked_at')):
        raise ValueError('Для ручной сверки нужны дата и псевдоним проверившего.')
    if audio_sha256(path.parent / reference['wav']) != reference['sha256']:
        raise ValueError('SHA-256 фонограммы не совпадает.')
    if not all(filled(series.get(key)) for key in ('room', 'source')):
        raise ValueError('Укажи комнату и параметры источника.')
    distances, ids = set(), set()
    for row in series['takes']:
        ident, distance = row['id'], row['distance_m']
        if not filled(ident) or ident in ids or type(distance) is not int or distance not in DISTANCES:
            raise ValueError('Нужны неповторяющиеся пары для дистанций 1, 3 и 5 м.')
        ids.add(ident)
        distances.add(distance)
        sync = load(path.parent / row['sync_json'])
        if sync['distance_m'] != distance:
            raise ValueError(f'{ident}: дистанция в паспорте и отчёте синхронизации различается.')
        for role in CHANNELS:
            audio, result = row[role], sync[role]
            for key in ('distance_measured_m', 'height_m'):
                if not measured(audio.get(key)):
                    raise ValueError(f'{ident}: нужно фактическое измерение {key} для {role}.')
            if not all(filled(audio.get(key)) for key in ('device', 'microphone', 'position')):
                raise ValueError(f'{ident}: нужен паспорт позиции и микрофона {role}.')
            if (audio['channel'] != result['channel'] or audio_sha256(path.parent / audio['wav']) != result['sha256']
                    or audio_sha256(path.parent / audio['original']) != audio['original_sha256']):
                raise ValueError(f'{ident}: файлы или канал {role} отличаются.')
            a, b = result['marker_times_s']
            if not all(map(math.isfinite, (a, b))) or a < 0 or abs((b - a) / 24 - 1) > .005:
                raise ValueError(f'{ident}: две метки {role} не образуют синхронизируемый интервал.')
    if distances != DISTANCES:
        raise ValueError('Нужна минимум одна пара на каждой дистанции.')
    return len(ids)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('series', type=Path)
    args = parser.parse_args()
    print(f'Сверены WAV, метки и паспорт для {check(args.series)} пар.')
