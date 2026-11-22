import argparse
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlencode



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


def main():
    parser = argparse.ArgumentParser(description='Скачать проверочные записи с единицами и бытовыми шумами для Mac.')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Выбери новую папку.')
    lock = json.loads((ROOT/'docs/asr-speed-checks-2026-11-22.json').read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as scratch:
        work = Path(scratch)
        cases = work/'cases'
        cases.mkdir()
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
        (cases/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        cases.rename(args.output)


if __name__ == '__main__':
    main()
