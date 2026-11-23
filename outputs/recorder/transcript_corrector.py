import hashlib,json,re,time
from pathlib import Path
from urllib.parse import quote
import illustrations
from learning_moments import safe_image_query
CACHE=Path(__file__).resolve().parent/'study/fact-checks'
EVENTS=[('Куликовская битва',r'куликовск\w*\s+битв\w*'),('Невская битва',r'невск\w*\s+битв\w*'),('Ледовое побоище',r'ледов\w*\s+побоищ\w*'),('Стояние на Угре',r'стояни\w*\s+на\s+угр\w*'),('Крещение Руси',r'крещени\w*\s+руси'),('Тверское восстание',r'тверск\w*\s+восстани\w*')]
NAMES=[('Иван Калита',r'\bИван\s+Калитто\b','Калита'),('Андрей Рублёв',r'\bАндрей\s+Рудл[её]в\b','Рубл'),('Феофан Грек',r'\b(?:Феотан|Феотан|Диафан|Пиатан)\s+Грек\b','Феофан')]

def reference(topic):
 CACHE.mkdir(parents=True,exist_ok=True);path=CACHE/(hashlib.sha256(topic.encode()).hexdigest()+'.json')
 try:
  saved=json.loads(path.read_text())
  if time.time()-saved.get('checked',0)<(604800 if saved.get('extract') else 300):return saved
 except (OSError,ValueError):pass
 pages=illustrations.wiki({'titles':topic,'redirects':1,'prop':'extracts|info','exintro':1,'explaintext':1,'inprop':'url'}).get('query',{}).get('pages',[])
 page=pages[0] if pages else {};text=page.get('extract','')[:2500]
 result={'checked':time.time(),'title':page.get('title',topic),'extract':text,'url':page.get('fullurl') or 'https://ru.wikipedia.org/wiki/'+quote(topic)}
 path.write_text(json.dumps(result,ensure_ascii=False));return result

def event_year(ref):
 opening=re.split(r'\n',ref.get('extract',''))[0]
 years=set(re.findall(r'(?<!\d)([12]\d{3}|[3-9]\d{2})(?=\s*(?:году|года|год|г\.|гг\.))',opening))
 return next(iter(years)) if len(years)==1 else None

def correct_segment(segment,topic,pattern,ref,kind):
 original=segment['text'];text=original;changes=[]
 if kind=='year':
  expected=event_year(ref)
  if not expected:return None
  for sentence in re.split(r'(?<=[.!?])\s+',original):
   if not re.search(pattern,sentence,re.I) or re.search(r'не\s+в|вместо|например|предполож|ошиб|раньше|позже|после|\bдо\b|годовщин|спустя|через',sentence,re.I):continue
   if not re.search(r'состоял|произош|начал|была|было|прошл|датиру|случил',sentence,re.I):continue
   dates=list(re.finditer(r'(?<!\d)([12]\d{3}|[3-9]\d{2})(?=\s*(?:году|года|год|г\.))',sentence))
   if len(dates)!=1 or dates[0].group(1)==expected:continue
   corrected=sentence[:dates[0].start(1)]+expected+sentence[dates[0].end(1):]
   text=text.replace(sentence,corrected,1);changes.append({'from':dates[0].group(1),'to':expected})
 else:
  match=re.search(pattern,original,re.I)
  if match:text=original[:match.start()]+topic+original[match.end():];changes.append({'from':match.group(),'to':topic})
 if not changes:return None
 return {'segment_id':segment['id'],'original':original,'text':text,'start':segment['start'],'kind':kind,'changes':changes,'source':{'title':ref['title'],'url':ref['url'],'evidence':ref['extract'][:600]}}

def proofread(report,subject,fetch=reference):
 if not re.search(r'истори|государственност',subject or '',re.I):return {'corrections':[],'status':'unsupported'}
 corrections={};queries=0;errors=0
 candidates=[(t,p,'year',None) for t,p in EVENTS]+[(t,p,'name',a) for t,p,a in NAMES]
 for moment in report.get('moments',[]):
  topic=safe_image_query(moment.get('image_query'),moment.get('quote',''))
  if topic and moment.get('kind')=='date' and topic not in [v[0] for v in candidates]:candidates.append((topic,re.escape(topic),'year',None))
 for topic,pattern,kind,anchor in candidates:
  matches=[s for s in report.get('segments',[]) if re.search(pattern,s.get('text',''),re.I)]
  if not matches or queries>=4:continue
  queries+=1
  try:ref=fetch(topic)
  except Exception:errors+=1;continue
  if not ref.get('extract') or (anchor and anchor.casefold() not in (ref['title']+' '+ref['extract']).casefold()):continue
  for segment in matches:
   prior=corrections.get(segment['id']);copy=dict(segment,text=prior['text'] if prior else segment['text'])
   change=correct_segment(copy,topic,pattern,ref,kind)
   if change:
    change['original']=segment['text'];change['sources']=(prior.get('sources',[prior['source']]) if prior else [])+[change['source']];corrections[segment['id']]=change
 return {'corrections':list(corrections.values()),'status':'partial' if errors else 'checked','checked_topics':queries}
