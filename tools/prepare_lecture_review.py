"""Подготовить фразы с числами и отрицаниями для слепой ручной сверки."""

import argparse
from collections import defaultdict
import hashlib
from pathlib import Path

from asr_qa import lock_control
from evaluate_asr import NEGATIONS, audio_sha256, indexed_rows, numeric_token, tokens
from prepare_asr_qa import load, save
from prepare_long_asr import cut


def select(cases):
    control = [case for case in cases if case['subset'] == 'lecture_holdout']
    used = set()
    output = []
    for focus, matches in (('number', numeric_token), ('negation', NEGATIONS.__contains__)):
        per_lecture = defaultdict(list)
        for case in control:
            for cue in case['cues']:
                if not 1.5 <= cue['end'] - cue['start'] <= 12 or not any(map(matches, tokens(cue['text']))):
                    continue
                ident = f"{case['id']}-{cue['start']:.3f}"
                per_lecture[case['lecture_id']].append((ident, case, cue))
        for picks in per_lecture.values():
            picks.sort(key=lambda item: hashlib.sha256(('clipmic-review-v1:' + item[0]).encode()).digest())
        chosen = 0
        while chosen < 4:
            added = False
            for lecture in sorted(per_lecture):
                picks = per_lecture[lecture]
                while picks and picks[0][0] in used:
                    picks.pop(0)
                if not picks:
                    continue
                ident, case, cue = picks.pop(0)
                used.add(ident)
                output.append((ident, case, cue, focus))
                chosen += 1
                added = True
                if chosen == 4:
                    break
            if not added:
                raise ValueError(f'Недостаточно фраз для {focus}.')
    return output


def prepare(manifest, lock, output):
    if lock_control(manifest) != load(lock):
        raise ValueError('Манифест и WAV отличаются от зафиксированного контроля.')
    selected = select(load(manifest))
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, (_, case, cue, focus) in enumerate(selected, 1):
        start, end = cue['start'] - case['clip_start'], cue['end'] - case['clip_start']
        extract_start = max(0, start - .45)
        extract_end = min(case['clip_end'] - case['clip_start'], end + .45)
        path = output / f'{index:02}.wav'
        cut(manifest.parent / case['audio'], path, extract_start, extract_end)
        rows.append(dict(id=path.stem, case_id=case['id'], lecture_id=case['lecture_id'], focus=focus,
                         audio=path.name, audio_sha256=audio_sha256(path),
                         parent_audio_sha256=case['audio_sha256'],
                         source_interval=[cue['start'], cue['end']],
                         parent_interval=[round(start, 3), round(end, 3)],
                         listen_interval=[round(start-extract_start, 3), round(end-extract_start, 3)],
                         subtitles=dict(reference_type='subtitles', text=cue['text']),
                         manual_review=None))
    save(output / 'review.json', rows)


def verify_manual(row):
    review = row.get('manual_review')
    if review is None:
        return False
    if (not isinstance(review, dict) or review.get('reference_type') != 'manual_verified'
            or review.get('audio_sha256') != row['audio_sha256']
            or not all(isinstance(review.get(key), str) and review[key].strip()
                       for key in ('reviewer', 'checked_at', 'text'))):
        raise ValueError(f"{row['id']}: ручная сверка без текста, авторства, даты или совпадающего WAV.")
    return True


def machine_review(packet, decoded, output):
    source = indexed_rows(load(decoded)['cases'], 'Машинная расшифровка')
    rows = []
    for row in load(packet):
        result = source[row['case_id']]
        if result['audio_sha256'] != row['parent_audio_sha256']:
            raise ValueError(f"{row['id']}: машинная расшифровка сделана по другому WAV.")
        start, end = row['parent_interval']
        words = [part['word'] for segment in result['segments'] for part in segment.get('words', [])
                 if start <= (part['start']+part['end']) / 2 < end]
        rows.append(dict(id=row['id'], reference_type='machine', text=' '.join(words),
                         audio_sha256=row['audio_sha256'], decoded_sha256=audio_sha256(decoded),
                         selection='середина таймкода слова в интервале подсказки'))
    save(output, rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('prepare')
    create.add_argument('manifest', type=Path)
    create.add_argument('lock', type=Path)
    create.add_argument('output', type=Path)
    check = commands.add_parser('check')
    check.add_argument('packet', type=Path)
    machine = commands.add_parser('machine')
    machine.add_argument('packet', type=Path)
    machine.add_argument('decoded', type=Path)
    machine.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.manifest, args.lock, args.output)
    elif args.command == 'check':
        rows = load(args.packet)
        for row in rows:
            if audio_sha256(args.packet.parent / row['audio']) != row['audio_sha256']:
                raise ValueError(f"{row['id']}: WAV отличается от пакета.")
        print(f'Ручная сверка: {sum(map(verify_manual, rows))} из {len(rows)}')
    else:
        machine_review(args.packet, args.decoded, args.output)
