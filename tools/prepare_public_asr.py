"""Подготовить воспроизводимую выборку русской речи FLEURS."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import tarfile
import wave
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, lfilter, sosfilt

REVISION = '70bb2e84b976b7e960aa89f1c648e09c59f894dd'
BASE = f'https://huggingface.co/datasets/google/fleurs/resolve/{REVISION}/data/ru_ru'
RATE = 16000


def download(url):
    return subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--location',
                                    '--connect-timeout', '15', '--max-time', '90', url])


def write_wave(path, signal):
    pcm = np.round(np.clip(signal, -1, 32767 / 32768) * 32768).astype('<i2')
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        stream.writeframes(pcm.tobytes())


def noise(size, rng):
    low = lfilter([1], [1, -.94], rng.normal(size=size))
    wide = rng.normal(size=size)
    return .45 * low / np.sqrt(np.mean(low**2)) + .55 * wide


def room_signal(signal, rng):
    taps = np.zeros(2900)
    taps[[0, 352, 816, 1376, 2048, 2880]] = [1, .56, -.44, .32, -.18, .13]
    reverberant = np.convolve(signal, taps, mode='full')[:signal.size]
    sound = sosfilt(butter(2, (160, 3900), btype='bandpass', fs=RATE, output='sos'), reverberant)
    sound *= .012 / max(np.sqrt(np.mean(sound**2)), 1e-9)
    background = noise(sound.size, rng)
    sound += background * (.012 * 10**(-6/20) / np.sqrt(np.mean(background**2)))
    return sound


def select_clips(reference_by_file, count):
    url = BASE + '/audio/test.tar.gz?download=true'
    command = ['curl', '--fail', '--silent', '--location', '--connect-timeout', '15', '--max-time', '120', url]
    clips = []
    seen = set()
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|gz') as archive:
                for entry in archive:
                    filename = Path(entry.name).name
                    if not entry.isfile() or filename not in reference_by_file or not 0 < entry.size <= 2_000_000:
                        continue
                    ident, reference = reference_by_file[filename]
                    if ident in seen:
                        continue
                    rate, samples = wavfile.read(io.BytesIO(archive.extractfile(entry).read()))
                    if rate != RATE or samples.ndim != 1 or samples.dtype.kind not in ('i', 'f'):
                        raise ValueError(f'Некорректный формат FLEURS: {filename}.')
                    if not 5 * RATE <= samples.size <= 16 * RATE:
                        continue
                    signal = samples.astype(np.float64)
                    if samples.dtype.kind == 'i':
                        signal /= -np.iinfo(samples.dtype).min
                    if not np.isfinite(signal).all() or not np.any(signal):
                        continue
                    seen.add(ident)
                    clips.append((ident, filename, reference, signal))
                    if len(clips) == count:
                        break
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
    if len(clips) != count:
        raise ValueError(f'В архиве найдено {len(clips)} подходящих записей из {count}.')
    return clips


def prepare(output, count, skip=0):
    tsv = download(BASE + '/test.tsv?download=true').decode('utf-8')
    references = {row[1]: (row[0], row[2]) for row in csv.reader(io.StringIO(tsv), delimiter='\t') if len(row) >= 4}
    clips = select_clips(references, skip + count)[skip:]
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for number, (sentence, name, reference, signal) in enumerate(clips, skip + 1):
        for subset, audio in (('clean', signal), ('room-6db', room_signal(signal, np.random.default_rng(number)))):
            ident = f'fleurs-{number:02}-{subset}'
            path = output / (ident + '.wav')
            write_wave(path, audio)
            cases.append({'id': ident, 'audio': path.name, 'reference': reference,
                          'subset': subset, 'source': 'google/fleurs', 'source_file': name, 'sentence_id': sentence,
                          'source_revision': REVISION, 'audio_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    for name, data in (('silence', np.zeros(RATE * 8)), ('noise', .01 * noise(RATE * 8, np.random.default_rng(2026)))):
        path = output / (name + '.wav')
        write_wave(path, data)
        cases.append({'id': name, 'audio': path.name, 'reference': '', 'subset': 'control', 'synthetic': True,
                      'audio_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = output / 'manifest.json'
    manifest.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--count', type=int, default=24, choices=range(1, 49), metavar='1–48')
    parser.add_argument('--skip', type=int, default=0, metavar='N',
                        help='Пропустить первые N подходящих фраз, чтобы собрать независимую выборку.')
    args = parser.parse_args()
    if not 0 <= args.skip <= 144:
        parser.error('--skip должен быть в диапазоне 0–144.')
    print(prepare(args.output, args.count, args.skip))


if __name__ == '__main__':
    main()
