"""Сравнить WER по целым источникам и измерить влияние одного спикера."""

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean

from asr_qa import lock_control, validate_lecture_splits
from evaluate_asr import EDIT_OPERATIONS, audio_sha256, indexed_rows, tokens
from prepare_asr_qa import load


def totals(rows):
    words = sum(row['reference_words'] for row in rows)
    edits = {key: sum(row['word_error_breakdown'][key] for row in rows) for key in EDIT_OPERATIONS}
    return dict(words=words, edits=edits, wer=sum(edits.values()) / words if words else None)


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return groups


def average(rows):
    by_lecture = grouped(rows, lambda row: row['lecture_id'])
    wers = [totals(group)['wer'] for group in by_lecture.values()]
    return dict(micro=totals(rows)['wer'], macro=mean(value for value in wers if value is not None))


def speaker_or_lecture(row):
    if row.get('speaker_id'):
        return 'speaker:' + row['speaker_id']
    return 'lecture:' + row['lecture_id']


def sensitivity(rows):
    fold_groups = grouped(rows, speaker_or_lecture)
    return {ident: average([row for row in rows if speaker_or_lecture(row) != ident])
            for ident in sorted(fold_groups) if len(fold_groups) > 1}


def attach_speakers(cases, speakers):
    if {case['lecture_id'] for case in cases.values()} != speakers.keys():
        raise ValueError('В списке выступающих должны быть все исходные лекции.')
    enriched = {}
    for ident, case in cases.items():
        metadata = speakers[case['lecture_id']]
        speaker = metadata['speaker'].strip()
        if not speaker or metadata['source_video'] != case.get('source_video'):
            raise ValueError(f"{ident}: имя выступающего должно быть подтверждено исходным видео.")
        if case.get('speaker_id') and case['speaker_id'] != speaker:
            raise ValueError(f"{ident}: источник и манифест дают разные идентификаторы спикера.")
        enriched[ident] = dict(case, speaker_id=speaker)
    validate_lecture_splits(enriched.values())
    return enriched


def report_rows(report, cases, lock_path, lock):
    if (report['platform'] != 'mac' or report['lock_sha256'] != audio_sha256(lock_path)
            or report['manifest_sha256'] != lock['manifest_sha256']):
        raise ValueError('Две версии должны использовать тот же зафиксированный вход Mac.')
    scores = indexed_rows(report['cases'], report['revision'])
    if scores.keys() != cases.keys():
        raise ValueError('Список WAV отличается от манифеста.')
    rows = []
    for ident, case in cases.items():
        score = scores[ident]
        if (score['audio_sha256'] != case['audio_sha256'] or score['subset'] != case['subset']
                or score['reference_words'] != len(tokens(case['reference']))):
            raise ValueError(f'{ident}: метаданные или WAV отличаются.')
        rows.append(dict(score, lecture_id=case['lecture_id'], speaker_id=case.get('speaker_id')))
    return rows


def percent(value):
    return '—' if value is None else f'{100 * value:.2f}%'.replace('.', ',')


def table(base, candidate):
    for subset, title in (('lecture_tune', 'Настройка'), ('lecture_holdout', 'Контроль')):
        old = [row for row in base if row['subset'] == subset]
        new = [row for row in candidate if row['subset'] == subset]
        if not old:
            continue
        print(f'\n### {title}\n')
        print('| Исходная лекция | Слова | Замены | Пропуски | Вставки | WER |')
        print('| --- | ---: | ---: | ---: | ---: | ---: |')
        old_by = grouped(old, lambda row: row['lecture_id'])
        new_by = grouped(new, lambda row: row['lecture_id'])
        for ident in sorted(old_by):
            first, last = totals(old_by[ident]), totals(new_by[ident])
            edits = [f"{first['edits'][key]} → {last['edits'][key]}" for key in EDIT_OPERATIONS]
            print(f"| {ident} | {first['words']} | {' | '.join(edits)} | "
                  f"{percent(first['wer'])} → {percent(last['wer'])} |")
        a, b = average(old), average(new)
        print(f"\nОбщий WER (micro) {percent(a['micro'])} → {percent(b['micro'])}. "
              f"Среднее по лекциям (macro) {percent(a['macro'])} → {percent(b['macro'])}.")
        a, b = sensitivity(old), sensitivity(new)
        if a:
            print('\n| Убрали одну группу | Micro WER | Macro WER |')
            print('| --- | ---: | ---: |')
            for ident in a:
                group, name = ident.split(':', 1)
                label = f'Спикер {name}' if group == 'speaker' else f'Лекция {name}'
                print(f"| {label} | {percent(a[ident]['micro'])} → {percent(b[ident]['micro'])} | "
                      f"{percent(a[ident]['macro'])} → {percent(b[ident]['macro'])} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('lock', type=Path)
    parser.add_argument('base', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--speakers', type=Path, help='Спикеры по метаданным оригинальных видео')
    args = parser.parse_args()
    cases = indexed_rows(load(args.manifest), 'Лекции')
    validate_lecture_splits(cases.values())
    lock = load(args.lock)
    if lock_control(args.manifest) != lock:
        raise ValueError('Манифест или WAV изменились.')
    if args.speakers:
        cases = attach_speakers(cases, load(args.speakers))
    base, candidate = load(args.base), load(args.candidate)
    base_rows = report_rows(base, cases, args.lock, lock)
    candidate_rows = report_rows(candidate, cases, args.lock, lock)
    print(f"{base['revision'][:7]} → {candidate['revision'][:7]}")
    table(base_rows, candidate_rows)


if __name__ == '__main__':
    main()
