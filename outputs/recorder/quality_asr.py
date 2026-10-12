"""Local adaptive Russian ASR with voiced-word evidence; originals remain untouched."""
import threading,math,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parent.parent
MODEL=PROJECT/'work/models/gigaam';RNNT=PROJECT/'work/models/gigaam-rnnt'
CHAR=PROJECT/'work/models/gigaam-beam'
ENGINE='GigaAM-v3-3pass-context-v5'

def ready():
 return all(p.exists() for p in [MODEL/'v3_e2e_ctc.int8.onnx',MODEL/'v3_e2e_ctc_vocab.txt',PROJECT/'work/models/gigaam-manifest.json',RNNT/'v3_e2e_rnnt_encoder.onnx',RNNT/'v3_e2e_rnnt_decoder.onnx',RNNT/'v3_e2e_rnnt_joint.onnx',RNNT/'v3_e2e_rnnt_vocab.txt',PROJECT/'work/models/gigaam-rnnt-manifest.json',CHAR/'v3_ctc.onnx',CHAR/'v3_vocab.txt',PROJECT/'work/models/gigaam-beam-manifest.json'])

class Decoder:
 def __init__(self):self.models={};self.lock=threading.Lock();self.last={}
 def close(self):
  with self.lock:self.models.clear()
 def _load(self,kind):
  if kind not in self.models:
   import onnx_asr,onnxruntime as rt
   options=rt.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1;options.execution_mode=rt.ExecutionMode.ORT_SEQUENTIAL
   options.add_session_config_entry('session.intra_op.allow_spinning','0');options.add_session_config_entry('session.inter_op.allow_spinning','0')
   name='gigaam-v3-ctc' if kind=='char' else 'gigaam-v3-e2e-'+kind
   path=CHAR if kind=='char' else RNNT if kind=='rnnt' else MODEL
   self.models[kind]=onnx_asr.load_model(name,path=path,quantization='int8' if kind=='ctc' else None,sess_options=options,providers=['CPUExecutionProvider']).with_timestamps()
  return self.models[kind]
 def transcribe(self,samples,terms=None,speech=None,emit_start=0,emit_end=float('inf')):
  from speech_gate import strict_speech_ranges,anchored_speech_ranges
  from asr_guard import prepare,supported_words,join_words,choose_candidate,refine_words
  from speech_quality import repetition
  from context_review import acoustic_evidence
  core=strict_speech_ranges(samples) if speech is None else speech
  if not core:
   self.last={'selected':'silence','words':0};return ''
  ranges=anchored_speech_ranges(samples,core);audio=prepare(samples,highpass=False)
  with self.lock:
   ctc_result=self._load('ctc').recognize(audio,sample_rate=16000)
   ctc=supported_words(ctc_result,ranges,emit_start,emit_end)
   # Keep CTC phrases on weak audio. The second pass can independently
   # confirm truncated words without replacing the entire weak excerpt.
   scores=[lp for token,lp in zip(ctc_result.tokens or [],ctc_result.logprobs or []) if re.search(r'[^\W_]',token)]
   confidence=math.exp(sum(scores)/len(scores)) if scores else 0;rnnt=[]
   rnnt_result=self._load('rnnt').recognize(audio,sample_rate=16000)
   rnnt=supported_words(rnnt_result,ranges,emit_start,emit_end)
   selected=choose_candidate(ctc,rnnt);kind='rnnt' if selected is rnnt else 'ctc'
   character=[]
   # This independent character model helped clear historical speech, but
   # regressed on weak classroom audio. It may only refine anchored words.
   if confidence>=.85:
    result=self._load('char').recognize(audio,sample_rate=16000)
    character=supported_words(result,ranges,emit_start,emit_end)
   original=join_words(selected)
   selected,changes,uncertain=refine_words(selected,ctc if kind=='rnnt' else rnnt,character)
   text=join_words(selected)
   if repetition(text):text=''
   self.last={'selected':kind,'words':len(selected),'ctc_confidence':round(confidence,3),'needs_review':bool(uncertain) or confidence<.85 or any(c['source']=='character-acoustic-pass' for c in changes),'uncertain_words':uncertain,'refinements':changes}
   self.last['word_evidence']=acoustic_evidence(selected,[('ctc',ctc),('rnnt',rnnt),('character',character)])
   if changes:self.last['original_text']=original
   return text
