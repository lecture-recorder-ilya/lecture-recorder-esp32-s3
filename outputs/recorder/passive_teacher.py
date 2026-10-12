"""Conservative per-recording dominant-voice estimate; never removes audio/text."""
import math

def unit(vector):
 length=math.sqrt(sum(float(v)**2 for v in vector))
 return [float(v)/length for v in vector] if length>1e-8 else None

def dot(a,b):return sum(x*y for x,y in zip(a,b)) if len(a)==len(b) else -1

def observe(state,vector,start,end):
 vector=unit(vector)
 if vector is None or end-start<5:return state
 if start<state.get('last_end',0):return state
 groups=state.setdefault('groups',[])
 scores=[max(dot(vector,r) for r in g['references']) for g in groups]
 best=max(range(len(scores)),key=scores.__getitem__) if scores else None
 similarity=scores[best] if best is not None else 0
 if best is None or similarity<.65:
  if len(groups)>=4:
   state['last_end']=end;return state
  best=len(groups);groups.append({'references':[vector],'seconds':0,'samples':0});similarity=1
 group=groups[best];group['samples']+=1;group['seconds']+=min(8,end-start)
 # Keep several strong exemplars rather than a drifting average of noisy clips.
 if similarity>=.8 and len(group['references'])<4:group['references'].append(vector)
 ranges=state.setdefault('ranges',[]);ranges.append({'start':start,'end':end,'group':best,'similarity':round(similarity,3)})
 state['ranges']=[r for r in ranges if r['end']>end-300];state['last_end']=end
 ranking=sorted(range(len(groups)),key=lambda i:groups[i]['seconds'],reverse=True)
 leader=ranking[0];runner=groups[ranking[1]]['seconds'] if len(ranking)>1 else 0
 g=groups[leader]
 # A single short shout or one clean sample cannot elect the lecturer.
 state['teacher']=leader if g['seconds']>=60 and g['samples']>=8 and g['seconds']>=runner*1.8 else None
 return state

def public(state):
 teacher=state.get('teacher');known=type(teacher) is int
 return {'status':'probable' if known else 'learning',
         'message':'Вероятный голос преподавателя определён автоматически' if known else 'Определяю голос преподавателя по длительной речи',
         'teacher_ranges':[{'start':r['start'],'end':r['end']} for r in state.get('ranges',[]) if known and r['group']==teacher and r['similarity']>=.8],
         'sample_seconds':round(sum(g['seconds'] for g in state.get('groups',[])),1)}

def sustained_window(segments,now):
 # ASR often splits one continuous explanation into several short sentences.
 chain=[]
 for segment in sorted(segments,key=lambda s:s['start']):
  if now-segment['end']>35:continue
  if chain and segment['start']-chain[-1]['end']>.5:chain=[]
  chain.append(segment)
 if not chain:return None
 end=chain[-1]['end'];start=max(chain[0]['start'],end-8)
 speech=sum(max(0,min(end,s['end'])-max(start,s['start'])) for s in chain)
 text=' '.join(s.get('text','') for s in chain if s['end']>start)
 return (start,end) if speech>=6 and len(text.split())>=10 else None
