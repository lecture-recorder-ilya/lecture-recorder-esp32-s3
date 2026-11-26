import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    os.replace(temp,path)


class TargetSpeech:
    def __init__(self,models,config,device='cpu'):
        import numpy as np
        import torch
        from hyperpyyaml import load_hyperpyyaml
        from speechbrain.inference.separation import SepformerSeparation

        self.models=Path(models);self.config=dict(config);self.device=device
        self.np=np;self.torch=torch
        torch.set_num_threads(4)
        separator=self.config['separator']
        if separator not in ['whamr','libri']:
            raise ValueError('Неизвестная модель разделения.')
        if device not in ['cpu','mps'] or device=='mps' and not torch.backends.mps.is_available():
            raise ValueError('Выбранный вычислитель недоступен.')
        pins=json.loads((self.models/'pins.json').read_text())
        self.pins={}
        for row in pins:
            if row['model'] in [separator,'ecapa']:
                path=self.models/row['model']/row['file']
                found=file_sha(path)
                if found!=row['sha256']:
                    raise ValueError('Контрольная сумма локальной модели не совпала.')
                self.pins[str(path.relative_to(self.models))]=found
        with (self.models/separator/'hyperparams.yaml').open() as source:
            params=load_hyperpyyaml(source)
        modules={name:params[key] for name,key in [('encoder','Encoder'),('masknet','MaskNet'),('decoder','Decoder')]}
        for name,module in modules.items():
            state=torch.load(self.models/separator/(name+'.ckpt'),map_location='cpu',weights_only=True)
            module.load_state_dict(state,strict=True)
        self.separator=SepformerSeparation(modules=modules,hparams={'sample_rate':8000,'num_spks':2},run_opts={'device':device})
        with (self.models/'ecapa/hyperparams.yaml').open() as source:
            speaker=load_hyperpyyaml(source)
        self.features=speaker['compute_features'].eval()
        self.normalizer=speaker['mean_var_norm'].eval()
        self.embedding=speaker['embedding_model'].eval()
        self.embedding.load_state_dict(torch.load(self.models/'ecapa/embedding_model.ckpt',map_location='cpu',weights_only=True),strict=True)
        for module in [self.features,self.normalizer,self.embedding]:
            module.requires_grad_(False)
        self.reference_cache={}

    def speaker(self,samples):
        from scipy.signal import resample_poly
        torch=self.torch;np=self.np
        wave=np.asarray(samples,dtype=np.float32)
        if not wave.size or np.max(np.abs(wave))<1e-8:
            return np.zeros(192,dtype=np.float32)
        if wave.size<4000:
            wave=np.pad(wave,(0,4000-wave.size))
        wave=resample_poly(resample_poly(wave,1,2),2,1).astype(np.float32)[:len(wave)]
        tensor=torch.from_numpy(wave.copy())[None,:]
        with torch.inference_mode():
            lengths=torch.ones(1)
            features=self.normalizer(self.features(tensor),lengths)
            embedding=self.embedding(features,lengths).reshape(-1)
            embedding=torch.nn.functional.normalize(embedding,dim=0)
        return embedding.numpy()

    def separate(self,samples):
        from scipy.signal import resample_poly
        np=self.np;torch=self.torch
        audio=np.asarray(samples,dtype=np.float32)
        down=resample_poly(audio,1,2).astype(np.float32)
        with torch.inference_mode():
            output=self.separator.separate_batch(torch.from_numpy(down)[None,:])
            if self.device=='mps':torch.mps.synchronize()
            output=output[0].cpu().numpy()
        streams=[]
        for i in range(2):
            restored=resample_poly(output[:,i],2,1).astype(np.float32)[:len(audio)]
            if len(restored)<len(audio):restored=np.pad(restored,(0,len(audio)-len(restored)))
            streams.append(restored)
        return np.stack(streams)

    def analyze(self,samples,reference):
        np=self.np
        reference=np.asarray(reference,dtype=np.float32)
        if reference.ndim!=1 or not 40000<=len(reference)<=480000 or not np.all(np.isfinite(reference)) or np.max(np.abs(reference))<1e-6:
            raise ValueError('Выбери отдельную чистую фразу нужного человека длительностью2,5–30с.')
        key=hashlib.sha256(reference.astype('<f4').tobytes()).hexdigest()
        if key not in self.reference_cache:self.reference_cache[key]=self.speaker(reference)
        ref=self.reference_cache[key]
        raw=np.asarray(samples,dtype=np.float32)
        streams=self.separate(raw)
        scores=[float(np.dot(self.speaker(stream),ref)) for stream in streams]
        raw_score=float(np.dot(self.speaker(raw),ref))
        return streams,dict(scores=scores,raw_score=raw_score,reference_float_sha256=key)

    def select(self,raw,streams,evidence):
        np=self.np;scores=evidence['scores'];index=int(np.argmax(scores));best=scores[index];other=scores[1-index]
        raw_score=evidence['raw_score'];threshold=self.config['min_cosine'];margin=self.config['margin']
        info=dict(evidence,selected_stream=None,reason='unconfirmed',matched=False,gain=1.0)
        powers=np.mean(streams.astype(np.float64)**2,axis=1)
        weak_fraction=float(min(powers)/max(1e-18,sum(powers)))
        if raw_score>=self.config['bypass_cosine'] and (min(scores)>=self.config['same_voice_cosine'] or weak_fraction<self.config['single_residual_fraction']):
            info.update(reason='single_voice_or_ambiguous_split_preserved',matched=True,weak_stream_power_fraction=weak_fraction)
            return raw.copy(),info
        if best<threshold or best-other<margin:
            return raw.copy(),info
        selected=streams[index].copy()
        rms=float(np.sqrt(np.mean(raw.astype(np.float64)**2)))
        target_rms=float(np.sqrt(np.mean(selected.astype(np.float64)**2)))
        gain=min(self.config['max_gain'],max(1.0,rms/max(1e-8,target_rms)))
        selected*=gain
        peak=float(np.max(np.abs(selected)))
        if peak>.98:selected*=.98/peak;gain*=.98/peak
        info.update(selected_stream=index,reason='reference_voice_matched',matched=True,gain=gain)
        return selected,info

    def process(self,speech,reference,sample_rate=16000,progress=None,cancel=None):
        np=self.np;started=time.monotonic()
        if sample_rate!=16000:raise ValueError('Ожидается WAV16кГц.')
        audio=np.asarray(speech,dtype=np.float32)
        if audio.ndim==2 and audio.shape[1]==2:audio=audio.mean(axis=1,dtype=np.float32)
        if audio.ndim!=1 or not len(audio) or not np.all(np.isfinite(audio)):
            raise ValueError('Ожидается непустая моно/стерео запись.')
        reference=np.asarray(reference,dtype=np.float32)
        if reference.ndim==2 and reference.shape[1]==2:reference=reference.mean(axis=1,dtype=np.float32)
        if reference.ndim!=1 or not 40000<=len(reference)<=480000 or not np.all(np.isfinite(reference)) or np.max(np.abs(reference))<1e-6:
            raise ValueError('Выбери отдельную чистую фразу нужного человека длительностью2,5–30с.')
        core=int(self.config['core_seconds']*16000);edge=int(self.config['edge_seconds']*16000)
        output=np.zeros_like(audio);chunks=[]
        for start in range(0,len(audio),core):
            if cancel and cancel():raise KeyboardInterrupt()
            end=min(len(audio),start+core);left=max(0,start-edge);right=min(len(audio),end+edge)
            window=audio[left:right]
            if np.ptp(window)==0:
                enhanced=window.copy();info=dict(matched=False,reason='constant_input',selected_stream=None)
            else:
                streams,evidence=self.analyze(window,reference)
                enhanced,info=self.select(window,streams,evidence)
            output[start:end]=enhanced[start-left:end-left]
            chunks.append(dict(start=start/16000,end=end/16000,**info))
            if progress:progress(end/16000,len(audio)/16000)
        matched=sum(c['matched'] for c in chunks)
        status='matched' if matched==len(chunks) else 'not_found' if not matched else 'partial'
        return output,dict(status=status,sample_rate=16000,samples=len(audio),seconds=len(audio)/16000,
          timeline_preserved=len(output)==len(audio),uncertain_intervals=[{'start':c['start'],'end':c['end']} for c in chunks if not c['matched']],
          chunks=chunks,elapsed_seconds=time.monotonic()-started,config=self.config,device=self.device,
          speaker_embedding_device='cpu',model_sha256=self.pins,
          refusal_policy='Unconfirmed intervals retain original; never presented as a successfully isolated teacher.')


