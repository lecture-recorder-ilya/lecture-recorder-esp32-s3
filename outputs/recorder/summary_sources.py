"""Привязки конспекта к текущей расшифровке; неоднозначность не угадываем."""
import copy
import hashlib
import math
import re

NOTICE='Источник нужно сверить.'
WARNING='Источники конспекта:'
ACTIVE=('start','end','segment_id','source_fingerprint')


def norm(text):return re.sub(r'\s+',' ',str(text)).strip().lower()


def fingerprint(rows,first=0):
    parts=[]
    for index,row in enumerate(rows,first):
        parts.append('|'.join((str(row.get('id',index)),str(math.floor(row['start']*1000+.5)),
                               str(math.floor(row['end']*1000+.5)),norm(row['text']))))
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def matches(quote,rows):
    target=norm(quote);found=[]
    for first in range(len(rows)):
        text='';span=[]
        for row in rows[first:]:
            start,end=row.get('start'),row.get('end')
            if (type(start) not in (int,float) or type(end) not in (int,float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end
                or span and not -.25<=start-span[-1]['end']<=2):break
            span.append(row);text=norm(text+' '+row.get('text',''))
            if not target.startswith(text):break
            if text==target:
                found.append((first,list(span)));break
    return found


def bind(anchor,rows,fresh=False):
    result=copy.deepcopy(anchor);candidates=matches(result.get('quote',''),rows)
    trusted=[(first,span) for first,span in candidates if not any(r.get('needs_review') and not r.get('reviewed') for r in span)]
    prior_hash=result.get('source_fingerprint') or result.get('original_source',{}).get('source_fingerprint')
    precise=[(first,span) for first,span in trusted if prior_hash==fingerprint(span,first)]
    if fresh and not precise:
        precise=[(first,span) for first,span in trusted if result.get('start')==span[0]['start'] and result.get('end')==span[-1]['end']
                 and result.get('segment_id') in (first,span[0].get('id',first))]
    selected=precise[0] if len(precise)==1 else trusted[0] if len(candidates)==len(trusted)==1 else None
    if selected:
        first,span=selected
        shifted=result.get('start')!=span[0]['start'] or result.get('end')!=span[-1]['end'] or result.get('segment_id')!=span[0].get('id',first)
        if shifted and 'original_source' not in result:result['original_source']={k:result[k] for k in ('quote',*ACTIVE) if k in result}
        result.update(start=span[0]['start'],end=span[-1]['end'],segment_id=span[0].get('id',first),
                      source_fingerprint=fingerprint(span,first),source_status='confirmed')
        if shifted:result['source_rebound']=True
        result.pop('source_note',None);result.pop('source_reason',None)
    else:
        result.setdefault('original_source',{k:result[k] for k in ('quote',*ACTIVE) if k in result})
        for key in ACTIVE:result.pop(key,None)
        result.update(source_status='needs_review',source_note=NOTICE,
                      source_reason='ambiguous' if len(candidates)>1 else 'uncertain' if candidates else 'not_found')
    return result


def reconcile(report,fresh=False):
    result=copy.deepcopy(report);rows=result.get('segments') or [];pending=0
    points=result.get('summary') or [];sources=result.get('summary_evidence') or []
    overview_derived='overview' in result and result['overview']==' '.join(points[:3])[:1500]
    anchors=[]
    for index,point in enumerate(points):
        anchor=sources[index] if index<len(sources) and isinstance(sources[index],dict) else dict(quote=point)
        original=anchor.get('source_point',point)
        anchor=bind(anchor,rows,fresh)
        if anchor['source_status']=='needs_review':
            anchor['source_point']=original;points[index]=original+'\n'+NOTICE;pending+=1
        else:
            points[index]=original;anchor.pop('source_point',None)
        anchors.append(anchor)
    if 'summary' in result:result['summary_evidence']=anchors
    if overview_derived:result['overview']=' '.join(points[:3])[:1500]
    for field in ('homework','formulas','formula_review','highlights'):
        for index,item in enumerate(result.get(field) or []):
            anchor=bind(item,rows,fresh)
            if anchor['source_status']=='needs_review':
                pending+=1
                if field=='homework':
                    original=anchor.setdefault('source_point',anchor.get('task',anchor.get('quote','')))
                    anchor['task']=original+'\n'+NOTICE;anchor.pop('deadline',None)
            elif field=='homework' and 'source_point' in anchor:anchor['task']=anchor.pop('source_point')
            result[field][index]=anchor
    warnings=[x for x in result.get('warnings',[]) if not str(x).startswith(WARNING)]
    if pending:warnings.append(f'{WARNING} нужно сверить — {pending}.')
    if warnings or 'warnings' in result:result['warnings']=warnings
    return result
