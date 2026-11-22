"""Сравнить текст, флаги, таймкоды и регрессии Android на неизменных PCM."""
import argparse
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path

from evaluate_asr import tokens


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def target_count(target,text):
    allowed={target,'3'} if target=='три' else {target}
    return sum(t in allowed for t in tokens(text))


def review_membership(before,after):
    def members(case):
        return [(token,bool(s['needs_review'])) for s in case['segments'] for token in tokens(s['text'])]
    a,b=members(before),members(after)
    matcher=SequenceMatcher(a=[w for w,_ in a],b=[w for w,_ in b],autojunk=False)
    marked=unmarked=common=0
    for block in matcher.get_matching_blocks():
        for i in range(block.size):
            old,new=a[block.a+i][1],b[block.b+i][1]
            common+=1;marked+=not old and new;unmarked+=old and not new
    return dict(unchanged_words_compared=common,newly_marked=marked,no_longer_marked=unmarked,
                flagged_phrases_before=sum(s['needs_review'] for s in before['segments']),
                flagged_phrases_after=sum(s['needs_review'] for s in after['segments']))


def compare(base,candidate,manifest):
    first=lambda data:{r['id']:r for r in data['cases'] if r['repeat']==0}
    before,after=first(base),first(candidate)
    if before.keys()!=after.keys():raise ValueError('Разные наборы')
    flags=lambda case:[(s['text'],s['needs_review']) for s in case['segments']]
    rows=[]
    for name,a in before.items():
        b=after[name]
        if (a['pcm_sha256'],a['reference'])!=(b['pcm_sha256'],b['reference']):raise ValueError('Изменён вход')
        reasons=[]
        for key in ('word_errors','hallucinated_words'):
            if b[key]>a[key]:reasons.append(key)
        for key in ('numeric_tokens','negations'):
            for direction in ('missed','extra'):
                if b[key][direction]>a[key][direction]:reasons.append(key+'.'+direction)
        target=manifest[name].get('target')
        if target and target_count(target,b['text'])<min(target_count(target,a['text']),target_count(target,a['reference'])):
            reasons.append('lost_target_'+target)
        row=dict(id=name,reference=a['reference'],before=a['text'],after=b['text'],
                 errors_before=a['word_errors'],errors_after=b['word_errors'],
                 edits_before=a['word_error_breakdown'],edits_after=b['word_error_breakdown'],
                 changed_text=a['text']!=b['text'],changed_flags_or_groups=flags(a)!=flags(b),
                 changed_timestamps=a['segments']!=b['segments'],regressions=reasons,
                 review_membership=review_membership(a,b),
                 segments_before=a['segments'],segments_after=b['segments'])
        rows.append(row)
        for segment in b['segments']:
            if not 0<=segment['start']<segment['end']<=b['duration']+.001:
                raise ValueError('Таймкод вне WAV: '+name)
            for start,end,millis in segment.get('word_times',[]):
                utf16_length=len(segment['text'].encode('utf-16-le'))//2
                if not 0<=start<end<=utf16_length or not segment['start']-.001<=millis/1000<=segment['end']+.001:
                    raise ValueError('Невалидная привязка слова: '+name)
    return dict(summary_before=base['summary'],summary_after=candidate['summary'],
                changed_text=sum(r['changed_text'] for r in rows),
                changed_flags_or_groups=sum(r['changed_flags_or_groups'] for r in rows),
                changed_timestamps=sum(r['changed_timestamps'] for r in rows),
                review_membership={k:sum(r['review_membership'][k] for r in rows)
                                   for k in ('unchanged_words_compared','newly_marked','no_longer_marked','flagged_phrases_before','flagged_phrases_after')},
                changed_review_cases=sum(bool(r['review_membership']['newly_marked'] or r['review_membership']['no_longer_marked']) for r in rows),
                regrouped_only=sum(r['changed_flags_or_groups'] and not r['changed_text'] and not r['review_membership']['newly_marked'] and not r['review_membership']['no_longer_marked'] for r in rows),
                regressions=[r for r in rows if r['regressions']],cases=rows,
                passes_before={k:sum(r.get(k,0) for r in before.values()) for k in ('primary_calls','clean_calls','onset_calls')},
                passes_after={k:sum(r.get(k,0) for r in after.values()) for k in ('primary_calls','clean_calls','onset_calls')})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('base','candidate','manifest'):parser.add_argument(name,type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Укажи новый результат')
    result=compare(json.loads(args.base.read_text()),json.loads(args.candidate.read_text()),
                   {r['id']:r for r in json.loads(args.manifest.read_text())})
    result.update(inputs_sha256={name:sha(getattr(args,name)) for name in ('base','candidate','manifest')},
                  script_sha256=sha(Path(__file__)))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('cases','regressions')},ensure_ascii=False,indent=2))
