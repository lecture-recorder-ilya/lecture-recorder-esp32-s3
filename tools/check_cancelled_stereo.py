"""Воспроизводимый A/B импорта одного набора WAV, затем штатный локальный ASR."""
import argparse
import array
import hashlib
import json
import shutil
import sys
import time
import wave
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def prepare(repo, output):
    output.mkdir(parents=True, exist_ok=True)
    if (output/'manifest.json').exists():
        raise FileExistsError('Состав уже зафиксирован')
    independent = repo/'work/asr-speed/round4/independent/manifest.json'
    short = repo/'work/asr-speed/round3/reproduced/manifest.json'
    clips = {r['id']: (r, independent.parent) for r in json.loads(independent.read_text())}
    sources = [clips[name] for name in ('golos-1571', 'As7ngXw-X8U_0065',
                                        'openstt-4d70a07ab282', '6hoeGxsHS6c_0164')]
    noise = [(r, short.parent) for r in json.loads(short.read_text()) if not r['reference']]
    chosen = [(r, folder, mode) for r, folder in sources for mode in ('mono', 'antiphase')]
    chosen += [(sources[0][0], sources[0][1], 'identical_stereo'),
               (sources[1][0], sources[1][1], 'almost_antiphase')]
    chosen += [(r, folder, 'antiphase_noise') for r, folder in noise]
    manifest = []
    for row, folder, mode in chosen:
        source = folder/row['audio']
        assert sha(source) == row['audio_sha256']
        with wave.open(str(source)) as stream:
            assert stream.getparams()[:3] == (1, 2, 16000)
            frames = stream.readframes(stream.getnframes())
        name = row['id']+'-'+mode
        target = output/(name+'.wav')
        scaled = False
        if mode == 'mono':
            shutil.copyfile(source, target)
        else:
            values = array.array('h', frames)
            if sys.byteorder != 'little':
                values.byteswap()
            scaled = -32768 in values
            if scaled:
                values = array.array('h', (int(x/2) for x in values))
            stereo = array.array('h')
            for x in values:
                right = x if mode == 'identical_stereo' else -x
                stereo.extend((x, right))
            if mode == 'almost_antiphase':
                stereo[1] += 1
            if sys.byteorder != 'little':
                stereo.byteswap()
            with wave.open(str(target), 'wb') as stream:
                stream.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
                stream.writeframes(stereo.tobytes())
        manifest.append(dict(id=name, audio=target.name, audio_sha256=sha(target), reference=row['reference'],
            subset=mode, source_id=row['id'], source_audio_sha256=sha(source), fixture_scaled_half=scaled,
            condition='Смоделированные каналы из реального исходного PCM; не запись двух микрофонов', terms=[]))
    silent = output/'silent_stereo.wav'
    with wave.open(str(silent), 'wb') as stream:
        stream.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(bytes(3*16000*4))
    manifest.append(dict(id='silent_stereo',audio=silent.name,audio_sha256=sha(silent),reference='',subset='digital_silence',terms=[]))
    dump(output/'manifest.json',manifest)
    dump(output/'lock.json',dict(manifest_sha256=sha(output/'manifest.json'),
        rule='Fixed four source IDs; each mono and exact antiphase; two ordinary stereo controls; '
             'all noise/silence cases of reproduced139 in exact antiphase plus digital stereo silence. '
             'Chosen before A/B. No model-output selection. Original WER counts number formatting.',
        source_manifests={str(independent):sha(independent),str(short):sha(short)},
        files={r['audio']:r['audio_sha256'] for r in manifest}))
    print('Зафиксировано WAV:',len(manifest),'SHA:',sha(output/'manifest.json'))


def run(manifest, source, output):
    if output.exists():
        raise FileExistsError(output)
    sys.path[:0] = [str(source/'outputs/recorder'),str(source/'tools')]
    from audio_import import normalize
    from evaluate_asr import evaluate
    rows = json.loads(manifest.read_text())
    folder = output.parent/(output.stem+'-normalized')
    folder.mkdir(parents=True,exist_ok=True)
    converted, imports = [], []
    for row in rows:
        original = manifest.parent/row['audio']
        assert sha(original)==row['audio_sha256']
        target = folder/(row['id']+'.wav')
        start = time.monotonic()
        normalize(original,target,source)
        imports.append(dict(id=row['id'],input_sha256=sha(original),normalized_sha256=sha(target),
                            import_seconds=time.monotonic()-start))
        converted.append(dict(row,audio=target.name,audio_sha256=sha(target)))
    normalized = folder/'manifest.json'
    dump(normalized,converted)
    report = evaluate(normalized,source)
    report.update(input_manifest_sha256=sha(manifest),source_root=str(source),imports=imports,
                  normalized_manifest_sha256=sha(normalized),audio_import_sha256=sha(source/'outputs/recorder/audio_import.py'))
    dump(output,report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('repo',type=Path);p.add_argument('output',type=Path)
    p=sub.add_parser('run');p.add_argument('manifest',type=Path);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.repo.resolve(),args.output.resolve())
    else:run(args.manifest.resolve(),args.source.resolve(),args.output.resolve())


if __name__=='__main__':
    main()
