import argparse
import hashlib
import json
from pathlib import Path

def score(case,result):
    rows=case['rows'];report=result['report'];errors=[];seen={'summary':set(),'homework':set()};fallback=0
    if [(r['text'],r.get('start'),r.get('end')) for r in report['segments']]!=[(r['text'],r.get('start'),r.get('end')) for r in rows]:errors.append('source_changed')
    for field,anchors in [('summary',report.get('summary_evidence',[])),('homework',report.get('homework',[]))]:
        eligible=set(case['academic_rows' if field=='summary' else 'homework_rows'])
        for anchor in anchors:
            index=anchor.get('segment_id',-1)
            if not 0<=index<len(rows):errors.append(field+':index');continue
            row=rows[index]
            if anchor.get('quote')!=row['text'] or anchor.get('start')!=row.get('start') or anchor.get('end')!=row.get('end'):errors.append(field+':citation')
            if index not in eligible:errors.append(field+':role')
            seen[field].add(index)
            fallback+=int(anchor.get('selection_method')=='verbatim_fallback')
    if len(report.get('summary',[]))!=len(report.get('summary_evidence',[])):errors.append('missing_citation')
    positive=bool(case['academic_rows'] or case['homework_rows'])
    if positive:
        passed=result['status']=='ready' and len(seen['summary'])>=case['summary_min'] and seen['homework']==set(case['homework_rows']) and not report.get('local_summary_pending') and not errors
    else:
        passed=result['status']=='refused' and result.get('error')=='Не нашёл уверенных пунктов. Расшифровка сохранена' and not seen['summary'] and not seen['homework'] and not errors
    return dict(name=case['name'],partition=case['partition'],positive=positive,passed=passed,errors=errors,
        selected_summary=len(seen['summary']),selected_homework=len(seen['homework']),fallback_citations=fallback,status=result['status'],error=result.get('error'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('fixture',type=Path);parser.add_argument('directory',type=Path)
    parser.add_argument('--suffix',default='');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    fixture=json.loads(args.fixture.read_text());digest=hashlib.sha256(args.fixture.read_bytes()).hexdigest();report={}
    for variant in ['ilya','stable','candidate']:
        data=json.loads((args.directory/(variant+args.suffix+'.json')).read_text())
        if data['input_sha256']!=digest:raise ValueError('Разные входные данные')
        if [r['name'] for r in data['results']]!=[c['name'] for c in fixture['cases']]:raise ValueError('Разные примеры')
        rows=[score(c,r) for c,r in zip(fixture['cases'],data['results'])]
        report[variant]=dict(apk_sha256=data['apk_sha256'],input_sha256=digest,unicode_source=data.get('unicode_source'),
            positive=sum(c['positive'] for c in rows),positive_pass=sum(c['positive'] and c['passed'] for c in rows),
            negative=sum(not c['positive'] for c in rows),negative_pass=sum(not c['positive'] and c['passed'] for c in rows),
            errors=sum(len(c['errors']) for c in rows),fallback_citations=sum(c['fallback_citations'] for c in rows),cases=rows)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for variant,value in report.items():print(variant,{k:value[k] for k in ['positive_pass','positive','negative_pass','negative','errors','fallback_citations']})

if __name__=='__main__':main()
