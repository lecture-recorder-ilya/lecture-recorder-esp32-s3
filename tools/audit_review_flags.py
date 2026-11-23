"""Проверить флаг сомнения на фиксированных эталонах и замороженном контроле."""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import sys

from evaluate_asr import audio_sha256, tokens, word_edits

TERMS = frozenset('пробирка мэтр клетка молекула теломера митохондрия мейерхольд '
                  'теорема метафора аналогия политология бактерия вирус антивирус '
                  'электростанция одномерный самодостаточность прибыль'.split())


@lru_cache(maxsize=8192)
def is_term(text):
    if text in TERMS:
        return True
    try:
        from context_review import morphology
        return morphology().parse(text)[0].normal_form in TERMS
    except ImportError:
        return False


def short(text):
    return bool(text) and text.isalpha() and len(text) <= 3


def extract(case):
    if not tokens(case['reference']):
        return []
    expected, actual = tokens(case['reference']), tokens(case['text'])
    rows, mapping, observed = [], [], []
    for index, segment in enumerate(case['segments']):
        words = tokens(segment['text'])
        mapping.extend([index]*len(words))
        observed.extend(words)
        evidence = segment.get('recognition', {}).get('word_evidence', [])
        confidence = [float(w['confidence']) for w in evidence if isinstance(w.get('confidence'), (float, int))]
        complete = len(confidence) == len(evidence) and bool(confidence)
        details = segment.get('recognition', {})
        forced = bool(details.get('refinements') or details.get('unrecognized_audio') or
                      any(w.get('review_reason') for w in evidence))
        local = forced or any(w.get('needs_review') for w in evidence)
        rows.append(dict(case=case['id'], row=index, text=segment['text'], baseline=bool(segment.get('needs_review')),
                         confidence=confidence, complete=complete, forced=forced, local=local,
                         short=any(short(w) for w in words), term=any(is_term(w) for w in words), events=[]))
    if observed != actual:
        raise ValueError('Токены фраз не совпали с расшифровкой: '+case['id'])
    if not rows:
        rows.append(dict(case=case['id'], row=None, text='', baseline=False, confidence=[], complete=False,
                         forced=False, local=False, short=False, term=False, events=[]))
    deleted = inserted = 0
    for edit in word_edits(expected, actual):
        if edit['op'] == 'deletions':
            position = edit['reference_index']-deleted+inserted
            deleted += 1
        else:
            position = edit['hypothesis_index']
            inserted += edit['op'] == 'insertions'
        index = mapping[min(position, len(mapping)-1)] if mapping else 0
        value = edit['reference'] if edit['reference'] is not None else edit['hypothesis']
        rows[index]['events'].append(dict(edit, short=short(value), term=is_term(value)))
    if sum(len(row['events']) for row in rows) != case['word_errors']:
        raise ValueError('Изменился счётчик ошибок.')
    return rows


def flag(row, rule):
    if rule['kind'] == 'baseline' or not row['complete']:
        return row['baseline']
    if row['forced'] or rule['kind'] == 'local' and row['local']:
        return True
    score = sum(row['confidence'])/len(row['confidence']) if rule['kind'] == 'mean' else min(row['confidence'])
    return score < rule['threshold']


def ratio(a, b):
    return a/b if b else None


def measure(rows, rule):
    predicted = [flag(row, rule) for row in rows]
    tp = sum(p and bool(row['events']) for row, p in zip(rows, predicted))
    fp = sum(p and not row['events'] for row, p in zip(rows, predicted))
    fn = sum(not p and bool(row['events']) for row, p in zip(rows, predicted))
    tn = sum(not p and not row['events'] for row, p in zip(rows, predicted))
    result = dict(phrases=len(rows), tp=tp, fp=fp, fn=fn, tn=tn, precision=ratio(tp, tp+fp),
                  phrase_recall=ratio(tp, tp+fn), false_alarm_rate=ratio(fp, fp+tn), f1=ratio(2*tp, 2*tp+fp+fn))
    for group in ('all', 'short', 'term'):
        total = sum(sum(group == 'all' or e[group] for e in row['events']) for row in rows)
        caught = sum(sum(group == 'all' or e[group] for e in row['events']) for row, p in zip(rows, predicted) if p)
        clean = [p for row, p in zip(rows, predicted) if not row['events'] and (group == 'all' or row[group])]
        result[group] = dict(errors=total, detected=caught, error_recall=ratio(caught, total),
                             clean_phrases=len(clean), false_alerts=sum(clean), false_alarm_rate=ratio(sum(clean), len(clean)))
    return result


def run(args):
    if args.output.exists():
        raise ValueError('Укажи новую папку.')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/'outputs/recorder'))
    args.output.mkdir(parents=True)
    tune = json.loads(args.tune.read_text())
    baseline = dict(kind='baseline')
    rows = [row for case in tune['cases'] for row in extract(case)]
    before = measure(rows, baseline)
    trials = []
    for kind in ('local', 'min', 'mean'):
        for threshold in (.5, .55, .6, .65, .7, .75, .8, .85, .9, .95):
            rule = dict(kind=kind, threshold=threshold)
            trials.append(dict(rule=rule, score=measure(rows, rule)))
    eligible = [t for t in trials if t['score']['all']['error_recall'] >= before['all']['error_recall']
                and t['score']['false_alarm_rate'] <= before['false_alarm_rate']
                and t['score']['f1'] > before['f1']]
    best = max(eligible or trials, key=lambda t: (t['score']['f1'], t['score']['all']['error_recall'], -t['score']['false_alarm_rate']))
    frozen = dict(rule=best['rule'], selection='F1 по development; сохранение recall ошибок и снижение FPR предпочтительны',
                  training_eligible=bool(eligible), terms=sorted(TERMS), tune_sha256=audio_sha256(args.tune),
                  control_sha256=audio_sha256(args.control), script_sha256=audio_sha256(Path(__file__)),
                  labels='Levenshtein по эталону; пропуск относится к следующему слову, в конце к последнему. Полностью пустая речь — виртуальная фраза без флага.')
    (args.output/'frozen.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2)+'\n')
    # Контрольные флаги и ошибки вычисляются только после записи заморозки.
    control = json.loads(args.control.read_text())
    checks = [row for case in control['cases'] for row in extract(case)]
    cb, ca = measure(checks, baseline), measure(checks, best['rule'])
    passed = bool(eligible) and ca['all']['error_recall'] >= cb['all']['error_recall'] and ca['false_alarm_rate'] < cb['false_alarm_rate']
    for group in ('short', 'term'):
        if cb[group]['error_recall'] is not None:
            passed &= ca[group]['error_recall'] >= cb[group]['error_recall']
    proof = dict(frozen=frozen, tune=dict(baseline=before, candidate=best['score'], trials=trials),
                 control=dict(baseline=cb, candidate=ca, passed=bool(passed)),
                 rows=[dict(row, candidate=flag(row, best['rule'])) for row in checks],
                 limitations='Ошибки размечены сравнением с субтитрами, не ручным прослушиванием каждого слова. Словарь терминов ограничен. Полностью потерянные фразы не имеют интерфейсного флага.')
    (args.output/'result.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(rule=best['rule'], train_eligible=bool(eligible), control=proof['control']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tune', required=True, type=Path)
    parser.add_argument('--control', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    run(parser.parse_args())
