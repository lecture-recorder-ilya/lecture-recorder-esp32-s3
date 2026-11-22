"""Local speech presence check. Original recording is never modified."""
import threading
from speech_audio import normalize_audio
_LOCK=threading.Lock()
_MODEL=None

def speech_ranges(samples):
 global _MODEL
 import torch
 from silero_vad import load_silero_vad,get_speech_timestamps
 with _LOCK:
  torch.set_num_threads(1)
  if _MODEL is None:_MODEL=load_silero_vad()
  audio=torch.as_tensor(normalize_audio(samples),dtype=torch.float32)
  # Quiet ESP microphones need the same bounded gain as the decoder.
  with torch.inference_mode():
   rows=get_speech_timestamps(audio,_MODEL,sampling_rate=16000,threshold=.45,min_speech_duration_ms=200,min_silence_duration_ms=700,speech_pad_ms=500)
 return [(row['start']/16000,row['end']/16000) for row in rows]

def overlaps_speech(start,end,ranges):
 return sum(max(0,min(end,b)-max(start,a)) for a,b in ranges)>=min(.15,max(.05,(end-start)*.1))

def clips(ranges):return [v for pair in ranges for v in pair]


def supported_words(segment, ranges, strict_ranges=None):
 """Short stock decoder responses need confident words and unpadded speech."""
 import re
 words=segment.get('words',[])
 if words and sum(float(w.get('probability',0)) for w in words)/len(words)<.35:return False
 stock=bool(re.fullmatch(r'[\s.!?,…]*(?:спасибо|спасибо за внимание)[\s.!?,…]*',segment.get('text',''),re.I))
 if not stock:return True
 if not words or min(float(w.get('probability',0)) for w in words)<.9:return False
 start=min(w['start'] for w in words);end=max(w['end'] for w in words)
 core=ranges if strict_ranges is None else strict_ranges
 overlap=sum(max(0,min(end,b)-max(start,a)) for a,b in core)
 return end-start>=.2 and overlap>=max(.25,(end-start)*.6)

def strict_speech_ranges(samples):
 global _MODEL
 import torch
 from silero_vad import load_silero_vad,get_speech_timestamps
 with _LOCK:
  torch.set_num_threads(1)
  if _MODEL is None:_MODEL=load_silero_vad()
  audio=torch.as_tensor(normalize_audio(samples),dtype=torch.float32)
  with torch.inference_mode():
   rows=get_speech_timestamps(audio,_MODEL,sampling_rate=16000,threshold=.7,min_speech_duration_ms=350,min_silence_duration_ms=300,speech_pad_ms=0)
 return [(row['start']/16000,row['end']/16000) for row in rows]


def anchored_speech_ranges(samples,core,*,recover_quiet=False):
 """Quiet continuation is admitted only near an already verified voiced phrase."""
 if not core:return []
 global _MODEL
 import torch
 from silero_vad import load_silero_vad,get_speech_timestamps
 with _LOCK:
  torch.set_num_threads(1)
  if _MODEL is None:_MODEL=load_silero_vad()
  audio=torch.as_tensor(normalize_audio(samples),dtype=torch.float32)
  with torch.inference_mode():
   threshold,minimum=(.50,160) if recover_quiet else (.55,250)
   rows=get_speech_timestamps(audio,_MODEL,sampling_rate=16000,threshold=threshold,min_speech_duration_ms=minimum,min_silence_duration_ms=300,speech_pad_ms=0)
 weak=[(row['start']/16000,row['end']/16000) for row in rows]
 selected=list(core)
 for a,b in weak:
  if any(a<d+1.5 and b>c-1.5 for c,d in core):selected.append((a,b))
 selected.sort();merged=[]
 for a,b in selected:
  if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
  else:merged.append((a,b))
 return merged
