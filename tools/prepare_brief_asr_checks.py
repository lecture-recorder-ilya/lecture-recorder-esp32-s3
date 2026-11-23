import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import wave

from prepare_asr_sound_checks import ROOT, source
from prepare_mtedx_asr import PARQUET_SHA256


def check(data, expected, label):
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'Не совпал SHA-256 для {label}.')


def talks(parquet, ids):
    import pyarrow.parquet as pq
    with parquet.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != PARQUET_SHA256:
            raise ValueError('Изменился набор mTEDx ru/test.')
    found = {}
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=32, columns=['id', 'audio', 'transcript']):
        for row in batch.to_pylist():
            if row['id'] in ids:
                found[row['id']] = row['audio']['bytes'], re.sub(r'\([^)]*\)', '', row['transcript']).strip()
    if set(found) != ids:
        raise ValueError('В наборе mTEDx отсутствуют записи из списка проверки.')
    return found


def variants(directory, cut):
    with wave.open(str(directory/(cut['source_id']+'.wav'))) as source_wav:
        source_wav.setpos(cut['start_frame'])
        pcm = source_wav.readframes(cut['end_frame']-cut['start_frame'])
    spare = 80000 - len(pcm) // 2
    rows = []
    for kind, expected in cut['wav_sha256'].items():
        name = cut['source_id'] + '-' + cut['target'] + '-' + kind
        path = directory/(name+'.wav')
        samples = pcm
        if kind == 'quiet-center-5s':
            samples = b''.join(struct.pack('<h', round(value / 16)) for value, in struct.iter_unpack('<h', pcm))
        if kind != 'isolated':
            left = {'start-5s': 0, 'end-5s': spare, 'center-5s': spare // 2, 'quiet-center-5s': spare // 2}[kind]
            samples = bytes(2 * left) + samples + bytes(2 * (spare - left))
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'none'))
            stream.writeframes(samples)
        check(path.read_bytes(), expected, name)
        rows.append(dict(id=name, audio=path.name, reference=cut['target'], subset=kind, audio_sha256=expected))
    return rows


def main():
    parser = argparse.ArgumentParser(description='Восстановить контроль короткой речи, дальних команд и шумов.')
    parser.add_argument('parquet', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Выбери новую папку.')
    lock = json.loads((ROOT/'tests/fixtures/asr/brief-checks.json').read_text())
    cases = lock['public_cases']
    speech = talks(args.parquet, {case['source_id'] for case in cases if case['corpus'] == 'mTEDx'})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as scratch:
        work = Path(scratch)
        directory = work/'samples'
        directory.mkdir()
        rows = []
        for case in cases:
            if case['corpus'] == 'mTEDx':
                raw, reference = speech[case['source_id']]
                original = work/'input.flac'
            else:
                raw, reference = source(case, lock['revisions'])
                original = work/'input.wav'
            check(raw, case['source_sha256'], case['id'])
            check(reference.encode(), case['reference_sha256'], case['id'])
            original.write_bytes(raw)
            output = directory/(case['id']+'.wav')
            subprocess.run(['/usr/bin/afconvert', str(original), str(output), '-f', 'WAVE',
                            '-d', 'LEI16@16000', '-c', '1'], check=True)
            check(output.read_bytes(), case['wav_sha256'], case['id'])
            rows.append(dict(id=case['id'], audio=output.name, reference=reference,
                             subset=case['set'], audio_sha256=case['wav_sha256']))
        for cut in lock['cuts']:
            rows.extend(variants(directory, cut))
        (directory/'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
        directory.rename(args.output)


if __name__ == '__main__':
    main()
