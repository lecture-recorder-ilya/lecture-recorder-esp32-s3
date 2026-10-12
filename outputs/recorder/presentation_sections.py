"""Presentation boundaries from explicit speech cues, not every speaker change."""
import re
START=re.compile(r'(?:сейчас|теперь)\s+(?:у нас\s+)?(?:выступит|выступает|будет выступать)|(?:предоставляю|передаю)\s+слово|тема\s+(?:моего|нашего)\s+(?:доклада|выступления|презентации)|(?:мой|наш|моя|наша)\s+(?:доклад|презентация)\s+(?:посвящ[её]н|на тему)',re.I)
END=re.compile(r'спасибо\s+(?:вам\s+)?за\s+(?:доклад|презентац|выступлен)|(?:верн[её]мся|продолжим)\s+(?:теперь\s+)?(?:к\s+)?(?:лекци|заняти)|спасибо\s+за\s+внимание',re.I)
ANNOUNCEMENT=re.compile(r'выступит|выступает|будет выступать|предоставляю|передаю',re.I)

def presentations(segments,duration):
 result=[];active=None
 for s in sorted(segments,key=lambda v:v['start']):
  text=s.get('text','')
  if START.search(text) and '?' not in text:
   if active and (s['start']-active['start']<15 or (active.get('announcement_id') is not None and not active.get('introduced') and not ANNOUNCEMENT.search(text) and s['start']-active['start']<90)):
    title=re.search(r'тема\s+(?:моего|нашего)\s+(?:доклада|выступления|презентации)\s*[:—-]?\s*(.+)',text,re.I)
    if title:active['title']=title.group(1).split('.')[0][:100]
    active['introduced']=True
    continue
   if active:active.update(end=s['start'],ongoing=False);result.append(active)
   title=re.search(r'тема\s+(?:моего|нашего)\s+(?:доклада|выступления|презентации)\s*[:—-]?\s*(.+)',text,re.I)
   active={'start':s['start'],'end':duration,'title':(title.group(1).split('.')[0][:100] if title else 'Выступление одногруппника'),'announcement_id':s['id'] if ANNOUNCEMENT.search(text) else None,'ongoing':True}
  elif active and END.search(text) and s['start']-active['start']>=10:
   active.update(end=s['end'],ongoing=False,closing_id=s['id']);result.append(active);active=None
 if active:result.append(active)
 return result

def roles(segments,sections,teacher_ranges=()):
 result={}
 for s in segments:
  role=None;basis=None
  for p in sections:
   if p['start']<=s['start']<p['end']:
    role='teacher' if s['id'] in (p.get('announcement_id'),p.get('closing_id')) and not re.search(r'спасибо\s+за\s+внимание',s['text'],re.I) else 'student'
    basis='speech_cue';break
  if any(min(s['end'],r['end'])-max(s['start'],r['start'])>=max(.5,(s['end']-s['start'])*.5) for r in teacher_ranges):role='teacher';basis='voice_estimate'
  if role:result[str(s['id'])]={'role':role,'basis':basis,'estimated':True}
 return result
