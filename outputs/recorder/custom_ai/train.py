"""Pilot training from random weights. Never promotes a checkpoint to production."""
import argparse
import fcntl
import hashlib
import json
import os
import random
import time
import uuid
import wave
from pathlib import Path

import numpy as np
import torch
from .corpus import Corpus
from .models import SpeechModel,NotesModel,TAGS,features,encode,decode,normalize,edit_distance

def audio(corpus, row):
    with wave.open(str(corpus.root/(row['id']+'.wav')),'rb') as source:
        return np.frombuffer(source.readframes(source.getnframes()),dtype='<i2').astype(np.float32)/32768

def train(task, corpus, epochs=30):
    with (corpus.root/'training.lock').open('a') as guard:
        try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Обучение уже идёт') from None
        return _train(task,corpus,epochs)

def _train(task, corpus, epochs):
    if task not in ('speech','notes') or not 1<=epochs<=200:raise ValueError('Некорректные параметры обучения')
    rows=corpus.verified()
    if task=='speech' and any(not r['silence'] and not normalize(r['text']) for r in rows):
        raise ValueError('В речевых примерах нужен текст из поддерживаемых букв или цифр')
    if len(rows)<20:raise ValueError('Для первого эксперимента нужно хотя бы 20 проверенных фрагментов; этого недостаточно для готового распознавателя')
    training,validation=corpus.split(rows)
    if task=='notes':
        training=[r for r in training if not r['silence']]
        validation=[r for r in validation if not r['silence']]
        if not any(r['labels'] for r in training):raise ValueError('Отметь в учебных текстах конспект, ДЗ, формулы, предмет или преподавателя')
    elif not all(any(r['silence'] for r in split) and any(not r['silence'] for r in split) for split in (training,validation)):
        raise ValueError('И в учебных, и в контрольных записях нужны примеры речи и тишины')
    if not training or not validation:raise ValueError('Не хватает учебных или контрольных примеров')
    torch.set_num_threads(2);torch.manual_seed(42);random.seed(42)
    model=SpeechModel() if task=='speech' else NotesModel()
    initial=hashlib.sha256(b''.join(v.detach().numpy().tobytes() for v in model.state_dict().values())).hexdigest()
    optimizer=torch.optim.AdamW(model.parameters(),lr=1e-3)
    ctc=torch.nn.CTCLoss(blank=0,zero_infinity=False)
    run=corpus.root/'runs'/(task+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    run.mkdir(parents=True,mode=0o700)
    corpus.save(run/'dataset.json',dict(training=training,validation=validation))
    cached={r['id']:features(audio(corpus,r)) for r in rows} if task=='speech' else {}
    best=float('inf');history=[]
    for epoch in range(epochs):
        model.train();random.shuffle(training);losses=[]
        for row in training:
            optimizer.zero_grad()
            if task=='speech':
                x=cached[row['id']]
                # Small loudness shifts; do not replace speech with silence while keeping a speech label.
                scores=model(x+random.uniform(-.03,.03))
                target=encode(row['text'])
                needed=len(target)+int((target[1:]==target[:-1]).sum())
                if needed>len(scores):raise ValueError('Текст не помещается в аудиофрагмент; проверь эталон')
                loss=ctc(scores,target,torch.tensor([len(scores)]),torch.tensor([len(target)]))
            else:
                target=torch.tensor([float(tag in row['labels']) for tag in TAGS])
                loss=torch.nn.functional.binary_cross_entropy_with_logits(model(row['text']),target)
            if not torch.isfinite(loss):raise ValueError('Обучение остановлено: некорректная функция ошибки')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1)
            optimizer.step();losses.append(float(loss.detach()))
        model.eval();errors=words=quiet_false=quiet_count=tp=fp=fn=0
        details=[]
        with torch.inference_mode():
            for row in validation:
                if task=='speech':
                    text=decode(model(cached[row['id']])[:,0].argmax(-1).tolist())
                    reference=normalize(row['text']).split()
                    if row['silence']:
                        quiet_count+=1;quiet_false+=bool(text)
                    else:
                        errors+=edit_distance(reference,text.split());words+=len(reference)
                    details.append(dict(id=row['id'],reference=row['text'],hypothesis=text))
                else:
                    predicted={tag for tag,score in zip(TAGS,model(row['text']).sigmoid()) if float(score)>=.5}
                    expected=set(row['labels']);tp+=len(predicted&expected);fp+=len(predicted-expected);fn+=len(expected-predicted)
                    details.append(dict(id=row['id'],reference=sorted(expected),hypothesis=sorted(predicted)))
        metric=errors/max(1,words)+quiet_false/max(1,quiet_count) if task=='speech' else 1-2*tp/max(1,2*tp+fp+fn)
        report=dict(epoch=epoch+1,loss=float(np.mean(losses)),metric=metric,
                    word_error_rate=errors/max(1,words) if task=='speech' else None,
                    false_text_on_silence=quiet_false/max(1,quiet_count) if task=='speech' else None,
                    micro_f1=2*tp/max(1,2*tp+fp+fn) if task=='notes' else None)
        history.append(report)
        if metric<best:
            best=metric
            torch.save(dict(state_dict=model.state_dict(),task=task,architecture='lecture-own-v1',
                            initialized_from='random',seed=42),run/'candidate.pt.tmp')
            os.replace(run/'candidate.pt.tmp',run/'candidate.pt')
            corpus.save(run/'evaluation.json',dict(**report,examples=details,production_ready=False,
                        limitation='Small local pilot; no comparison against production models and no deployment approval.'))
        corpus.save(run/'history.json',history)
        print(json.dumps(report),flush=True)
    corpus.save(run/'manifest.json',dict(task=task,initialized_from='random',initial_state_sha256=initial,
                pretrained_weights_used=False,parameter_count=sum(p.numel() for p in model.parameters()),
                epochs=epochs,training_examples=len(training),validation_examples=len(validation),
                label_coverage={tag:sum(tag in r['labels'] for r in training) for tag in TAGS},
                pytorch_version=str(torch.__version__),
                checkpoint_sha256=hashlib.sha256((run/'candidate.pt').read_bytes()).hexdigest(),
                production_ready=False,completed=True))
    return run

def main():
    parser=argparse.ArgumentParser();parser.add_argument('task',choices=['speech','notes'])
    parser.add_argument('--epochs',type=int,default=30)
    args=parser.parse_args()
    recorder=Path(__file__).resolve().parents[1]
    corpus=Corpus(recorder,recorder.parents[1]/'work/custom-ai')
    try:print(train(args.task,corpus,args.epochs))
    except ValueError as error:parser.exit(2,str(error)+'\n')

if __name__=='__main__':main()
