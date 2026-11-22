"""Зафиксировать новые голоса/шумы и управляемые паузы вокруг записанного слова."""
import argparse
from array import array
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import wave

REV='33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6'
CATEGORIES=('keyboard_typing','mouse_click','rain','clock_tick','footsteps','vacuum_cleaner','door_wood_knock','washing_machine')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def words(text):return re.findall(r'[а-яё]+',text.lower())
def write(path,pcm):
    with wave.open(str(path),'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(pcm)
def read(path):
    with wave.open(str(path)) as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,16000):raise ValueError('Нужен PCM16 mono 16 кГц')
        return f.readframes(f.getnframes())
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def independent(manifest,output):
    rows=json.loads(manifest.read_text());result=[];chosen=[]
    for row in rows:
        audio=(manifest.parent/row['audio']).resolve();pcm=read(audio)
        result.append(dict(row,audio=str(audio),subset='independent-whole-short'))
        lexical=words(re.sub(r'\([^)]*\)','',row['reference']))
        if len(lexical)!=1 or not .15<=len(pcm)/32000<2:continue
        chosen.append(row['id'])
        for label,gain in [('right5',1),('quiet-right5',1/16)]:
            values=array('h');values.frombytes(pcm)
            if sys.byteorder!='little':values.byteswap()
            values=array('h',(round(v*gain) for v in values))
            if sys.byteorder!='little':values.byteswap()
            wav=output/(row['id']+'-'+label+'.wav');write(wav,values.tobytes()+bytes(160000-len(pcm)))
            result.append(dict(row,id=row['id']+'-'+label,audio=str(wav.resolve()),audio_sha256=sha(wav),
                               subset='independent-'+label,gain=gain,target=lexical[0],parent_audio_sha256=sha(audio)))
    save(output/'plan.json',dict(source_manifest=str(manifest.resolve()),source_manifest_sha256=sha(manifest),
                                 whole_contexts=len(rows),single_word_ids=chosen,
                                 variants='Целые однословные записи до 5с и gain 1/16; без вырезания слова.'))
    return result


def prepare(args):
    args.output.mkdir(parents=True)
    excluded=set();source_files=set()
    for p in args.exclude:
        for r in json.loads(p.read_text()):
            for key in ('id','source_id'):
                value=str(r.get(key,''));excluded.add(value.removeprefix('mtedx-'))
                if re.match(r'^[1-5]-\d+-',value):source_files.add(value.split('-')[1])
    if args.mode=='independent':
        manifest=independent(args.manifest,args.output)
    elif args.mode=='voices':
        import pyarrow.parquet as pq
        table=pq.read_table(args.parquet);rows=table.drop(['audio']).to_pylist();index={r['id']:i for i,r in enumerate(rows)}
        chosen=[]
        for target in ('не','три','да'):
            candidates=[r for r in rows if r['id'] not in excluded and target in words(r['transcript'])]
            candidates.sort(key=lambda r:(len(words(r['transcript'])),r['id']));talks=set()
            for r in candidates:
                if r['talk_id'] in talks:continue
                chosen.append(dict(r,target=target));talks.add(r['talk_id'])
                if len(talks)==3:break
            if len(talks)!=3:raise ValueError('Не хватает новых контекстов '+target)
        save(args.output/'plan.json',dict(chosen=chosen,parquet_sha256=sha(args.parquet),excludes={str(p):sha(p) for p in args.exclude},
                                         rule='Три кратчайших новых эталона на слово, по одному на выступление. Полный контекст, без вырезания слов. До ASR.'))
        manifest=[]
        for r in chosen:
            raw=table.slice(index[r['id']],1).to_pylist()[0]['audio']['bytes'];flac=args.output/(r['id']+'.flac');flac.write_bytes(raw)
            wav=args.output/(r['id']+'.wav');subprocess.run(['/usr/bin/afconvert',str(flac),str(wav),'-f','WAVE','-d','LEI16@16000','-c','1'],check=True)
            manifest.append(dict(id=r['id'],audio=str(wav.resolve()),reference=re.sub(r'\([^)]*\)','',r['transcript']).strip(),
                                 subset='new-recorded-context',target=r['target'],talk_id=r['talk_id'],source_id=r['id'],
                                 source_audio_sha256=sha(flac),audio_sha256=sha(wav)))
    elif args.mode=='noise':
        prefix=f'https://raw.githubusercontent.com/karolpiczak/ESC-50/{REV}/'
        def get(path):
            return subprocess.check_output(['curl','--fail','--silent','--show-error','--location',
                                            '--retry','2','--max-time','30',prefix+path])
        metadata=get('meta/esc50.csv');(args.output/'esc50.csv').write_bytes(metadata)
        rows=list(csv.DictReader(io.StringIO(metadata.decode('utf-8-sig'))));chosen=[]
        for fold in (1,2):
            for category in CATEGORIES:
                eligible=[r for r in rows if r['fold']==str(fold) and r['category']==category and r['filename'].split('-')[1] not in source_files]
                chosen.append(max(eligible,key=lambda r:r['filename']))
        save(args.output/'plan.json',dict(chosen=chosen,revision=REV,metadata_sha256=sha(args.output/'esc50.csv'),
                                         excludes={str(p):sha(p) for p in args.exclude},rule='Наибольшее имя в fold 1/2 на категорию; прежние исходные Freesound ID исключены. Выбор до ASR.'))
        def fetch(r):
            raw=get('audio/'+r['filename']);original=args.output/('source-'+r['filename']);original.write_bytes(raw)
            wav=args.output/r['filename'];subprocess.run(['/usr/bin/afconvert',str(original),str(wav),'-f','WAVE','-d','LEI16@16000','-c','1'],check=True,capture_output=True)
            return dict(id='new-esc50-'+r['filename'],audio=str(wav.resolve()),reference='',subset='new-environmental-sound',
                        category=r['category'],source_id=r['filename'],source_revision=REV,source_audio_sha256=sha(original),audio_sha256=sha(wav))
        with ThreadPoolExecutor(max_workers=4) as pool:manifest=list(pool.map(fetch,chosen))
    else:
        source=args.source.resolve();pcm=read(source);manifest=[]
        for trim in (0,20,40,60):
            clip=pcm[:len(pcm)-trim*32] if trim else pcm
            for label,left,right in [('isolated',0,0),('right5',0,80000-len(clip)//2),('center5',38400,38400),('prefix064',10240,0),('both064',10240,10240),('center25',198400,198400)]:
                name=f'cut-{trim}ms-{label}';wav=args.output/(name+'.wav');write(wav,bytes(left*2)+clip+bytes(right*2))
                manifest.append(dict(id=name,audio=str(wav.resolve()),reference='не',subset='boundary-diagnostic',
                                     audio_sha256=sha(wav),parent_audio_sha256=sha(source),tail_trim_ms=trim,pad_left_frames=left,pad_right_frames=right,
                                     reference_note='Диагностический срез с возможным соседним звуком; не золотой однословный эталон'))
        save(args.output/'plan.json',dict(source=str(source),source_sha256=sha(source),trim_ms=[0,20,40,60],pads='Заранее заданные паузы; PCM голоса не масштабируется'))
    save(args.output/'manifest.json',manifest)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['voices','noise','boundary','independent'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--exclude',type=Path,action='append',default=[])
    p.add_argument('--parquet',type=Path);p.add_argument('--source',type=Path);p.add_argument('--manifest',type=Path);prepare(p.parse_args())
