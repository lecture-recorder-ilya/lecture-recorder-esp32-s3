"""Independent local semantic search, speaker timeline and live transcription."""
import contextlib
import copy
import base64
import fcntl
import io
import json
import os
import struct
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
import study_store as store
from speech_quality import usable, repetition, clean_asr_text
from speech_gate import speech_profile,speech_ranges,overlaps_speech,clips,supported_words,strict_speech_ranges
from speech_context import context_for_recording
from asr_policy import selected_model
from preview_history import PreviewHistory
from live_draft import LiveDraft
from quality_asr import Decoder, ready as quality_ready
from power_budget import Budget

ROOT=store.ROOT
PROJECT=ROOT.parent.parent
MODELS=PROJECT/'work/models'
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
STATE={'live':store.read(ROOT/'study/settings.json').get('live',True),'message':'Запускаю учебный сервис','search_ready':False,'speakers_ready':False}
SEARCH_LOCK=threading.Lock()
VOICE_LOCK=threading.Lock()
SEARCH=None
VOICE=None
INDEX=None
PREVIEW={}
PREVIEW_LOCK=threading.Lock()
PREVIEW_HISTORY=PreviewHistory()
LIVE_DRAFT=LiveDraft()

def publish_context(name, updates, formulas=()):
    from context_review import replace_rows
    with PREVIEW_LOCK:
        if LIVE_DRAFT.history.file!=name:return 0
        changed=replace_rows(LIVE_DRAFT.history.rows,updates)
        from math_formulas import merge
        merged=merge(LIVE_DRAFT.formulas,formulas)
        if not changed and merged==LIVE_DRAFT.formulas:return 0
        LIVE_DRAFT.formulas=merged
        path=ROOT/'analysis'/(Path(name).stem+'.live.json')
        seconds=max(store.read(path).get('duration',0),max((r['end'] for r in LIVE_DRAFT.history.rows),default=0))
        LIVE_DRAFT.update(name,seconds,[],force=True)
        if PREVIEW_HISTORY.file==name:replace_rows(PREVIEW_HISTORY.rows,updates)
        if PREVIEW.get('file')==name:
            replace_rows(PREVIEW.get('segments',[]),updates)
            PREVIEW['history']=[copy.deepcopy(r) for r in PREVIEW_HISTORY.rows]
            PREVIEW['formulas']=copy.deepcopy(LIVE_DRAFT.formulas)
        return changed

from live_context import Reviewer
CONTEXT_REVIEWER=Reviewer(publish_context)

def publish_preview(name,value,force=False):
    global PREVIEW
    with PREVIEW_LOCK:
        LIVE_DRAFT.update(name,value['seconds'],value.get('segments',[]),force=force)
        value['history']=PREVIEW_HISTORY.update(name,value['seconds'],value.get('segments',[]))
        value['formulas']=copy.deepcopy(LIVE_DRAFT.formulas)
        PREVIEW=value
        recent=copy.deepcopy(LIVE_DRAFT.history.rows[-4:])
    CONTEXT_REVIEWER.submit(name,recent,value.get('subject'))

def recorder_status():
    with urlopen('http://127.0.0.1:8765/status',timeout=4) as response:return json.load(response)

