"""Local adaptive Russian ASR with voiced-word evidence; originals remain untouched."""
import threading,math,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parent.parent
MODEL=PROJECT/'work/models/gigaam';RNNT=PROJECT/'work/models/gigaam-rnnt'
CHAR=PROJECT/'work/models/gigaam-beam'
ENGINE='GigaAM-v3-3pass-phrases-v12-units'

def ready():
 return all(p.exists() for p in [MODEL/'v3_e2e_ctc.int8.onnx',MODEL/'v3_e2e_ctc_vocab.txt',PROJECT/'work/models/gigaam-manifest.json',RNNT/'v3_e2e_rnnt_encoder.onnx',RNNT/'v3_e2e_rnnt_decoder.onnx',RNNT/'v3_e2e_rnnt_joint.onnx',RNNT/'v3_e2e_rnnt_vocab.txt',PROJECT/'work/models/gigaam-rnnt-manifest.json',CHAR/'v3_ctc.onnx',CHAR/'v3_vocab.txt',PROJECT/'work/models/gigaam-beam-manifest.json'])

class Decoder:
 def __init__(self, threads=None):
  from power_budget import decoder_threads
  self.threads = decoder_threads() if threads is None else threads
  self.models = {}
  self.lock = threading.Lock()
  self.last = {}
 def close(self):
  with self.lock:self.models.clear()
 def _load(self,kind):
  if kind not in self.models:
   import onnx_asr,onnxruntime as rt
   options=rt.SessionOptions();options.intra_op_num_threads=self.threads;options.inter_op_num_threads=1;options.execution_mode=rt.ExecutionMode.ORT_SEQUENTIAL
   options.add_session_config_entry('session.intra_op.allow_spinning','0');options.add_session_config_entry('session.inter_op.allow_spinning','0')
   name='gigaam-v3-ctc' if kind=='char' else 'gigaam-v3-e2e-'+kind
   path=CHAR if kind=='char' else RNNT if kind=='rnnt' else MODEL
   self.models[kind]=onnx_asr.load_model(name,path=path,quantization='int8' if kind=='ctc' else None,sess_options=options,providers=['CPUExecutionProvider']).with_timestamps()
  return self.models[kind]
 def _retry_original(self, samples, cleaned, speech, start, end):
  import numpy as np
  from asr_guard import lexical, prepare, supported_words
  original=prepare(samples,highpass=False)
  if np.array_equal(original,cleaned, equal_nan=True):return []
  ctc=supported_words(self._load('ctc').recognize(original,sample_rate=16000),speech,start,end)
  if not ctc or min(word['confidence'] for word in ctc)<.75:return []
  rnnt=supported_words(self._load('rnnt').recognize(original,sample_rate=16000),speech,start,end)
  if len(ctc)!=len(rnnt):return []
  for left,right in zip(ctc,rnnt):
   if (lexical(left['text'])!=lexical(right['text']) or right['confidence']<.75
       or abs(left['start']-right['start'])>.30):return []
  return [dict(word,needs_review=True,review_reason='original_audio_retry') for word in ctc]
 def transcribe(self,samples,terms=None,speech=None,emit_start=0,emit_end=float('inf')):
  from speech_gate import SpeechProfile, anchored_speech_ranges, speech_profile
  from asr_guard import prepare,supported_words,join_words,choose_candidate,refine_words,speech_windows,lexical,unrecognized_voice
  from asr_terms import apply_terms
  from asr_units import restore_spoken_units
  from context_review import acoustic_evidence
  if speech is None:
   speech=speech_profile(samples)
  if isinstance(speech,SpeechProfile):
   core,ranges=speech.strict,speech.anchored
  else:
   core=speech
   ranges=anchored_speech_ranges(samples,core) if core else []
  windows=speech_windows(ranges,len(samples)/16000,padding=.5,max_seconds=24)
  if not windows:
   self.last={'selected':'silence','words':0,'word_evidence':[]};return ''
  from speech_audio import enhance_audio
  working=enhance_audio(samples,ranges,level=False)
  selected_all=[];raw_all=[];alternatives={'ctc':[],'rnnt':[],'character':[]};changes=[];uncertain=[];scores_all=[];kinds=[];decoded_seconds=0
  retried_original=False
  with self.lock:
   for left,right in windows:
    begin,finish=int(left*16000),min(len(samples),int(right*16000))
    if finish<=begin or right<=emit_start or left>=emit_end:continue
    left=begin/16000
    audio=prepare(working[begin:finish],highpass=False)
    local=[(max(0,a-left),min(len(audio)/16000,b-left)) for a,b in ranges if b>left and a<finish/16000]
    ctc_result=self._load('ctc').recognize(audio,sample_rate=16000)
    ctc=supported_words(ctc_result,local,emit_start-left,emit_end-left)
    scores=[lp for token,lp in zip(ctc_result.tokens or [],ctc_result.logprobs or []) if re.search(r'[^\W_]',token)]
    confidence=math.exp(sum(scores)/len(scores)) if scores else 0
    rnnt_result=self._load('rnnt').recognize(audio,sample_rate=16000)
    rnnt=supported_words(rnnt_result,local,emit_start-left,emit_end-left)
    selected=choose_candidate(ctc,rnnt);kind='rnnt' if selected is rnnt else 'ctc'
    if not selected and not retried_original:
     retried_original=True
     selected=self._retry_original(samples[begin:finish],audio,local,emit_start-left,emit_end-left)
     if selected:kind='original'
    character=[]
    if selected and kind!='original' and confidence>=.85:
     result=self._load('char').recognize(audio,sample_rate=16000)
     character=supported_words(result,local,emit_start-left,emit_end-left)
    raw=[dict(word) for word in selected]
    selected,refinements,weak=refine_words(selected,ctc if kind=='rnnt' else rnnt,character)
    selected,term_changes=apply_terms(selected,[('ctc',ctc),('rnnt',rnnt),('character',character)],terms)
    for i,word in enumerate(selected):
     if word['text']!=raw[i]['text']:word['original_text']=raw[i]['text']
     word['needs_review']=bool(word.get('needs_review')) or word['confidence']<.7 or word['text']!=raw[i]['text']
     for other_words in (ctc,rnnt):
      nearby=[(j,other) for j,other in enumerate(other_words) if abs(other['start']-word['start'])<=.35 and other['confidence']>=.65]
      if not nearby:continue
      j,other=min(nearby,key=lambda value:abs(value[1]['start']-word['start']))
      anchored=any(0<=i+d<len(selected) and 0<=j+d<len(other_words) and lexical(selected[i+d]['text'])==lexical(other_words[j+d]['text']) for d in (-1,1))
      if anchored and lexical(word['text'])!=lexical(other['text']):word['needs_review']=True
    selected,unit_changes=restore_spoken_units(selected,ctc_result,rnnt_result,character)
    for word in selected+raw+ctc+rnnt+character:
     word['start']+=left;word['end']=min(finish/16000,word['end']+left)
    selected_all.extend(selected);raw_all.extend(raw)
    for source,words in [('ctc',ctc),('rnnt',rnnt),('character',character)]:alternatives[source].extend(words)
    changes.extend(dict(change,start=change['start']+left) for change in refinements+term_changes+unit_changes)
    uncertain.extend(weak);scores_all.extend(scores);kinds.append(kind);decoded_seconds+=len(audio)/16000
  text=join_words(selected_all)
  confidence=math.exp(sum(scores_all)/len(scores_all)) if scores_all else 0
  self.last={'selected':kinds[0] if len(set(kinds))==1 else 'mixed','words':len(selected_all),
             'ctc_confidence':round(confidence,3),'needs_review':bool(uncertain) or confidence<.85 or any(w['needs_review'] for w in selected_all),
             'uncertain_words':uncertain,'refinements':changes,'decoded_seconds':round(decoded_seconds,3),'speech_windows':len(kinds)}
  if retried_original:self.last['original_retry']=True
  self.last['word_evidence']=acoustic_evidence(selected_all,list(alternatives.items()))
  gaps=unrecognized_voice(core,selected_all,max(0,emit_start),min(len(samples)/16000,emit_end))
  if gaps:self.last['unrecognized_voice']=gaps
  if changes:self.last['original_text']=join_words(raw_all)
  return text
