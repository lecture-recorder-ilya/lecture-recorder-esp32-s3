"""Grounded dates and illustration topics, anchored to the recorded words."""
import re
from historical_people import identified_people

def norm(text):return re.sub(r'\s+',' ',str(text)).strip().casefold()

def safe_image_query(query,quote):
    if not isinstance(query,str):return None
    query=query.strip()
    if not 3<=len(query)<=70 or re.search(r'[\d@:/<>\\]|(?:преподавател|студент|телефон|адрес)',query,re.I):return None
    if not re.fullmatch(r'[\w\s()«»—–-]+',query):return None
    return query if norm(query) in norm(quote) else None

def date_supported(date,quote):
    if not isinstance(date,str) or not date.strip() or len(date)>80:return False
    if norm(date) in norm(quote):return True
    if not re.fullmatch(r'\s*\d{3,4}(?:\s*[-–]\s*\d{3,4})?(?:\s*г(?:г|од[ауыов]*)?\.?)?\s*',date,re.I):return False
    numbers=re.findall(r'\b\d{3,4}\b',date)
    return bool(numbers) and all(re.search(r'(?<!\d)'+re.escape(n)+r'(?!\d)',quote) for n in numbers)

def merge_moments(items):
    seen=set();result=[]
    for item in sorted(items,key=lambda v:v['start']):
        key=(item['segment_id'],item['kind'],norm(item.get('date','')),norm(item['title']))
        if key not in seen:seen.add(key);result.append(item)
    return result

def dated_segments(segments,subject):
    if not subject or not re.search('истори|государственност',subject,re.I):return []
    result=[]
    for segment in segments:
        text=segment.get('text','')
        # Require a year/century marker, not arbitrary counts or audio timestamps.
        for match in re.finditer(r'(?<!\d)([3-9]\d{2}|[12]\d{3})(?:\s*[-–]\s*([12]\d{3}))?\s*(?:году|год[аыов]*|гг?\.?)(?![а-я])',text,re.I):
            date=match.group(1)+(('–'+match.group(2)) if match.group(2) else '')
            sentence=next((v.strip() for v in re.split(r'(?<=[.!?])\s+',text) if match.group(0) in v),text)
            result.append({'kind':'date','date':date,'title':'Дата из объяснения','description':sentence[:500],'quote':text,'segment_id':segment['id'],'start':segment['start'],'end':segment['end'],'image_query':None})
    return merge_moments(result)

PUBLIC_TOPICS=(r'Куликовск[а-я]+ битв[а-я]+',r'Золот[а-я]+ Орд[а-я]+',r'Московск[а-я]+ (?:государств[а-я]+|княжеств[а-я]+)',r'стояни[а-я]+ на Угр[а-я]+',r'Невск[а-я]+ битв[а-я]+',r'Ледов[а-я]+ побоищ[а-я]+',r'Смутн[а-я]+ врем[а-я]+',r'электрическ[а-я]+ пол[а-я]+',r'магнитн[а-я]+ пол[а-я]+',r'закон[а-я]* Ньютон[а-я]+',r'Отечественн[а-я]+ войн[а-я]+',r'Бородинск[а-я]+ (?:битв[а-я]+|сражени[а-я]+)',r'Перв[а-я]+ миров[а-я]+ войн[а-я]+',r'Втор[а-я]+ миров[а-я]+ войн[а-я]+',r'Крещени[а-я]+ Руси')

def public_topic(text):
    for pattern in PUBLIC_TOPICS:
        match=re.search(pattern,text,re.I)
        if match:return match.group(0)
    return None

def moments_for_report(report,subject):
    items=list(report.get('moments') or [])
    date_keys={(v.get('segment_id'),v.get('date')) for v in items}
    for item in dated_segments(report.get('segments',[]),subject):
        if (item['segment_id'],item['date']) not in date_keys:items.append(item)
    # Only known full public identities in historical context, not roll-call names.
    if re.search(r'истори|государственност',subject or '',re.I):
        seen_people=set();segments=report.get('segments',[])
        for index,segment in enumerate(segments):
            neighbors=[v for v in segments[max(0,index-1):index+2] if abs(v['start']-segment['start'])<15]
            context=' '.join(v['text'] for v in neighbors)
            for query,mention in identified_people(segment.get('text',''),context):
                if query in seen_people or len(seen_people)>=12:continue
                seen_people.add(query)
                items.append({'kind':'person','date':None,'title':query,'description':'Историческая личность, упомянутая в объяснении.','quote':segment['text'],'context':context,'segment_id':segment['id'],'start':segment['start'],'end':segment['end'],'image_query':query})
    # Existing reports can gain a few grounded illustrations without rerunning the LLM.
    for segment in report.get('segments',[]):
        query=public_topic(segment.get('text',''))
        if not query:continue
        related=next((v for v in items if v['segment_id']==segment['id']),None)
        if related:related['image_query']=related.get('image_query') or query
        elif not any(norm(v.get('image_query',''))==norm(query) for v in items):
            items.append({'kind':'concept','date':None,'title':query,'description':segment['text'][:500],'quote':segment['text'],'segment_id':segment['id'],'start':segment['start'],'end':segment['end'],'image_query':query})
        if sum(bool(v.get('image_query')) for v in items)>=6:break
    for item in items:
        if item.get('date') and not item.get('image_query'):
            item['image_query']=safe_image_query(item.get('title'),item.get('quote',''))
    return merge_moments(items)
