"""Зафиксировать живую короткую речь отдельно от настройки фильтра шума."""
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import wave

RATE = 16000
TARGETS = ('не', 'три', 'да')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def words(text):
    return re.findall(r'[а-яё]+', text.lower())


def clean(text):
    return re.sub(r'\([^)]*\)', '', text).strip()


def select(rows, excluded, count=4):
    selected = []
    for target in TARGETS:
        candidates = [r for r in rows if r['id'] not in excluded and target in words(clean(r['transcript']))]
        candidates.sort(key=lambda r: (len(words(clean(r['transcript']))), r['id']))
        talks = set()
        for row in candidates:
            if row['talk_id'] in talks:
                continue
            selected.append(dict(row, target=target))
            talks.add(row['talk_id'])
            if len(talks) == count:
                break
        if len(talks) != count:
            raise ValueError('Недостаточно разных выступлений для '+target)
    return selected


def sources(args):
    import pyarrow.parquet as pq
    args.output.mkdir(parents=True)
    excluded = set()
    for path in args.exclude:
        for row in json.loads(path.read_text()):
            for key in ('id', 'source_id'):
                value = str(row.get(key, ''))
                excluded.add(value.removeprefix('mtedx-'))
    table = pq.read_table(args.parquet)
    metadata = table.drop(['audio']).to_pylist()
    chosen = select(metadata, excluded, args.count)
    plan = dict(rule='Четыре кратчайших эталона на слово, по одному на выступление; сортировка число слов, ID. Выбор до ASR.',
                targets=TARGETS, count=args.count, sources=chosen, parquet_sha256=sha(args.parquet),
                excludes={str(p.resolve()):sha(p) for p in args.exclude},
                script_sha256=sha(Path(__file__)))
    (args.output/'sources-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n')
    index = {row['id']:i for i,row in enumerate(metadata)}
    manifest = []
    for row in chosen:
        encoded = table.slice(index[row['id']], 1).to_pylist()[0]['audio']['bytes']
        flac = args.output/(row['id']+'.flac');flac.write_bytes(encoded)
        wav = args.output/(row['id']+'.wav')
        subprocess.run(['/usr/bin/afconvert', str(flac), str(wav), '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1'], check=True)
        manifest.append(dict(id=row['id'], audio=str(wav.resolve()), reference=clean(row['transcript']),
                             subset='recorded-context', target=row['target'], source_id=row['id'],
                             talk_id=row['talk_id'], source_start=row['start'], source_end=row['end'],
                             source='Multilingual TEDx / ru/test',
                             source_revision='89e77b30f14b8c580b19dc51087f675ff90cda07',
                             source_audio_sha256=sha(flac), audio_sha256=sha(wav)))
    (args.output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')


def crop_bounds(case, target, duration):
    matches = []
    for kind in ('ctc', 'rnnt'):
        found = []
        for chunk in case['chunks']:
            for trace in chunk['trace']:
                for word in trace[kind]:
                    if words(word['text']) == [target]:
                        found.append((word['start']+chunk['offset'], word['end']+chunk['offset']))
        if found:
            matches.append(dict(kind=kind, start=found[0][0], end=found[0][1]))
    if not matches:
        return None
    nearest = [m for m in matches if abs(m['start']-matches[0]['start']) <= .25]
    left = max(0, min(m['start'] for m in nearest)-.06)
    right = min(duration, max(m['end'] for m in nearest)+.06)
    return dict(start_frame=round(left*RATE), end_frame=round(right*RATE), passes=matches,
                note='Автоматическая акустическая разметка, не ручная фонемная; срез из связной живой речи')


def pcm_scaled(pcm, gain):
    values = array('h');values.frombytes(pcm)
    if sys.byteorder != 'little':
        values.byteswap()
    values = array('h', (round(v*gain) for v in values))
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes()


def crops(args):
    args.output.mkdir(parents=True)
    contexts = json.loads(args.manifest.read_text())
    traces = {r['id']:r for r in json.loads(args.alignment.read_text())['cases']}
    rows, failures = list(contexts), []
    for row in contexts:
        path = Path(row['audio'])
        if sha(path) != row['audio_sha256']:
            raise ValueError('Изменился источник')
        with wave.open(str(path)) as stream:
            if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate()) != (1,2,RATE):
                raise ValueError('Нужен PCM16 mono 16 кГц')
            pcm = stream.readframes(stream.getnframes())
        bounds = crop_bounds(traces[row['id']], row['target'], len(pcm)/2/RATE)
        if bounds is None:
            failures.append(dict(id=row['id'],reason='Нет времён целевого слова; полный контекст оставлен в контроле'))
            continue
        cut = pcm[bounds['start_frame']*2:bounds['end_frame']*2]
        silence = bytes(max(0,5*RATE-len(cut)//2)*2)
        variants = [('isolated', cut, 1), ('center-5s',silence[:len(silence)//4*2]+cut+silence[len(silence)//4*2:],1),
                    ('quiet-center-5s',silence[:len(silence)//4*2]+pcm_scaled(cut,1/16)+silence[len(silence)//4*2:],1/16),
                    ('start-5s',cut+silence,1),('end-5s',silence+cut,1)]
        for variant, data, gain in variants:
            name=row['id']+'-'+row['target']+'-'+variant
            output=args.output/(name+'.wav')
            with wave.open(str(output),'wb') as stream:
                stream.setparams((1,2,RATE,0,'NONE','not compressed'));stream.writeframes(data)
            rows.append(dict(row,id=name,audio=str(output.resolve()),audio_sha256=sha(output),
                             reference=row['target'],subset=variant,parent_audio_sha256=row['audio_sha256'],
                             cut=bounds,gain=gain,synthetic_speech=False,synthetic_silence=variant!='isolated'))
    (args.output/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    plan=dict(context_manifest_sha256=sha(args.manifest),alignment_sha256=sha(args.alignment),
              script_sha256=sha(Path(__file__)),unavailable_cuts=failures,
              rules='Все вырезки сохраняются, независимо от последующего ответа Android; контексты не исключаются.')
    (args.output/'frozen.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    first=modes.add_parser('sources');first.add_argument('parquet',type=Path)
    first.add_argument('--exclude',action='append',type=Path,default=[]);first.add_argument('--count',type=int,default=4)
    second=modes.add_parser('crops');second.add_argument('manifest',type=Path);second.add_argument('alignment',type=Path)
    for mode in (first,second):
        mode.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    (sources if args.mode=='sources' else crops)(args)
