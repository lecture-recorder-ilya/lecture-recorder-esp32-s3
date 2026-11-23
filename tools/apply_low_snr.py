"""Сравнить зафиксированные правила по сохранённым акустическим проходам."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

from evaluate_asr import audio_sha256, score, summarize_scores, summarize_subsets


def run(args):
    if args.output.exists():
        raise ValueError('Укажи новый файл результата.')
    sys.path.insert(0, str(args.source_root/'outputs/recorder'))
    from asr_low_snr_policy import choose_audio, recover_gaps
    from asr_guard import join_words
    from asr_segments import phrase_rows
    from speech_quality import clean_asr_text
    clean, raw = json.loads(args.clean.read_text()), json.loads(args.raw.read_text())
    if clean['manifest_sha256'] != raw['manifest_sha256'] or clean['models_sha256'] != raw['models_sha256']:
        raise ValueError('Различаются наборы или веса.')
    crops = raw.get('gap_crops', False)
    if (not raw['raw_audio'] and not crops) or clean['raw_audio'] or (crops and args.policy != 'gaps'):
        raise ValueError('Нужны очищенный и исходный проходы в этом порядке.')
    rows = []
    for base, alternate in zip(clean['cases'], raw['cases'], strict=True):
        if any(base[key] != alternate[key] for key in ('id', 'audio_sha256', 'pcm_sha256', 'reference')):
            raise ValueError('Различаются WAV или эталоны.')
        started = time.monotonic()
        segments, decisions = [], []
        changed = False
        for first, second in zip(base['chunks'], alternate['chunks'], strict=True):
            if any(first[key] != second[key] for key in ('offset', 'emit_start', 'emit_end')):
                raise ValueError('Различаются окна исходного аудио.')
            original_text = first.get('text', base['text'] if len(base['chunks']) == 1 else None)
            if original_text is None:
                raise ValueError('В старом многоблочном журнале нет текста блоков.')
            if not original_text:
                chosen, decision, local_changed = deepcopy(first['evidence']), 'empty-kept', False
            elif args.policy == 'choice':
                margin = {'strict': .04, 'relaxed': .02, 'argmax': 0}[args.profile]
                chosen, decision = choose_audio(first['evidence'], second['evidence'], margin=margin)
                local_changed = decision == 'raw'
            else:
                chosen, added = recover_gaps(first['evidence'], second['gap_trace'] if crops else second['trace'],
                                           word_confidence=.75 if args.profile == 'strict' else .65,
                                           mean_confidence=.85 if args.profile == 'strict' else .75)
                decision, local_changed = dict(added=added), bool(added)
            text = clean_asr_text(join_words(chosen.get('word_evidence', []))) if local_changed else original_text
            changed |= local_changed
            decisions.append(decision)
            segments.extend(phrase_rows(text, chosen, first['offset'], first['emit_start'], first['emit_end'], len(segments)))
        text = ' '.join(row['text'] for row in segments) if changed else base['text']
        if not changed:
            segments = base['segments']
        row = {key: base[key] for key in ('id', 'subset', 'audio_sha256', 'pcm_sha256', 'reference', 'duration')}
        row.update(text=text, segments=segments, decisions=decisions,
                   elapsed_seconds=(0 if crops else base['elapsed_seconds'])+alternate['elapsed_seconds']+time.monotonic()-started,
                   clean_elapsed_seconds=base['elapsed_seconds'], raw_elapsed_seconds=alternate['elapsed_seconds'],
                   **score(base['reference'], text))
        rows.append(row)
    report = dict(policy=args.policy, profile=args.profile, policy_sha256=audio_sha256(Path(__file__).with_name('asr_low_snr_policy.py')),
                  script_sha256=audio_sha256(Path(__file__)), inputs_sha256={str(p): audio_sha256(p) for p in (args.clean, args.raw)},
                  manifest_sha256=clean['manifest_sha256'], models_sha256=clean['models_sha256'],
                  timing=('Измеренный current с дополнительными CTC/RNN-T по пробелам плюс правило.' if crops else
                          'Сумма измеренных clean и raw проходов плюс время правила; загрузка моделей включена в оба процесса.'),
                  summary=summarize_scores(rows), subsets=summarize_subsets(rows), cases=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(policy=args.policy, summary=report['summary'], subsets=report['subsets']), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('clean', type=Path)
    parser.add_argument('raw', type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--policy', required=True, choices=('choice', 'gaps'))
    parser.add_argument('--profile', choices=('strict', 'relaxed', 'argmax'), default='strict')
    parser.add_argument('--output', required=True, type=Path)
    run(parser.parse_args())
