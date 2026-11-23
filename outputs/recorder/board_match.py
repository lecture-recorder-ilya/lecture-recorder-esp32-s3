import math,re,wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def words(text):
    text=str(text).casefold().replace('ё','е')
    aliases={r'\\sin|\bsin\b':'синус',r'\\cos|\bcos\b':'косинус',r'\\lim|\blim\b':'предел',r'\bx\b':'икс',r'\by\b':'игрек',r'\bz\b':'зет',r'\balpha\b|α':'альфа',r'\bbeta\b|β':'бета'}
    for pattern,replacement in aliases.items():text=re.sub(pattern,replacement,text)
    stop=set('это есть для при как или что тут нам вам вот так нас вас его она они если тогда равно равен равна найти решение пример рисунок график фото доска'.split())
    terms=set()
    for word in re.findall(r'[а-яa-z]+',text):
        if len(word)<3 or word in stop:continue
        terms.add(re.sub(r'(иями|ами|ями|ого|ему|ому|ыми|ими|иях|ах|ях|ий|ый|ая|ое|ые|ие|ов|ев|ом|ам|ям|ую|ию|а|я|ы|и|у|ю|е)$','',word) if len(word)>5 else word)
    return terms

def start_ms(name,phone_meta=None):
    value=(phone_meta or {}).get('started_ms')
    if type(value) in (int,float) and math.isfinite(value):return float(value)
    match=re.match(r'lecture-(\d{4}-\d\d-\d\d)-(\d\d)-(\d\d)-(\d\d)-(\d+)',name)
    if not match:return None
    date,h,m,s,micro=match.groups()
    return datetime.fromisoformat(f'{date}T{h}:{m}:{s}').replace(tzinfo=ZoneInfo('Europe/Moscow')).timestamp()*1000+min(int(micro)/1000,999)

def locate(photo,lectures):
    anchor=None
    for lecture in lectures:
        duration=lecture['duration'];name=lecture['file']
        if photo.get('source_recording')==name and type(photo.get('offset_seconds')) in (int,float):
            offset=photo['offset_seconds']
            if math.isfinite(offset) and 0<=offset<=duration+60:anchor=(lecture,min(offset,duration),'recording');break
    if anchor is None:
        found=[]
        for lecture in lectures:
            if lecture.get('started_ms') is None:continue
            offset=(photo['captured_ms']-lecture['started_ms'])/1000
            if 0<=offset<=lecture['duration']+20:found.append((lecture,min(offset,lecture['duration']),'clock'))
        if len(found)!=1:return None
        anchor=found[0]
    lecture,offset,source=anchor
    query=words(photo.get('analysis',{}).get('visible_text',''))
    scored=[];rows=lecture.get('segments',[])
    for i,row in enumerate(rows):
        if not offset-600<=row['start']<=offset+60:continue
        window=rows[i:i+4];text=' '.join(s['text'] for s in window);shared=query&words(text)
        score=len(shared)/max(1,len(query))
        if len(shared)>=2 and score>=.45:scored.append((score,row['start'],sorted(shared)))
    method=source;start=offset;overlap=[]
    if scored:
        best=max(s[0] for s in scored);near=[s for s in scored if s[0]>=best-.03]
        picked=min(near,key=lambda s:abs(s[1]-offset))
        distant=[s for s in scored if abs(s[1]-picked[1])>60 and s[0]>=best-.03]
        if not distant or min(abs(s[1]-offset) for s in distant)>abs(picked[1]-offset)+60:
            _,start,overlap=picked;method=source+'+content'
    return {'file':lecture['file'],'start':start,'anchor_seconds':offset,'method':method,'visible_overlap':overlap}
