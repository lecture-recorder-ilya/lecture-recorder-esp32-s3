import math,re
SPACE=re.compile(r'\A\s|\s\B|(\s)\b')

def speech_windows(core,duration,padding=.32,merge_gap=1.0,max_seconds=22):
 groups=[]
 if max_seconds<=0:raise ValueError('Длина фрагмента должна быть положительной.')
 for start,end in sorted(core):
  start=max(0,float(start)-padding);end=min(duration,float(end)+padding)
  if end<=start:continue
  if groups and start-groups[-1][1]<=merge_gap and end-groups[-1][0]<=max_seconds:groups[-1]=(groups[-1][0],end)
  else:groups.append((start,end))
 bounded=[]
 for start,end in groups:
  while end-start>max_seconds:
   bounded.append((start,start+max_seconds));start+=max_seconds
  bounded.append((start,end))
 return bounded

def supported_words(result,core,emit_start=0,emit_end=float('inf')):
 tokens=result.tokens or [];times=result.timestamps or [];logprobs=result.logprobs or []
 if not core or not tokens or len(tokens)!=len(times) or len(tokens)!=len(logprobs):return []
 words=[];current=[]
 for token,t,lp in zip(tokens,times,logprobs):
  token=token.replace('▁',' ')
  parts=re.findall(r'\s+|\S+',token)
  for part in parts:
   if part.isspace():
    if current:words.append(current);current=[]
   else:current.append((part,float(t),float(lp)))
 if current:words.append(current)
 output=[]
 for word in words:
  lexical=[v for v in word if re.search(r'[^\W_]',v[0])]
  if not lexical:continue
  midpoint=(lexical[0][1]+lexical[-1][1])/2
  if not emit_start<=midpoint<emit_end:continue
  support=sum(any(a-.32<=t<=b+.32 for a,b in core) for _,t,_ in lexical)/len(lexical)
  confidence=math.exp(sum(lp for _,_,lp in lexical)/len(lexical))
  if support<.6 or confidence<.45:continue
  value=''.join(v[0] for v in word)
  output.append({'text':value,'start':lexical[0][1],'end':lexical[-1][1]+.04,'confidence':confidence})
 return output

def join_words(words):
 text=SPACE.sub(lambda m:' ' if m.group(1) else '', ' '.join(w['text'] for w in words)).strip()
 return re.sub(r'([.!?])(?=[А-ЯA-Z])',r'\1 ',text)

def supported_text(result,core,emit_start=0,emit_end=float('inf')):
 return join_words(supported_words(result,core,emit_start,emit_end))

MIN_UNRECOGNIZED_VOICE=.9

def unrecognized_voice(core,words,start,end):
 if not core or end<=start:return []
 coverage=sorted((w['start']-.13,w['end']+.13) for w in words)
 gaps=[]
 for a,b in core:
  left,right=max(a,start),min(b,end)
  if right-left<MIN_UNRECOGNIZED_VOICE:continue
  cursor=left
  for first,last in coverage:
   if last<=left:continue
   if first>=right:break
   if first-cursor>=MIN_UNRECOGNIZED_VOICE:gaps.append((cursor,first))
   cursor=max(cursor,last)
   if cursor>=right:break
  if right-cursor>=MIN_UNRECOGNIZED_VOICE:gaps.append((cursor,right))
 return gaps

def choose_candidate(ctc,rnnt):
 if not ctc:return rnnt
 if not rnnt:return ctc
 ctc_confidence=sum(w['confidence'] for w in ctc)/len(ctc)
 if ctc_confidence<.85:return ctc
 if len(rnnt)<len(ctc)*.65:return ctc
 if any(w['confidence']>=.65 and min(abs(w['start']-v['start']) for v in rnnt)>1.2 for w in ctc):return ctc
 return rnnt

def lexical(value):
 return ''.join(re.findall(r'[^\W_]',value.casefold().replace('ё','е')))

def refine_words(primary,secondary,character=()):
 from context_review import protected
 output=[dict(w) for w in primary];changes=[]
 def near(words,word):
  candidates=[(i,w) for i,w in enumerate(words) if abs(w['start']-word['start'])<=.32]
  return min(candidates,key=lambda v:abs(v[1]['start']-word['start'])) if candidates else (None,None)
 def anchored(i,j,words):
  left=i==0 and j==0 or i>0 and j>0 and lexical(primary[i-1]['text'])==lexical(words[j-1]['text']) and abs(primary[i-1]['start']-words[j-1]['start'])<=.32
  right=i==len(primary)-1 and j==len(words)-1 or i+1<len(primary) and j+1<len(words) and lexical(primary[i+1]['text'])==lexical(words[j+1]['text']) and abs(primary[i+1]['start']-words[j+1]['start'])<=.32
  return left and right
 char_clear=bool(character) and sum(w['confidence'] for w in character)/len(character)>=.95
 for i,original in enumerate(primary):
  key=lexical(original['text']);proposal=None;source=None
  j,other=near(secondary,original)
  if other and original['confidence']<.85 and other['confidence']>=max(.65,original['confidence']-.2):
   longer=lexical(other['text'])
   repeated=any(k!=i and lexical(w['text'])==longer and w['confidence']>=.7 for k,w in enumerate(primary))
   if len(key)>=3 and longer.startswith(key) and 1<=len(longer)-len(key)<=3 and repeated and anchored(i,j,secondary):proposal=other;source='second-acoustic-pass'
  if proposal is None and char_clear and original['confidence']<.8:
   j,other=near(character,original)
   if other and other['confidence']>=.9 and other['confidence']-original['confidence']>=.15 and lexical(other['text'])!=key and anchored(i,j,character):proposal=other;source='character-acoustic-pass'
  if proposal and (protected(original['text']) or protected(proposal['text'])):
   output[i]['needs_review']=True
   output[i]['review_reason']='protected_word_mismatch'
   continue
  if proposal:
   value=re.sub(r'[\W_]+$','',proposal['text']);suffix=re.search(r'[\W_]+$',original['text'])
   if original['text'][:1].isupper() and re.search(r'[а-яa-z]',original['text']):value=value[:1].upper()+value[1:]
   value+=suffix.group() if suffix else ''
   output[i]['text']=value
   changes.append({'from':original['text'],'to':value,'start':original['start'],'source':source})
 uncertain=[]
 for w in output:
  _,support=near(character,w) if char_clear else (None,None)
  confirmed=support and lexical(support['text'])==lexical(w['text']) and support['confidence']>=.9
  if w['confidence']<.7 and not confirmed:uncertain.append(w['text'])
 return output,changes,uncertain

def prepare(samples,highpass=True):
 import numpy as np
 x=np.asarray(samples,dtype=np.float32).copy()
 if not len(x):return x
 if highpass:
  from scipy.signal import butter,sosfilt
  x=sosfilt(butter(2,70,fs=16000,btype='highpass',output='sos'),x).astype(np.float32)
 from speech_audio import normalize_audio
 return normalize_audio(x)
