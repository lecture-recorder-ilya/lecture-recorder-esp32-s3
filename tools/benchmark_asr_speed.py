import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import wave


def measure(source, audio, folder):
    sys.path.insert(0, str(source/'outputs/recorder'))
    import power_budget
    import qwen_transcribe

    folder.mkdir()
    power_budget.CONFIG = folder/'ai-settings.json'
    power_budget.CONFIG.write_text(json.dumps({'economical': False}))
    cache = folder/'result.transcript.json'
    first = None
    save = qwen_transcribe.save

    def timed_save(path, data):
        nonlocal first
        save(path, data)
        if first is None and path == cache and data.get('segments'):
            first = time.perf_counter() - started

    qwen_transcribe.save = timed_save
    started = time.perf_counter()
    qwen_transcribe.run(audio, folder/'result.json', folder/'progress.json')
    elapsed = time.perf_counter() - started
    transcript = json.loads(cache.read_text())
    if not transcript['complete']:
        raise RuntimeError('Расшифровка не завершена.')
    rows = transcript['segments']
    evidence = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    return dict(seconds=round(elapsed, 3), first_phrase_seconds=round(first, 3) if first is not None else None,
                engine=transcript['engine'], wav_sha256=transcript['identity']['audio_sha256'],
                segments=len(rows), segments_sha256=hashlib.sha256(evidence).hexdigest())


def main():
    parser = argparse.ArgumentParser(description='Замер распознавания на одном WAV с чистым кэшем каждого запуска.')
    parser.add_argument('audio', type=Path)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', default=3, type=int)
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error('Число пар должно быть положительным.')
    audio = args.audio.resolve()
    with wave.open(str(audio)) as reader, audio.open('rb') as stream:
        seconds = reader.getnframes()/reader.getframerate()
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {'before': args.before.resolve(), 'after': args.after.resolve()}
    runs = []
    for pair in range(args.pairs):
        for name in (('after', 'before') if pair % 2 else ('before', 'after')):
            folder = (args.output/f'{pair+1}-{name}').resolve()
            subprocess.run([sys.executable, __file__, '--worker', str(sources[name]), str(audio), str(folder)], check=True)
            row = json.loads((folder/'timing.json').read_text())
            if row['wav_sha256'] != sha:
                raise ValueError('Исходный звук изменился между прогонами.')
            runs.append(dict(version=name, pair=pair+1, **row))
            print(name, row['seconds'], flush=True)
    (args.output/'report.json').write_text(json.dumps(dict(audio_seconds=seconds, wav_sha256=sha, runs=runs), indent=2)+'\n')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--worker']:
        source, audio, folder = map(Path, sys.argv[2:])
        (folder/'timing.json').write_text(json.dumps(measure(source, audio, folder), indent=2)+'\n')
    else:
        main()
