"""Проверить сохранность текста/таймкодов/меток и описать отвергнутые отсечения."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from evaluate_asr import tokens, summarize_scores


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def cases(report):return {r['id']:r for r in report['cases'] if r['repeat']==0}


def errors_by_segment(case):
    mapping=[i for i,s in enumerate(case['segments']) for _ in tokens(s['text'])]
    result=[[] for _ in case['segments']];deleted=inserted=0
    for edit in case['word_edits']:
        if edit['op']=='deletions':
            position=edit['reference_index']-deleted+inserted;deleted+=1
        else:
            position=edit['hypothesis_index'];inserted+=edit['op']=='insertions'
        if mapping:result[mapping[max(0,min(position,len(mapping)-1))]].append(edit)
    return result


def compare(before,after,ids):
    if before['model_sha256']!=after['model_sha256'] or before['dependencies_sha256']!=after['dependencies_sha256']:
        raise ValueError('Изменены модель или runtime')
    a,b=cases(before),cases(after);alerts=[];old_true=0
    call_keys=('primary_calls','clean_calls','onset_calls')
    for name in ids:
        x,y=a[name],b[name]
        if (x['pcm_sha256'],x['reference'],x['text'])!=(y['pcm_sha256'],y['reference'],y['text']):raise ValueError('Изменён текст или вход '+name)
        if len(x['segments'])!=len(y['segments']):raise ValueError('Изменились группы')
        errors=errors_by_segment(x)
        for i,(s,t) in enumerate(zip(x['segments'],y['segments'],strict=True)):
            if {k:v for k,v in s.items() if k!='needs_review'}!={k:v for k,v in t.items() if k!='needs_review'}:raise ValueError('Изменились границы '+name)
            if s['needs_review']:
                old_true+=1
                if not t['needs_review']:raise ValueError('Снят прежний флаг '+name)
            elif t['needs_review']:
                alerts.append(dict(id=name,phrase=t['text'],reference=x['reference'],errors=errors[i]))
        if any(x.get(k,0)!=y.get(k,0) for k in call_keys):raise ValueError('Добавлен проход '+name)
    return dict(before=summarize_scores([a[n] for n in ids]),after=summarize_scores([b[n] for n in ids]),
                text_timing_groups_equal=True,old_true_flags_preserved=old_true,removed_flags=0,
                new_alerts=alerts,new_alerts_on_erroneous_phrases=sum(bool(r['errors']) for r in alerts),
                new_alerts_on_correct_phrases=sum(not r['errors'] for r in alerts),
                extra_model_calls=0,calls={k:sum(a[n].get(k,0) for n in ids) for k in call_keys})


def audit(root,output):
    before=read(root/'control-normal.json');diagnostic=read(root/'control-observe.json');after=read(root/'control-confidence.json')
    b,d=cases(before),cases(diagnostic)
    for name in b:
        if (b[name]['pcm_sha256'],b[name]['segments'])!=(d[name]['pcm_sha256'],d[name]['segments']):raise ValueError('Диагностика изменила ответ')
    cohorts={}
    for label,manifest in [('control99','control99.json'),('new_voices9','new-voices2/manifest.json'),('new_noise16','new-noise2/manifest.json')]:
        ids=[r['id'] for r in read(root/manifest)];cohorts[label]=compare(before,after,ids)
    cohorts['independent37']=compare(read(root/'independent-base.json'),read(root/'independent-confidence.json'),list(cases(read(root/'independent-base.json'))))
    cohorts['tune76']=compare(read(root/'tune-observe.json'),read(root/'tune-confidence.json'),list(cases(read(root/'tune-observe.json'))))
    original=read(root/'tune-observe.json');index=cases(original);policies={}
    for policy in ['greedy-blank','onset-single']:
        report=read(root/('tune-'+policy+'.json'));rows=cases(report)
        changed=[dict(id=n,reference=index[n]['reference'],before=index[n]['text'],after=r['text'],
                      errors_before=index[n]['word_errors'],errors_after=r['word_errors'],
                      previously_correct=index[n]['word_errors']==0) for n,r in rows.items() if r['text']!=index[n]['text']]
        policies[policy]=dict(summary=report['summary'],changes=changed,
                              voice_turned_empty=[r for r in changed if r['reference'] and r['before'] and not r['after']],
                              onset_calls_before=sum(r['onset_calls'] for r in index.values()),
                              onset_calls_after=sum(r['onset_calls'] for r in rows.values()),
                              onset_seconds_before=sum(r['onset_seconds'] for r in index.values()),
                              onset_seconds_after=sum(r['onset_seconds'] for r in rows.values()))
    files=[p for p in root.glob('*.json') if p.name!=output.name]
    result=dict(base='cd879d2',cohorts=cohorts,rejected_filters=policies,
                probe_did_not_change_outputs=True,
                source_candidate_sha256=after['sources_sha256'],model_sha256=after['model_sha256'],
                artifacts_root=os.path.relpath(root, output.parent),artifacts_sha256={str(p.relative_to(root)):sha(p) for p in files},
                limits='Ошибки фраз по корпусному эталону и фиксированному выравниванию; ручное прослушивание не выполнено. Контексты и их варианты зависимы. JVM на Mac, не телефон.')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({n:dict(new_alerts=len(c['new_alerts']),errors=c['new_alerts_on_erroneous_phrases'],correct=c['new_alerts_on_correct_phrases'],old_flags=c['old_true_flags_preserved']) for n,c in cohorts.items()},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Укажи новый результат')
    audit(args.root,args.output)
