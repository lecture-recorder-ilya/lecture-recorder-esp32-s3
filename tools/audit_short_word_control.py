"""Посчитать сохранность коротких слов; простые отсечения только диагностические."""
import argparse
import hashlib
import json
from pathlib import Path

from evaluate_asr import score, summarize_scores, tokens


RULES = ('single_word', 'single_conf_below_070', 'single_span_over_1s')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(case, rule):
    kept = []
    for window in case['windows']:
        words = window['final']
        lexical = [w for w in words if tokens(w['word'])]
        drop = False
        if len(lexical) == 1:
            word = lexical[0]
            drop = (rule == 'single_word' or
                    rule == 'single_conf_below_070' and word['conf'] < .70 or
                    rule == 'single_span_over_1s' and word['end']-word['start'] > 1)
        if not drop:
            kept.extend(words)
    return ' '.join(w['word'] for w in kept)


def retained(target, reference, text):
    equivalents = {target, '3'} if target == 'три' else {target}
    wanted = sum(t in equivalents for t in tokens(reference))
    found = sum(t in equivalents for t in tokens(text))
    return min(wanted, found), wanted


def measure(cases, manifest, texts):
    results, labels = [], []
    for case in cases:
        meta = manifest[case['id']]
        text = texts[case['id']]
        results.append(dict(id=case['id'], subset=case['subset'], duration=case.get('duration',0),
                            **score(case['reference'], text)))
        if meta.get('target'):
            before, wanted = retained(meta['target'], case['reference'], case['text'])
            after, _ = retained(meta['target'], case['reference'], text)
            labels.append(dict(id=case['id'], subset=case['subset'], target=meta['target'],
                               reference=case['reference'], baseline=case['text'], after=text,
                               expected=wanted, before=before, retained=after,
                               added_losses=max(0, before-after)))
    def group(rows):
        return dict(cases=len(rows), expected=sum(r['expected'] for r in rows),
                    retained=sum(r['retained'] for r in rows),
                    baseline_retained=sum(r['before'] for r in rows),
                    added_losses=sum(r['added_losses'] for r in rows))
    summary=summarize_scores(results)
    summary.pop('elapsed_seconds',None);summary.pop('real_time_factor',None)
    return dict(summary=summary, targets={t:group([r for r in labels if r['target']==t]) for t in ('не','три','да')},
                subsets={s:group([r for r in labels if r['subset']==s]) for s in sorted({r['subset'] for r in labels})}, rows=labels)


def first_cases(report):
    cases = [r for r in report['cases'] if r['repeat']==0]
    if len({r['id'] for r in cases}) != len(cases):
        raise ValueError('Повторяющиеся ID')
    return cases


def candidate_texts(baseline, candidate):
    index = {r['id']:r for r in candidate}
    if len(index) != len(baseline):
        raise ValueError('Другой набор кандидата')
    for row in baseline:
        other = index[row['id']]
        if row['pcm_sha256'] != other['pcm_sha256'] or row['reference'] != other['reference']:
            raise ValueError('Изменился вход или эталон')
    return {k:v['text'] for k,v in index.items()}


def audit(args):
    if args.output.exists():
        raise ValueError('Укажи новый результат')
    data = json.loads(args.baseline.read_text());cases=first_cases(data)
    manifest = {r['id']:r for r in json.loads(args.manifest.read_text())}
    result = dict(baseline=measure(cases,manifest,{r['id']:r['text'] for r in cases}),
                  baseline_sha256=sha(args.baseline), manifest_sha256=sha(args.manifest),
                  script_sha256=sha(Path(__file__)), diagnostic_plan_sha256=sha(args.plan),
                  sources_sha256=data['sources_sha256'], model_sha256=data['model_sha256'],
                  diagnostic_only=True, diagnostics={})
    for rule in RULES:
        result['diagnostics'][rule]=measure(cases,manifest,{r['id']:replay(r,rule) for r in cases})
    if args.candidate:
        other = json.loads(args.candidate.read_text())
        result['candidate']=measure(cases,manifest,candidate_texts(cases,first_cases(other)))
        result['candidate_sha256']=sha(args.candidate)
    repeated = {r['id']:r for r in data['cases'] if r['repeat']==1}
    result['baseline_repeats_exact'] = (all(r['segments']==repeated[r['id']]['segments'] for r in cases)
                                         if len(repeated)==len(cases) else None)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:{'summary':v['summary'],'targets':v['targets']} for k,v in [('baseline',result['baseline']),*result['diagnostics'].items()]},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path);parser.add_argument('manifest',type=Path)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--candidate',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    audit(parser.parse_args())