def read_pcm(path, start, end):
    """Read growing RIFF even when the data chunk length has not been finalized."""
    with path.open('rb') as audio:
        if audio.read(4)!=b'RIFF':raise ValueError('Ожидается WAV')
        audio.read(4)
        if audio.read(4)!=b'WAVE':raise ValueError('Ожидается WAV')
        while True:
            header=audio.read(8)
            if len(header)!=8:return b''
            kind,size=struct.unpack('<4sI',header)
            if kind==b'data':
                available=max(0,(path.stat().st_size-audio.tell())//2)
                end=min(end,available)
                audio.seek(start*2,1)
                return audio.read(max(0,end-start)*2)
            if kind==b'fmt ':
                fmt=audio.read(size)
                if struct.unpack('<HHIIHH',fmt[:16])[:3]!=(1,1,16000):raise ValueError('Нужен PCM16, моно, 16 кГц')
                if struct.unpack('<H',fmt[14:16])[0]!=16:raise ValueError('Нужен PCM16')
                if size%2:audio.read(1)
            else:audio.seek(size+(size%2),1)

def embeddings(texts, prefix):
    global SEARCH
    import torch
    from transformers import AutoTokenizer, AutoModel
    torch.set_num_threads(2)
    if SEARCH is None:
        tokenizer=AutoTokenizer.from_pretrained(str(MODELS/'search'),local_files_only=True)
        model=AutoModel.from_pretrained(str(MODELS/'search'),local_files_only=True).eval()
        SEARCH=(tokenizer,model);STATE['search_ready']=True
    tokenizer,model=SEARCH
    batches=[]
    for offset in range(0,len(texts),16):
        inputs=tokenizer([prefix+text for text in texts[offset:offset+16]],padding=True,truncation=True,max_length=512,return_tensors='pt')
        with torch.inference_mode():
            hidden=model(**inputs).last_hidden_state
            mask=inputs['attention_mask'].unsqueeze(-1)
            values=(hidden*mask).sum(1)/mask.sum(1)
            batches.append(torch.nn.functional.normalize(values,dim=1))
    return torch.cat(batches) if batches else torch.empty((0,384))

def search(query):
    global INDEX
    if not isinstance(query,str) or not query.strip() or len(query)>1000:raise ValueError('Введи описание до 1000 символов')
    with SEARCH_LOCK:
        files=sorted((ROOT/'analysis').glob('*.transcript.json'))
        stamp=[(str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in files]
        if INDEX is None or INDEX[0]!=stamp:
            items=[]
            for path in files:
                name=path.name.removesuffix('.transcript.json')+'.wav'
                if not (ROOT/'recordings'/name).exists():continue
                segments=store.read(path).get('segments',[])
                for i in range(0,len(segments),2):
                    window=segments[i:i+3]
                    items.append({'file':name,'start':window[0]['start'],'end':window[-1]['end'],'text':' '.join(v['text'] for v in window)})
            INDEX=(stamp,items,embeddings([v['text'] for v in items],'passage: '))
        _,items,vectors=INDEX
        if not items:return {'results':[],'message':'Пока нет расшифровок для поиска'}
        scores=(vectors@embeddings([query],'query: ')[0]).tolist()
        ranked=sorted(range(len(items)),key=lambda i:scores[i],reverse=True)
        result=[]
        for i in ranked:
            item=items[i]
            if scores[i]<.72:continue
            if any(v['file']==item['file'] and abs(v['start']-item['start'])<20 for v in result):continue
            result.append(dict(item,score=round(scores[i],3)))
            if len(result)==8:break
        return {'results':result,'message':'Близкие по смыслу фрагменты; проверь по записи','model':'multilingual-e5-small'}

def voice_vector(pcm):
    global VOICE
    import numpy as np
    import torch
    from transformers import AutoFeatureExtractor, WavLMForXVector
    torch.set_num_threads(2)
    if VOICE is None:
        extractor=AutoFeatureExtractor.from_pretrained(str(MODELS/'speakers'),local_files_only=True)
        model=WavLMForXVector.from_pretrained(str(MODELS/'speakers'),local_files_only=True).eval()
        VOICE=(extractor,model);STATE['speakers_ready']=True
    extractor,model=VOICE
    signal=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    inputs=extractor(signal,sampling_rate=16000,return_tensors='pt',padding=True)
    with torch.inference_mode():
        value=model(**inputs).embeddings
        return torch.nn.functional.normalize(value,dim=-1)[0].numpy()

def assign_voice(vector, centroids, threshold=.75):
    import numpy as np
    similarity=[float(np.dot(vector,c)) for c in centroids]
    if similarity and max(similarity)>=threshold:
        return int(np.argmax(similarity)),max(similarity)
    if len(centroids)<8:
        centroids.append(vector);return len(centroids)-1,1.0
    return None,max(similarity,default=0)

def diarize(name, segments):
    budget=Budget()
    import numpy as np
    path=ROOT/'study'/(Path(name).stem+'.speakers.json')
    previous=store.read(path)
    fingerprints=[(v['id'],v['start'],v['end'],v['text']) for v in segments]
    saved=previous.get('fingerprints',[])
    if saved and any(list(v)!=saved[i] for i,v in enumerate(fingerprints[:len(saved)])):
        previous={}
    centroids=[np.array(v,dtype=np.float32) for v in previous.get('centroids',[])]
    result=previous.get('segments',[])
    known={v['segment_id'] for v in result}
    for segment in segments:
        if segment['id'] in known:continue
        start,end=segment['start'],segment['end']
        if end-start<1.2:
            result.append({'segment_id':segment['id'],'start':start,'end':end,'speaker':None,'similarity':0});continue
        pcm=read_pcm(store.audio(name),round(start*16000),round(min(end,start+6)*16000))
        if len(pcm)<16000*2:continue
        with VOICE_LOCK:vector=voice_vector(pcm)
        speaker,similarity=assign_voice(vector,centroids)
        # Do not adapt centroids to uncertain/noisy samples.
        if speaker is not None and similarity>.85:
            updated=centroids[speaker]*.9+vector*.1
            centroids[speaker]=updated/np.linalg.norm(updated)
        result.append({'segment_id':segment['id'],'start':start,'end':end,'speaker':speaker,'similarity':round(similarity,3)})
        budget.checkpoint()
    durations={i:sum(v['end']-v['start'] for v in result if v['speaker']==i) for i in range(len(centroids))}
    selected=previous.get('teacher')
    if selected is None and centroids:
        monitor=store.read(ROOT/'study'/(Path(name).stem+'.monitor-voices.json'))
        teacher=monitor.get('teacher')
        references=monitor.get('centroids',[])
        if type(teacher) is int and 0<=teacher<len(references):
            scores=[float(np.dot(c,np.array(references[teacher]))) for c in centroids]
            if max(scores)>.8:selected=int(np.argmax(scores))
    guessed=max(durations,key=durations.get) if durations else None
    value={'status':'done','segments':result,'centroids':[v.tolist() for v in centroids], 'fingerprints':fingerprints,
           'teacher':selected,'suggested_teacher':guessed,
           'speakers':[{'id':i,'label':'Голос '+str(i+1),'seconds':round(durations[i],1)} for i in durations],
           'message':'Предположение по звучанию. Выбери голос преподавателя. Одновременные голоса с одного микрофона могут смешиваться.'}
    with store.transaction():
        current=store.read(path)
        if previous:value['teacher']=current.get('teacher',selected)
        store.save(path,value)
    return value

def find_voice_example(name,speaker,saved):
    import numpy as np
    centroids=[np.array(v,dtype=np.float32) for v in saved.get('centroids',[])]
    if not 0<=speaker<len(centroids):return None
    path=store.audio(name)
    total=(path.stat().st_size-44)//2
    budget=Budget();best=None
    for frame in np.linspace(0,max(0,total-3*16000),24,dtype=int):
        pcm=read_pcm(path,int(frame),int(frame)+3*16000)
        if len(pcm)<32000:continue
        with VOICE_LOCK:vector=voice_vector(pcm)
        scores=[float(np.dot(vector,c)) for c in centroids]
        if int(np.argmax(scores))==speaker and scores[speaker]>=.75:
            best={'sample_start':int(frame)/16000,'sample_end':int(frame)/16000+len(pcm)/32000,'sample_confidence':scores[speaker]};break
        budget.checkpoint()
    budget.checkpoint(force=True)
    if best:
        with store.transaction():
            target=ROOT/'study'/(Path(name).stem+'.monitor-voices.json');current=store.read(target)
            for item in current.get('speakers',[]):
                if item['id']==speaker:item.update(best)
            store.save(target,current)
    return best

def voice_sample(name,speaker,monitor=False):
    store.audio(name)
    saved=store.read(ROOT/'study'/(Path(name).stem+('.monitor-voices.json' if monitor else '.speakers.json')))
    if monitor:
        item=next((v for v in saved.get('speakers',[]) if v['id']==speaker),{})
        if item and item.get('sample_start') is None:
            example=find_voice_example(name,speaker,saved)
            if example:item.update(example)
        start,end=item.get('sample_start'),item.get('sample_end')
    else:
        item=next((v for v in saved.get('segments',[]) if v.get('speaker')==speaker and v.get('end',0)-v.get('start',0)>=1),{})
        start,end=item.get('start'),item.get('end')
    if start is None or end is None:raise ValueError('Пример этого голоса пока не записан')
    pcm=read_pcm(store.audio(name),max(0,int(start*16000)),int(min(end,start+6)*16000))
    if not pcm:raise ValueError('Пример пока недоступен')
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','none'));wav.writeframes(pcm)
    return output.getvalue()

def speaker_track(name, speaker):
    store.audio(name)
    data=store.read(ROOT/'study'/(Path(name).stem+'.speakers.json'))
    intervals=[(v['start'],v['end']) for v in data.get('segments',[]) if v['speaker']==speaker]
    if not intervals:raise ValueError('У выбранного голоса нет фрагментов')
    if recorder_status().get('file')==name and recorder_status().get('recording'):raise ValueError('Дождись окончания записи')
    import numpy as np
    with wave.open(str(store.audio(name))) as wav:
        output=io.BytesIO()
        with wave.open(output,'wb') as target:
            target.setparams(wav.getparams())
            offset=0
            while True:
                pcm=wav.readframes(16000*30)
                if not pcm:break
                samples=np.frombuffer(pcm,dtype='<i2');mask=np.zeros(len(samples),dtype=bool)
                for start,end in intervals:
                    left=max(0,round(start*16000)-offset);right=min(len(samples),round(end*16000)-offset)
                    if right>left:mask[left:right]=True
                target.writeframesraw(np.where(mask,samples,0).astype('<i2').tobytes());offset+=len(samples)
        return output.getvalue()

def monitor_frame(after):
    status=recorder_status()
    if not status.get('recording'):return {'recording':False,'pcm':''}
    total=status['samples'];start=max(0,total-16000) if after<=0 or after>total or total-after>3*16000 else min(after,total)
    pcm=read_pcm(store.audio(status['file']),start,total)
    return {'recording':True,'file':status['file'],'from_frame':start,'to_frame':start+len(pcm)//2,'rate':16000,'pcm':base64.b64encode(pcm).decode()}

QUALITY_DECODER=Decoder(threads=2)
QUALITY_CURSOR={'file':None,'end':0}

def monitor_quality(name,total,flush=False):
    import numpy as np
    started=time.monotonic()
    if not quality_ready():raise RuntimeError('GigaAM: модель не установлена полностью')
    if QUALITY_CURSOR['file']!=name:
        QUALITY_CURSOR.update(file=name,end=max(0,total-int(12.45*16000)))
    offset=QUALITY_CURSOR['end'];end=min(max(0,total-(0 if flush else int(.45*16000))),offset+12*16000)
    if end <= offset or (not flush and end - offset < 12 * 16000):
        if flush:QUALITY_CURSOR['end']=max(offset,end)
        return {'file':name,'segments':[],'seconds':QUALITY_CURSOR['end']/16000,'message':'Собираю целую фразу · текст появляется примерно раз в 12 секунд','model':QUALITY_DECODER.engine}
    read_start=max(0,offset-int(.45*16000));read_end=min(total,end+int(.45*16000))
    pcm=read_pcm(store.audio(name),read_start,read_end)
    samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    profile=speech_profile(samples)
    ranges=profile.padded or profile.quiet
    if not ranges:
        QUALITY_CURSOR['end']=end
        return {'file':name,'segments':[],'message':'Фоновый звук · подтверждённой речи нет','seconds':end/16000,'speech_detected':False,'model':QUALITY_DECODER.engine}
    first=ranges[0][0];last=ranges[-1][1]
    context=context_for_recording(name,offset/16000)
    text=clean_asr_text(QUALITY_DECODER.transcribe(samples,(context['prompt'] or '').split(', ') if context['prompt'] else [],speech=profile,emit_start=(offset-read_start)/16000,emit_end=(end-read_start)/16000))
    QUALITY_CURSOR['end']=end
    from asr_segments import phrase_rows
    rows=phrase_rows(text,QUALITY_DECODER.last,read_start/16000,
                     max(offset/16000,read_start/16000+first),min(end/16000,read_start/16000+last))
    message='Контроль ESP · GigaAM · черновой текст' if rows else 'Речь слышна, текст пока неразборчив'
    if not rows and profile.quiet:message='Фоновый звук · подтверждённой речи нет'
    return {'file':name,'segments':rows,'message':message,
            'seconds':end/16000,'model':QUALITY_DECODER.engine,'subject':context['subject'],'context_seconds':12,'latency':round(time.monotonic()-started,3),'updated':time.time()}

def monitor_chunk(name,total):
    if selected_model(store.read(PROJECT/'work/ai-settings.json').get('speech','auto'),quality_ready())=='qwen':return monitor_quality(name,total)
    import numpy as np
    import mlx_whisper
    started=time.monotonic()
    if total<16000:return {'file':name,'segments':[],'message':'Ожидаю звук ESP','seconds':total/16000}
    end=total;offset=max(0,end-30*16000)
    pcm=read_pcm(store.audio(name),offset,end)
    if not pcm:return {'file':name,'segments':[],'message':'Ожидаю звук ESP','seconds':end/16000}
    samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    rms=float(np.sqrt(np.mean(samples*samples)))
    if rms<.0002:return {'file':name,'segments':[],'message':'Сейчас тихо','seconds':end/16000,'rms':rms}
    ranges=speech_ranges(samples)
    if not ranges:return {'file':name,'segments':[],'message':'Пауза · речи нет','seconds':end/16000,'rms':rms,'speech_detected':False}
    strict_ranges=strict_speech_ranges(samples)
    if not strict_ranges:return {'file':name,'segments':[],'message':'Фоновый звук · подтверждённой речи нет','seconds':end/16000,'rms':rms,'speech_detected':False}
    from speech_audio import enhance_audio,normalize_audio
    samples=normalize_audio(enhance_audio(samples,strict_ranges,level=False))
    model_path=MODELS/'whisper'
    if not any((model_path/name).exists() for name in ('weights.npz','weights.safetensors')):model_path=MODELS/'monitor-base'
    context=context_for_recording(name,offset/16000)
    recognized=mlx_whisper.transcribe(samples,path_or_hf_repo=str(model_path),language='ru',temperature=0,initial_prompt=context['prompt'],
        condition_on_previous_text=False,verbose=None,compression_ratio_threshold=2.0,logprob_threshold=-1.0,
        no_speech_threshold=.7,word_timestamps=True,sample_len=300,clip_timestamps=clips(ranges))
    segments=[]
    if repetition(recognized.get('text','')):
        recognized['segments']=[]
    for item in recognized.get('segments',[]):
        local_end=min(len(pcm)/32000,item['end'])
        if usable(item) and supported_words(item,ranges,strict_ranges) and 0<=item['start']<local_end and overlaps_speech(item['start'],local_end,strict_ranges):segments.append({'id':len(segments),'start':round(offset/16000+item['start'],2),
            'end':round(offset/16000+local_end,2),'text':clean_asr_text(item['text'])})
    return {'file':name,'segments':segments,'message':('Контроль ESP · '+context['subject']+' · черновой текст' if context['prompt'] else 'Контроль ESP · черновой текст') if segments else 'Речь слышна, текст пока неразборчив',
            'seconds':end/16000,'rms':rms,'model':model_path.name,'subject':context['subject'],'context_seconds':30,'latency':round(time.monotonic()-started,3),'updated':time.time()}

def live_loop():
    global PREVIEW
    last_file=None;last_samples=0
    while True:
        started=time.monotonic()
        try:
            status=recorder_status()
            if not STATE['live'] or not status.get('recording'):
                # Publish the final short tail once when capture stops. Waiting
                # for whole phrases must not lose the end of the live draft.
                if STATE['live'] and not status.get('recording') and status.get('file')==QUALITY_CURSOR['file'] and int(status.get('samples',0))>QUALITY_CURSOR['end'] and selected_model(store.read(PROJECT/'work/ai-settings.json').get('speech','auto'),quality_ready())=='qwen':
                    name=status['file'];total=int(status.get('samples',0))
                    value=monitor_quality(name,total,flush=True)
                    publish_preview(name,value,force=True)
                with PREVIEW_LOCK:
                    if not PREVIEW and status.get('file'):
                        draft=store.read(ROOT/'analysis'/(Path(status['file']).stem+'.live.json'))
                        seconds=status.get('samples',0)/16000
                        PREVIEW={'history':[v for v in draft.get('segments',[]) if v['end']>seconds-300],'formulas':draft.get('formulas',[])}
                STATE['message']='Контроль ESP выключен; аудиозапись сохраняется' if status.get('recording') else 'Контроль ESP включается во время записи'
                time.sleep(1);continue
            name=status['file'];total=int(status.get('samples',0))
            if name==last_file and total-last_samples<16000:
                time.sleep(.1);continue
            import mlx.core as mx
            budget=Budget(synchronize=lambda:mx.synchronize(mx.gpu))
            value=monitor_chunk(name,total)
            publish_preview(name,value)
            STATE['message']=value['message'];last_file=name;last_samples=total
            budget.checkpoint(force=True)
        except Exception as error:
            STATE['message']='Контроль ESP: '+str(error)[:300]
            time.sleep(1)
        delay=1-(time.monotonic()-started)
        if delay>0:time.sleep(delay)

def lecture_recall_loop():
    from lecture_recall import cue_query,passages,shortlist,ranked_results
    handled=None
    while True:
        try:
            status=recorder_status()
            if not status.get('recording') or not STATE['live']:
                time.sleep(3);continue
            name=status['file']
            with PREVIEW_LOCK:rows=[dict(s) for s in PREVIEW.get('history',[])] if PREVIEW.get('file')==name else []
            cue=cue_query(rows,status['samples']/16000)
            if not cue or handled==(name,cue['start']):
                time.sleep(3);continue
            handled=(name,cue['start']);path=ROOT/'study'/(Path(name).stem+'.recall.json')
            store.save(path,dict(cue,status='searching',results=[]))
            items=shortlist(cue['query'],passages(ROOT,name,store.read));results=[]
            if items:
                budget=Budget()
                with SEARCH_LOCK:
                    query=embeddings([cue['query']],'query: ')[0]
                    vectors=[]
                    for offset in range(0,len(items),16):
                        vectors.append(embeddings([v['text'] for v in items[offset:offset+16]],'passage: '));budget.checkpoint(force=True)
                    import torch
                    scores=(torch.cat(vectors)@query).tolist()
                results=ranked_results(items,scores)
            store.save(path,dict(cue,status='ready' if results else 'not_found',results=results))
        except Exception as error:
            STATE['recall_error']=str(error)[:200]
            if 'path' in locals() and 'cue' in locals() and cue:store.save(path,dict(cue,status='unavailable',results=[]))
        time.sleep(3)

def passive_teacher_loop():
    from passive_teacher import observe,sustained_window
    import numpy as np
    last_attempt={}
    while True:
        try:
            status=recorder_status()
            if not status.get('recording') or not STATE['live']:
                time.sleep(2);continue
            name=status['file'];total=status['samples']
            if total-last_attempt.get(name,0)<20*16000:
                time.sleep(1);continue
            last_attempt={name:total}
            with PREVIEW_LOCK:segments=[dict(v) for v in PREVIEW.get('segments',[])] if PREVIEW.get('file')==name else []
            # Only actual recognized sustained speech; no silence/short answers.
            window=sustained_window(segments,total/16000)
            if not window:continue
            start,end=window
            path=ROOT/'study'/(Path(name).stem+'.passive-teacher.json')
            saved=store.read(path)
            if start<saved.get('last_end',0):continue
            pcm=read_pcm(store.audio(name),round(start*16000),round(end*16000))
            signal=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
            if len(signal)<5*16000 or float(np.sqrt(np.mean(signal*signal)))<.0005 or float(np.mean(abs(signal)>.99))>.01:continue
            budget=Budget()
            with VOICE_LOCK:vector=voice_vector(pcm)
            observe(saved,vector.tolist(),start,end)
            store.save(path,saved)
            STATE.pop('passive_voice_error',None)
            budget.checkpoint(force=True)
        except Exception as error:
            STATE['passive_voice_error']=str(error)[:200];time.sleep(3)
        time.sleep(1)

def voice_loop():
    while True:
        try:
            final=list((ROOT/'analysis').glob('*.transcript.json'))
            live=[]
            for path in sorted(final+live,key=lambda p:p.stat().st_mtime,reverse=True):
                source=store.read(path);segments=source.get('segments',[])
                name=path.name.removesuffix('.transcript.json').removesuffix('.live.json')+'.wav'
                previous=store.read(ROOT/'study'/(Path(name).stem+'.speakers.json'))
                done={v['segment_id'] for v in previous.get('segments',[])}
                if segments and any(v['id'] not in done for v in segments):
                    STATE['voice_message']='Различаю голоса: '+name
                    diarize(name,segments)
            STATE['voice_message']='Голоса обработаны'
        except Exception as error:STATE['voice_message']='Голоса: '+str(error)[:300]
        time.sleep(5)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,value,code=200,mime='application/json'):
        body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        route=urlsplit(self.path);q=parse_qs(route.query)
        try:
            if route.path=='/study-status':return self.reply(dict(STATE,pid=os.getpid()))
            if route.path=='/search':return self.reply(search(q.get('q',[''])[0]))
            if route.path=='/monitor-frame':return self.reply(monitor_frame(int(q.get('after',['0'])[0])))
            if route.path=='/live':
                status=recorder_status();name=status.get('file')
                with PREVIEW_LOCK:value=dict(PREVIEW)
                voices=store.read(ROOT/'study'/(Path(name).stem+'.monitor-voices.json')) if name else {}
                value['seconds']=status.get('samples',0)/16000
                value['history']=[row for row in value.get('history',[]) if row['end']>value['seconds']-300]
                value['formulas']=[row for row in value.get('formulas',[]) if row.get('end',row['start'])>value['seconds']-300]
                value['markers']=[m for m in store.notes(name).get('markers',[]) if m['start']>value['seconds']-300] if name else []
                from passive_teacher import public
                passive=public(store.read(ROOT/'study'/(Path(name).stem+'.passive-teacher.json'))) if name else {}
                recall=store.read(ROOT/'study'/(Path(name).stem+'.recall.json')) if name else {}
                if recall and value['seconds']-recall.get('start',0)>300:recall={}
                return self.reply(dict(value,self_review=dict(CONTEXT_REVIEWER.status),recall=recall,passive_teacher=passive,enabled=STATE['live'],message=STATE['message'],file=name,recording=status['recording'],voice={k:v for k,v in voices.items() if k!='centroids'}))
            if route.path=='/voice-sample':return self.reply(voice_sample(q.get('file',[''])[0],int(q.get('speaker',['-1'])[0]),q.get('monitor',['0'])[0]=='1'),mime='audio/wav')
            if route.path=='/speaker-track':return self.reply(speaker_track(q.get('file',[''])[0],int(q.get('speaker',['-1'])[0])),mime='audio/wav')
            return self.reply({'error':'Не найдено'},404)
        except (ValueError,KeyError,TypeError) as error:self.reply({'error':str(error)},400)
        except Exception as error:self.reply({'error':str(error)[:500]},503)
    def do_POST(self):
        if self.headers.get('Origin') not in (None,'http://127.0.0.1:8768','http://localhost:8768'):return self.reply({'error':'Запрос отклонён'},403)
        if self.path=='/shutdown-for-update':
            try:
                status=recorder_status()
                if status.get('recording') or not status.get('busy'):
                    return self.reply({'error':'Сначала подготовь службу записи к обновлению'},409)
            except OSError:
                pass  # The updater has already stopped the recording service.
            self.reply({'ok':True})
            CONTEXT_REVIEWER.close()
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        try:
            length=int(self.headers.get('Content-Length',0))
            if not 0<=length<=4096:raise ValueError('Слишком большой запрос')
            body=json.loads(self.rfile.read(length))
            if self.path=='/live-settings':
                if type(body.get('live')) is not bool:raise ValueError('Нужно true/false')
                STATE['live']=body['live'];store.save(ROOT/'study/settings.json',{'live':STATE['live']});return self.reply({'ok':True})
            if self.path=='/speaker-choice':
                name=body.get('file');store.audio(name);suffix='.monitor-voices.json' if body.get('monitor') is True else '.speakers.json'
                path=ROOT/'study'/(Path(name).stem+suffix)
                with store.transaction():
                    data=store.read(path);speaker=body.get('speaker')
                    if type(speaker) is not int or speaker not in [v['id'] for v in data.get('speakers',[])]:raise ValueError('Голос не найден')
                    data['teacher']=speaker;store.save(path,data)
                return self.reply({'ok':True})
            self.reply({'error':'Не найдено'},404)
        except Exception as error:self.reply({'error':str(error)},400)

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8768),Handler)
    for target in (live_loop,passive_teacher_loop,lecture_recall_loop):threading.Thread(target=target,daemon=True).start()
    server.serve_forever()
