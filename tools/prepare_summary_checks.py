"""Подготовить контроль конспекта из имеющихся WAV, субтитров и сохранённого ASR."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'outputs/recorder'))
from ai_worker import analysis_rows
from prepare_rear_row_asr import OPENSTT_MD5, samples
from prepare_public_asr import room_signal,write_wave
import numpy as np


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def pcm(path):
    with wave.open(str(path)) as audio:
        return audio.getparams()[:4],audio.readframes(audio.getnframes())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('run',type=Path)
    corpus=parser.add_mutually_exclusive_group(required=True)
    corpus.add_argument('--archive',type=Path)
    corpus.add_argument('--mtedx-parquet',type=Path)
    parser.add_argument('--parquet-python',type=Path,default=Path(sys.executable),help='Python с pyarrow; среда приложения не меняется')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.archive and hashlib.md5(args.archive.read_bytes()).hexdigest()!=OPENSTT_MD5:
        raise ValueError('Архив отличается от проверенной версии OpenSTT')
    rows=json.loads(args.manifest.read_text());asr={r['id']:r for r in json.loads(args.run.read_text())['cases']}
    cases=[]
    with (tarfile.open(args.archive) if args.archive else nullcontext()) as archive,tempfile.TemporaryDirectory(prefix='summary-audio-') as temp:
        cache={};temp=Path(temp)
        mtedx={}
        if args.mtedx_parquet:
            from prepare_mtedx_asr import PARQUET_SHA256
            subprocess.run([args.parquet_python,ROOT/'tools/prepare_mtedx_asr.py',args.mtedx_parquet,temp/'mtedx'],
                           check=True,capture_output=True)
            prepared=temp/'mtedx/manifest.json'
            mtedx={r['id']:r for r in json.loads(prepared.read_text())}
        for item in rows:
            recorded=asr[item['id']];path=args.manifest.parent/item['audio']
            if digest(path)!=item['audio_sha256'] or digest(path)!=recorded['audio_sha256']:
                raise ValueError('Не совпал WAV: '+item['id'])
            if item['reference']!=recorded['reference']:raise ValueError('Не совпали субтитры')
            origin=dict(item,local_audio=str(path.resolve()),asr_run=str(args.run.resolve()),
                        asr_run_sha256=digest(args.run),fact_checked=False)
            if item.get('source')=='OpenSTT public_lecture_1':
                if archive is None:raise ValueError('Для OpenSTT нужен проверенный архив')
                source=item['source_item'];reference=archive.extractfile(str(Path(source).with_suffix('.txt'))).read().decode().strip()
                if reference!=item['reference']:raise ValueError('Субтитры отличаются от архива')
                if source not in cache:
                    opus=temp/'original.opus';wav=temp/'original.wav'
                    opus.write_bytes(archive.extractfile(source).read())
                    subprocess.run(['/usr/bin/afconvert',opus,wav,'-f','WAVE','-d','LEI16@16000','-c','1'],check=True,capture_output=True)
                    cache[source]=(pcm(wav),samples(wav))
                    wav.unlink()
                expected=cache[source][0]
                if item.get('synthetic'):
                    wav=temp/'room.wav'
                    write_wave(wav,room_signal(cache[source][1],np.random.default_rng(int(Path(source).stem,16))))
                    expected=pcm(wav)
                if pcm(path)!=expected:raise ValueError('Звук отличается от исходника или указанной обработки: '+item['id'])
                origin.update(archive_md5=OPENSTT_MD5,archive=str(args.archive.resolve()),
                              audio_provenance_verified=True,reference_source='субтитры из проверенного архива')
            elif item.get('source')=='Multilingual TEDx / OpenSLR 100':
                fresh=mtedx[item['id']]
                for field in ['reference','source_revision','source_video','source_start','source_end','audio_sha256']:
                    if item[field]!=fresh[field]:raise ValueError('Разметка mTEDx отличается от зафиксированного Parquet')
                if pcm(path)!=pcm(temp/'mtedx'/fresh['audio']):raise ValueError('Звук отличается от mTEDx')
                origin.update(parquet_sha256=PARQUET_SHA256,parquet=str(args.mtedx_parquet.resolve()),audio_provenance_verified=True)
            elif item.get('synthetic'):origin['kind']='синтетическая тишина или шум; не реальная лекция'
            else:raise ValueError('Не подтверждено происхождение: '+item['id'])
            lines=analysis_rows(recorded['segments']);selected=lines[:4]
            proposal=dict(summary=[dict(quote=r['text'],segment_id=r['id']) for r in selected],
                          homework=[dict(quote=r['text'],segment_id=r['id']) for r in selected])
            indices=','.join(str(i+1) for i in range(len(selected)))
            tokens=lambda text:re.findall(r'[^\W_]+',text.casefold().replace('ё','е'))
            origin['reference_tokens_match_asr']=tokens(recorded['reference'])==tokens(recorded['text'])
            cases.append(dict(name=item['id'],origin=origin,rows=lines,proposal=proposal,
                              android_response='KEY: '+indices+'\nTASK: '+indices,
                              response_kind='фиксированный выбор строк; модель не запускалась'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Проверены WAV и субтитры: {len(cases)} фрагментов. {args.output}')


if __name__=='__main__':main()
