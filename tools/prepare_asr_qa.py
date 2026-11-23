"""Собрать независимый контроль ClipMic из локальных копий открытых корпусов."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from evaluate_asr import NEGATIONS, audio_sha256, numeric_token, tokens
from prepare_mtedx_asr import NON_SPEECH, PARQUET_SHA256, REVISION, decode


OPENSTT_ARCHIVE = '1d4d35aa8792c63ad35217b9ea5e8e2daf1ee9f79187300c8ab272491923c90b'
OPENSTT_INDEX = '90badb2fdaa3f1354c94ba891c6f973153c25cd0b6ed1f1e597821b308ac11a1'
MTEDX_TALKS = ('As7ngXw-X8U', '7hkxVyhoMoQ', 'dd5R6wgQlp8')
SEED = 'clipmic-asr-qa-2026-11-22:'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def ranked(rows, per_class):
    ordered = sorted(rows, key=lambda row: hashlib.sha256((SEED + row['source_id']).encode()).digest())
    chosen, seen_ids, seen_text = [], set(), set()
    for group, accepts in (
        ('числа', lambda words: any(map(numeric_token, words))),
        ('отрицания', lambda words: bool(NEGATIONS.intersection(words))),
        ('общая речь', lambda words: True),
    ):
        count = 0
        for row in ordered:
            words = tuple(tokens(row['reference']))
            if row['source_id'] in seen_ids or words in seen_text or not accepts(words):
                continue
            chosen.append(dict(row, selection=group))
            seen_ids.add(row['source_id'])
            seen_text.add(words)
            count += 1
            if count == per_class:
                break
        if count != per_class:
            raise ValueError(f'Недостаточно размеченных фраз для отбора «{group}».')
    return chosen


def record(path, row, subset):
    return dict(row, id=path.stem, audio=path.name, audio_sha256=audio_sha256(path), subset=subset)


def openstt(args):
    import numpy as np
    from prepare_rear_row_asr import room_signal, samples, wav, write_wave

    if audio_sha256(args.archive) != OPENSTT_ARCHIVE or audio_sha256(args.index) != OPENSTT_INDEX:
        raise ValueError('Архив или индекс OpenSTT отличаются от проверенной копии.')
    excluded = [row for path in args.exclude for row in load(path) if row.get('source_item')]
    excluded_ids = {row['source_item'] for row in excluded}
    excluded_texts = {tuple(tokens(row['reference'])) for row in excluded}
    with args.index.open(newline='', encoding='utf-8') as stream:
        eligible = {text: audio for audio, text, duration in csv.reader(stream)
                    if 4.5 <= float(duration) <= 14 and audio not in excluded_ids}
    rows = []
    with tarfile.open(args.archive, mode='r|gz') as archive:
        for member in archive:
            audio = eligible.get(member.name)
            if not member.isfile() or audio is None:
                continue
            reference = archive.extractfile(member).read().decode('utf-8').strip()
            words = tuple(tokens(reference))
            if len(words) >= 7 and words not in excluded_texts:
                rows.append(dict(source_id=audio, reference=reference, reference_item=member.name))
    selected = {row['source_id']: row for row in ranked(rows, 8)}
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    with tarfile.open(args.archive, mode='r|gz') as archive:
        for member in archive:
            row = selected.get(member.name)
            if row is None or not member.isfile():
                continue
            stem = 'openstt-' + Path(member.name).stem
            payload = archive.extractfile(member).read()
            row['source_audio_sha256'] = hashlib.sha256(payload).hexdigest()
            path = wav(args.output, stem, payload, '.opus')
            cases.append(record(path, row, 'openstt_lectures'))
            modeled = args.output / (stem + '-room.wav')
            seed = int(Path(member.name).stem, 16)
            write_wave(modeled, room_signal(samples(path), np.random.default_rng(seed)))
            cases.append(record(modeled, dict(row, seed=seed, parent_audio_sha256=audio_sha256(path)),
                                'modeled_room_6db'))
    if len(cases) != 2 * len(selected):
        raise ValueError('Извлечены не все выбранные дорожки OpenSTT.')
    save(args.output / 'manifest.json', sorted(cases, key=lambda case: (case['subset'], case['id'])))


def mtedx(args):
    import pyarrow.parquet as pq

    if audio_sha256(args.parquet) != PARQUET_SHA256:
        raise ValueError('Parquet mTEDx отличается от проверенной ревизии.')
    packet = pq.ParquetFile(args.parquet)
    metadata = packet.read(columns=['id', 'talk_id', 'transcript', 'duration', 'start', 'end']).to_pylist()
    selected = {}
    for talk in MTEDX_TALKS:
        rows = []
        for row in metadata:
            if row['talk_id'] != talk or not 5 <= row['duration'] <= 17:
                continue
            reference = ' '.join(row['transcript'].split())
            if NON_SPEECH.search(reference) or re.search(r'[\[\(]', reference) or len(tokens(reference)) < 7:
                continue
            rows.append(dict(source_id=row['id'], reference=reference, source_start=round(row['start'], 3),
                             source_end=round(row['end'], 3), source_video='https://www.youtube.com/watch?v=' + talk))
        selected.update((row['source_id'], row) for row in ranked(rows, 2))
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    with tempfile.TemporaryDirectory() as temp:
        for batch in packet.iter_batches(batch_size=32, columns=['id', 'audio']):
            for row in batch.to_pylist():
                item = selected.get(row['id'])
                if item is None:
                    continue
                path = args.output / ('mtedx-' + row['id'] + '.wav')
                payload = row['audio']['bytes']
                decode(payload, Path(temp), path)
                cases.append(record(path, dict(item, source_revision=REVISION,
                                               source_audio_sha256=hashlib.sha256(payload).hexdigest()),
                                    'mtedx_public_talks'))
    if {row['source_id'] for row in cases} != selected.keys():
        raise ValueError('Извлечены не все выбранные дорожки mTEDx.')
    save(args.output / 'manifest.json', sorted(cases, key=lambda case: case['id']))


def combine(args):
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for manifest in args.manifests:
        for row in load(manifest):
            source = manifest.parent / row['audio']
            if audio_sha256(source) != row['audio_sha256']:
                raise ValueError(f"{row['id']}: WAV отличается от исходного манифеста.")
            path = args.output / source.name
            if path.exists():
                raise ValueError(f'{path.name}: два входных файла с одним именем.')
            shutil.copyfile(source, path)
            row['audio'] = path.name
            cases.append(row)
    save(args.output / 'manifest.json', cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    lecture = commands.add_parser('openstt')
    lecture.add_argument('archive', type=Path)
    lecture.add_argument('index', type=Path)
    lecture.add_argument('output', type=Path)
    lecture.add_argument('--exclude', type=Path, nargs='+', required=True)
    talk = commands.add_parser('mtedx')
    talk.add_argument('parquet', type=Path)
    talk.add_argument('output', type=Path)
    merged = commands.add_parser('combine')
    merged.add_argument('output', type=Path)
    merged.add_argument('manifests', type=Path, nargs='+')
    args = parser.parse_args()
    {'openstt': openstt, 'mtedx': mtedx, 'combine': combine}[args.command](args)


if __name__ == '__main__':
    main()
