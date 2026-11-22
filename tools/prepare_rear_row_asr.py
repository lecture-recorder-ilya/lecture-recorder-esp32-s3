import argparse
import csv
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import wave
from pathlib import Path, PurePosixPath

import numpy as np

from prepare_public_asr import RATE, download, noise, room_signal, write_wave

OPENSTT_MD5 = '184a4d0a2016f8f5359bd4365a488fe5'
GOLOS = 'bond005/sberdevices_golos_100h_farfield'
GOLOS_REVISION = 'c93949f7140beef4adc404e7b54841e957f81c54'


def digest(path, kind='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, kind).hexdigest()


def wav(directory, name, payload, extension):
    output = directory / (name + '.wav')
    with tempfile.TemporaryDirectory() as temp:
        original = Path(temp) / ('audio' + extension)
        converted = Path(temp) / 'audio.wav'
        original.write_bytes(payload)
        subprocess.run(['/usr/bin/afconvert', str(original), str(converted), '-f', 'WAVE',
                        '-d', 'LEI16@16000', '-c', '1'], check=True, capture_output=True)
        output.write_bytes(converted.read_bytes())
    return output


def samples(path):
    with wave.open(str(path)) as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, RATE):
            raise ValueError('Ожидается моно WAV PCM16 16 кГц.')
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768


def entry(path, reference, subset, **source):
    return dict(id=path.stem, audio=path.name, audio_sha256=digest(path),
                reference=reference, subset=subset, **source)


def lectures(args):
    if digest(args.archive, 'md5') != OPENSTT_MD5:
        raise ValueError('Архив OpenSTT отличается от указанной версии.')
    with args.index.open(newline='') as stream:
        selected = [row for row in csv.reader(stream) if 4.5 <= float(row[2]) <= 10]
    selected.sort(key=lambda row: hashlib.sha256(('clipmic-lectures-v1:' + row[0]).encode()).digest())
    splits = [[], []]
    with tarfile.open(args.archive) as archive:
        seen = set()
        for audio, text, _ in selected:
            source = PurePosixPath(audio)
            reference = archive.extractfile(text).read().decode('utf-8').strip()
            normalized = re.sub(r'[^\w ]', '', reference.casefold().replace('ё', 'е'))
            if len(normalized.split()) < 7 or normalized in seen:
                continue
            seen.add(normalized)
            if len(seen) <= args.skip:
                continue
            split = 0 if len(splits[0]) < 2 * args.development else 1
            if split == 1 and len(splits[1]) == 2 * args.holdout:
                break
            name = 'lecture-' + source.stem
            path = wav(args.output, name, archive.extractfile(audio).read(), '.opus')
            metadata = dict(source='OpenSTT public_lecture_1', source_item=audio,
                            reference_source='субтитры корпуса', microphone_distance=None)
            splits[split].append(entry(path, reference, 'openstt_original', **metadata))
            seed = int(source.stem, 16)
            room = args.output / (name + '-room.wav')
            write_wave(room, room_signal(samples(path), np.random.default_rng(seed)))
            splits[split].append(entry(room, reference, 'openstt_simulated_room', synthetic=True, **metadata))
    return splits


def farfield(args):
    index = json.loads(args.golos_index.read_text())
    if index['dataset'] != GOLOS or index['split'] != 'test':
        raise ValueError('Ожидается тестовая выборка Golos Farfield.')
    rows = sorted(index['rows'], key=lambda row: hashlib.sha256(
        f"clipmic-golos-v1:{row['row_idx']}".encode()).digest())
    result = []
    for item in rows:
        row_id, row = item['row_idx'], item['row']
        text = row['transcription']
        url = row['audio'][0]['src']
        if len(text.split()) < 4 or GOLOS_REVISION not in url:
            continue
        name = f'golos-{row_id:04}'
        suffix = PurePosixPath(url.split('?', 1)[0]).suffix or '.wav'
        path = wav(args.output, name, download(url), suffix)
        result.append(entry(path, text, 'golos_farfield', source=GOLOS, source_item=row_id,
                            source_revision=GOLOS_REVISION, microphone_distance=None))
        if len(result) == args.golos:
            break
    return result


def save(directory, name, rows):
    for seed in (7721, 7722):
        path = directory / f'{name}-noise-{seed}.wav'
        signal = np.zeros(6 * RATE) if seed == 7721 else .012 * noise(6 * RATE, np.random.default_rng(seed))
        write_wave(path, signal)
        rows.append(entry(path, '', 'no_speech', synthetic=True))
    (directory / (name + '.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Собрать одинаковые WAV для сравнения распознавалок.')
    parser.add_argument('archive', type=Path)
    parser.add_argument('index', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--development', type=int, default=18)
    parser.add_argument('--holdout', type=int, default=36)
    parser.add_argument('--skip', type=int, default=0)
    parser.add_argument('--golos-index', type=Path)
    parser.add_argument('--golos', type=int, default=24)
    args = parser.parse_args()
    if min(args.development, args.holdout, args.golos) < 1 or args.skip < 0:
        parser.error('Проверь число записей и пропуск.')
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        parser.error('Укажи пустую папку для нового прогона.')
    development, holdout = lectures(args)
    if len(development) != 2 * args.development or len(holdout) != 2 * args.holdout:
        raise ValueError('В архиве не хватило подходящих лекционных фрагментов.')
    save(args.output, 'development', development)
    save(args.output, 'holdout', holdout)
    if args.golos_index:
        checks = farfield(args)
        if len(checks) != args.golos:
            raise ValueError('В индексе не хватило размеченных записей Golos.')
        save(args.output, 'farfield', checks)


if __name__ == '__main__':
    main()
