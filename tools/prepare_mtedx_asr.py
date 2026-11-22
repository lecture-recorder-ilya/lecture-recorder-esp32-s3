"""Prepare the fixed Russian mTEDx public-talk test clips for local evaluation."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import wave

from evaluate_asr import audio_sha256


REVISION = '89e77b30f14b8c580b19dc51087f675ff90cda07'
PARQUET_SHA256 = '636b6437749db49bfad10e628945fc284afee33c75f874f8a1462b4b8b7a6eb9'
CLIPS = {
    '6hoeGxsHS6c': (2, 16, 26, 51, 82, 132),
    'CPci7a8l-oU': (1, 15, 23, 38, 52, 68),
    'dll-jtmrD70': (1, 26, 46, 66, 97, 113),
}
NON_SPEECH = re.compile(r'\((?:аплодисменты|смех|музыка)\)', re.IGNORECASE)


def decode(audio, scratch, target):
    encoded = scratch / 'clip.flac'
    pcm = scratch / 'clip.wav'
    encoded.write_bytes(audio)
    subprocess.run(['afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1', encoded, pcm], check=True)
    with wave.open(str(pcm)) as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Expected PCM16 mono at 16 kHz after conversion')
        frames = source.readframes(source.getnframes())
    pcm.unlink()
    with wave.open(str(target), 'wb') as dest:
        dest.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        dest.writeframes(frames)


def prepare(parquet, output):
    import pyarrow.parquet as pq

    if audio_sha256(parquet) != PARQUET_SHA256:
        raise ValueError('Unexpected mTEDx test Parquet checksum')
    selected = {f'{talk}_{index:04}' for talk, indexes in CLIPS.items() for index in indexes}
    output.mkdir(parents=True, exist_ok=True)
    cases = {}
    with tempfile.TemporaryDirectory() as temp:
        for batch in pq.ParquetFile(parquet).iter_batches(batch_size=32):
            for row in batch.to_pylist():
                ident = row['id']
                if ident not in selected:
                    continue
                if ident in cases:
                    raise ValueError(f'Duplicate mTEDx segment {ident}')
                path = output / f'{ident}.wav'
                decode(row['audio']['bytes'], Path(temp), path)
                text = row['transcript']
                cases[ident] = {
                    'id': ident, 'audio': path.name,
                    'reference': ' '.join(NON_SPEECH.sub('', text).split()),
                    'reference_source': 'mTEDx Russian subtitles aligned by corpus authors',
                    'source': 'Multilingual TEDx / OpenSLR 100',
                    'source_revision': REVISION, 'source_split': 'ru/test',
                    'source_video': 'https://www.youtube.com/watch?v=' + row['talk_id'],
                    'source_start': round(row['start'], 3), 'source_end': round(row['end'], 3),
                    'source_cues': NON_SPEECH.findall(text),
                    'license': 'CC-BY-NC-ND-4.0',
                    'subset': 'recorded-public-talk',
                    'synthetic_background': False, 'microphone_distance': 'unknown',
                    'audio_sha256': audio_sha256(path),
                }
    if cases.keys() != selected:
        raise ValueError(f'Missing mTEDx segments: {sorted(selected - cases.keys())}')
    manifest = output / 'manifest.json'
    manifest.write_text(json.dumps([cases[key] for key in sorted(cases)], ensure_ascii=False, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parquet', type=Path, help='Pinned deepdml/mtedx Russian test Parquet')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(prepare(args.parquet, args.output))


if __name__ == '__main__':
    main()
