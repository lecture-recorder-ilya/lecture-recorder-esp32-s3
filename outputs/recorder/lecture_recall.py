import re
from pathlib import Path
from speech_context import context_for_recording
CUE=re.compile(r'(?:на|в)\s+(?:предыдущей|прошлой)\s+(?:лекции|паре|занятии)|(?:я|мы)\s+(?:говорил[аи]?|обсуждали|разбирали)\s+(?:об этом\s+)?(?:на\s+прошлой|в\s+прошлый\s+раз)',re.I)

def cue_query(segments,now):
 rows=sorted(segments,key=lambda s:s['start'])
 hits=[i for i,s in enumerate(rows) if now-s['end']<180 and CUE.search(s.get('text',''))]
 if not hits:return None
 index=hits[-1];cue=rows[index]
 if now-cue['end']<5:return None
 query=' '.join(s['text'] for s in rows[index:index+3] if s['start']-cue['start']<35)[:700]
 return {'start':cue['start'],'query':query}

def passages(root,current,read):
 subject=context_for_recording(current,root=root)['subject'];files={}
 for suffix in ('.live.json','.transcript.json'):
  for p in (root/'analysis').glob('*'+suffix):
   name=p.name[:-len(suffix)]+'.wav'
   if name>=current or not (root/'recordings'/name).exists():continue
   if subject and context_for_recording(name,root=root)['subject']!=subject:continue
   files[name]=p
 items=[]
 for name in sorted(files,reverse=True)[:3]:
  report=read(files[name]);segments=report.get('segments',[])
  for i in range(0,len(segments),3):
   rows=segments[i:i+6]
   if not rows:continue
   items.append({'file':name,'start':rows[0]['start'],'end':rows[-1]['end'],'text':' '.join(s['text'] for s in rows)[:1200],'subject':subject})
 return items

def shortlist(query,items,limit=120):
 words=set(re.findall(r'[а-яё]{4,}',query.casefold()))
 score=lambda item:sum(any(word[:5] in token for token in re.findall(r'[а-яё]+',item['text'].casefold())) for word in words)
 return sorted(items,key=score,reverse=True)[:limit]

def ranked_results(items,scores):
 ranked=sorted(zip(items,scores),key=lambda pair:pair[1],reverse=True);result=[]
 threshold=max(.78,(ranked[0][1]-.02) if ranked else .78)
 for item,score in ranked:
  if score<threshold:continue
  if any(v['file']==item['file'] and abs(v['start']-item['start'])<30 for v in result):continue
  result.append(dict(item,score=round(float(score),3)))
  if len(result)>=3:break
 return result