def main():
    import soundfile as sf
    parser=argparse.ArgumentParser()
    for name in ['mixture','reference','output','report','models','config']:parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--device',choices=['cpu','mps'],default='cpu')
    args=parser.parse_args()
    temp=args.output.with_name(args.output.name+'.tmp.wav')
    def stop(signum,frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,stop)
    try:
        started=time.monotonic()
        inputs=[args.mixture.resolve(),args.reference.resolve()]
        if args.output.resolve() in inputs or args.report.resolve() in inputs or args.output.resolve()==args.report.resolve():raise ValueError('Выход и отчёт должны отличаться от исходника и образца.')
        speech,rate=sf.read(args.mixture,dtype='float32');reference,ref_rate=sf.read(args.reference,dtype='float32')
        if ref_rate!=16000:raise ValueError('Образец должен быть16кГц.')
        signature={str(path):file_sha(path) for path in [args.mixture,args.reference]}
        config=json.loads(args.config.read_text())
        model=TargetSpeech(args.models,config,args.device)
        def progress(done,total):print(json.dumps(dict(type='progress',processed_seconds=done,total_seconds=total)),file=sys.stderr,flush=True)
        audio,report=model.process(speech,reference,rate,progress)
        if signature!={str(path):file_sha(path) for path in [args.mixture,args.reference]}:raise ValueError('Исходная запись изменилась во время обработки.')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        sf.write(temp,audio,16000,subtype='PCM_16')
        os.replace(temp,args.output)
        report.update(input_sha256=signature,output_sha256=file_sha(args.output),process_wall_seconds=time.monotonic()-started,
                      script_sha256=file_sha(__file__),configuration_sha256=file_sha(args.config))
        atomic_json(args.report,report)
        print(json.dumps(dict(status=report['status'],output=str(args.output),report=str(args.report)),ensure_ascii=False))
    except KeyboardInterrupt:
        temp.unlink(missing_ok=True);raise SystemExit(130)
    except Exception as error:
        temp.unlink(missing_ok=True)
        print(str(error),file=sys.stderr);raise SystemExit(2)


if __name__=='__main__':main()
