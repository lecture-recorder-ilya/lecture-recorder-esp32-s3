import argparse
import hashlib
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlencode
import wave


ROOT = Path(__file__).resolve().parents[1]


def download(url):
    return subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--location',
                                    '--retry', '3', '--retry-delay', '1', '--connect-timeout', '12',
                                    '--max-time', '45', url])


@lru_cache(maxsize=16)
def golos_page(offset, revision):
    query = urlencode(dict(dataset='bond005/sberdevices_golos_100h_farfield', config='default',
                           split='test', offset=offset, length=100, revision=revision))
    page = json.loads(download('https://datasets-server.huggingface.co/rows?'+query))
    return {item['row_idx']: item['row'] for item in page['rows']}


def source(case, revisions):
    if case['corpus'] == 'ESC-50':
        url = f"https://raw.githubusercontent.com/karolpiczak/ESC-50/{revisions['ESC-50']}/audio/{case['source_id']}"
        return download(url), ''
    index = case['source_id']
    row = golos_page(index // 100 * 100, revisions['Golos'])[index]
    url = row['audio'][0]['src']
    if revisions['Golos'] not in url:
        raise ValueError('Изменился исходный фрагмент Golos.')
    return download(url), row['transcription']


def prepare_quiet_holdout(cases, lock):
    revisions = {'Golos': lock['source_revision']}
    manifest = []
    for case in lock['cases']:
        identifier = case['id']
        raw, reference = source(dict(case, corpus='Golos'), revisions)
        digest = hashlib.sha256(raw).hexdigest()
        if (digest != case['source_audio_sha256'] or digest != case['audio_sha256'] or
                hashlib.sha256(reference.encode()).hexdigest() != case['reference_sha256']):
            raise ValueError(f"Изменилось аудио или эталон {identifier}.")
        try:
            with wave.open(BytesIO(raw)) as stream:
                if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                    raise ValueError
                frames = stream.getnframes()
                if not frames or len(stream.readframes(frames)) != frames * 2:
                    raise ValueError
        except (wave.Error, EOFError, ValueError) as error:
            raise ValueError(f"Некорректный WAV PCM16 mono 16 кГц для {identifier}.") from error
        audio = cases/(identifier+'.wav')
        audio.write_bytes(raw)
        manifest.append(dict(id=identifier, audio=audio.name, audio_sha256=digest,
                             reference=reference, subset=case['subset']))
    return manifest


def prepare_sound_checks(cases, work, lock):
    manifest = []
    for case in lock['public_cases']:
        raw, reference = source(case, lock['revisions'])
        if (hashlib.sha256(raw).hexdigest() != case['source_sha256'] or
                hashlib.sha256(reference.encode()).hexdigest() != case['reference_sha256']):
            raise ValueError(f"Изменилось аудио или эталон {case['id']}.")
        original = work/'input.wav'
        original.write_bytes(raw)
        audio = cases/(case['id']+'.wav')
        subprocess.run(['/usr/bin/afconvert', str(original), str(audio), '-f', 'WAVE',
                        '-d', 'LEI16@16000', '-c', '1'], check=True)
        digest = hashlib.sha256(audio.read_bytes()).hexdigest()
        if digest != case['wav_sha256']:
            raise ValueError(f"Проверь версию конвертера для {case['id']}.")
        manifest.append(dict(id=case['id'], audio=audio.name, audio_sha256=digest,
                             reference=reference, subset=case['set']))
    return manifest


def main():
    parser = argparse.ArgumentParser(description='Скачать проверочные записи с единицами и бытовыми шумами для Mac.')
    parser.add_argument('output', type=Path)
    parser.add_argument('--quiet-holdout', action='store_true', help='Скачать зафиксированную выборку тихих записей Golos.')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Выбери новую папку.')
    fixture = 'quiet-holdout.json' if args.quiet_holdout else 'sound-checks.json'
    lock = json.loads((ROOT/'tests/fixtures/asr'/fixture).read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as scratch:
        work = Path(scratch)
        cases = work/'cases'
        cases.mkdir()
        if args.quiet_holdout:
            manifest = prepare_quiet_holdout(cases, lock)
        else:
            manifest = prepare_sound_checks(cases, work, lock)
        (cases/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        cases.rename(args.output)


if __name__ == '__main__':
    main()
