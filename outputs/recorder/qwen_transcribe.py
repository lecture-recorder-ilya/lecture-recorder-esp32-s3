import argparse,json,os,wave
from transcript_cache import identity,prepare,checkpoint
from asr_windows import audio_window
from asr_segments import phrase_rows
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent.parent

def save(path,data):
 temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(path)

def run(audio_path,result_path,progress_path):
 import numpy as np
 from speech_gate import speech_ranges,strict_speech_ranges
 from speech_quality import usable,clean_asr_text
 from quality_asr import Decoder,ENGINE
 from power_budget import Budget
 from speech_context import context_for_recording
 budget=Budget();decoder=Decoder()
 cache=result_path.with_suffix('.transcript.json')
 try:
  with wave.open(str(audio_path)) as audio:
   rate=audio.getframerate();total=audio.getnframes();duration=total/rate
   if rate!=16000 or audio.getsampwidth()!=2 or audio.getnchannels()!=1:raise ValueError('Ожидается PCM16 mono 16 кГц.')
   step=20*rate
   expected=identity(audio_path,ENGINE)
   old=prepare(cache,expected,total,step)
   if old['complete']:return
   segments=old['segments']
   for offset in range(old.get('completed_frames',0),total,step):
    save(progress_path,dict(status='processing',stage='transcribing',percent=5+round(55*offset/max(1,total)),message=f'GigaAM: распознаю {offset//rate//60} из {int(duration)//60+1} мин'))
    read_start,read_end=audio_window(offset,step,total,rate)
    audio.setpos(read_start);samples=np.frombuffer(audio.readframes(read_end-read_start),dtype='<i2').astype(np.float32)/32768
    core=strict_speech_ranges(samples)
    ranges=speech_ranges(samples) if core else []
    if ranges:
     first,last=ranges[0][0],ranges[-1][1]
     context=context_for_recording(audio_path.name,offset/rate)
     terms=(context['prompt'] or '').split(', ') if context['prompt'] else []
     text=clean_asr_text(decoder.transcribe(samples,terms,speech=core,emit_start=(offset-read_start)/rate,emit_end=(min(total,offset+step)-read_start)/rate))
     segments.extend(phrase_rows(text,decoder.last,read_start/rate,
                                 max(offset/rate,read_start/rate+first),
                                 min(duration,(offset+step)/rate,read_start/rate+last),len(segments)))
    save(cache,checkpoint(expected,segments,duration,min(offset+step,total)))
    budget.checkpoint(force=True)
  save(cache,checkpoint(expected,segments,duration,total,complete=True))
  save(progress_path,dict(status='processing',stage='transcribed',percent=60,message='GigaAM: речь распознана, готовлю конспект'))
 finally:decoder.close()

if __name__=='__main__':
 import importlib.util,sys
 if importlib.util.find_spec('torch') is None:
  os.execv(str(PROJECT/'work/ai-env/bin/python'),[str(PROJECT/'work/ai-env/bin/python'),str(Path(__file__)),*sys.argv[1:]])
 os.nice(10)
 p=argparse.ArgumentParser();p.add_argument('audio');p.add_argument('result');p.add_argument('progress');a=p.parse_args()
 try:run(Path(a.audio),Path(a.result),Path(a.progress))
 except Exception as exc:
  save(Path(a.progress),dict(status='error',stage='error',percent=0,message=str(exc)[:1000]));raise
