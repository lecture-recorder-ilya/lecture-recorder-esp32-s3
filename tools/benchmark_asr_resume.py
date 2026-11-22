"""Exercise the production Mac ASR checkpoint on a deterministic, long PCM WAV."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
from unittest.mock import patch
import wave

from evaluate_asr import audio_sha256


RATE = 16000
WINDOW = 20 * RATE
MINUTE_BYTES = 60 * RATE * 2
SOURCE = Path(__file__).resolve().parents[1] / 'outputs/recorder'


def build_wav(path, sources, minutes):
    # Alternate supplied excerpts without changing the samples. Each minute
    # contains up to 30 seconds of source audio, then digital silence.
    blocks = []
    for audio in sources:
        with wave.open(str(audio)) as stream:
            if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (RATE, 1, 2):
                raise ValueError(f'{audio}: expected PCM16 mono at 16 kHz')
            data = stream.readframes(30 * RATE)
        if not data:
            raise ValueError(f'{audio}: empty source')
        blocks.append((len(data) // 2, data.ljust(MINUTE_BYTES, b'\0')))
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        for minute in range(minutes):
            stream.writeframesraw(blocks[minute % len(blocks)][1])
    return sum(blocks[i % len(blocks)][0] for i in range(minutes)) / RATE


def read_checkpoint(path):
    return json.loads(path.read_text())


def snapshot(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def worker(folder, phase, interrupt_frame):
    sys.path.insert(0, str(SOURCE))
    from qwen_transcribe import run

    audio = folder / 'lecture-2026-01-01-00-00-00.wav'
    cache = folder / 'result.transcript.json'
    existing = read_checkpoint(cache) if cache.exists() else {}
    start = existing.get('completed_frames', 0)
    first = None
    windows = 0
    started = time.monotonic()

    def log():
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        multiplier = 1 if sys.platform == 'darwin' else 1024
        (folder / f'{phase}.json').write_text(json.dumps({
            'wall_seconds': time.monotonic() - started, 'peak_rss_mib': peak * multiplier / 2**20,
            'start_frame': start, 'first_checkpoint_frame': first, 'windows': windows,
        }, indent=2) + '\n')

    def after_checkpoint(*, force=False):
        nonlocal first, windows
        # qwen_transcribe calls Budget only after committing its checkpoint.
        windows += 1
        if first is None or interrupt_frame:
            frames = read_checkpoint(cache)['completed_frames']
            if first is None:
                first = frames
            if not interrupt_frame or frames < interrupt_frame:
                return
            log()
            os.kill(os.getpid(), signal.SIGKILL)

    with patch('power_budget.Budget.checkpoint', side_effect=after_checkpoint):
        run(audio, folder / 'result.json', folder / 'progress.json')
    log()


def benchmark(folder, sources, minutes, interrupt_at):
    folder.mkdir(parents=True)
    audio = folder / 'lecture-2026-01-01-00-00-00.wav'
    source_seconds = build_wav(audio, sources, minutes)
    sha = audio_sha256(audio)
    cache = folder / 'result.transcript.json'
    phases = {}

    def run_phase(phase, stop_frame=0):
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   str(folder), phase, str(stop_frame)]
        expected = -signal.SIGKILL if stop_frame else 0
        result = subprocess.run(command)
        if result.returncode != expected:
            raise RuntimeError(f'{phase}: expected process status {expected}, got {result.returncode}')
        phases[phase] = json.loads((folder / f'{phase}.json').read_text())
        return read_checkpoint(cache)

    before = run_phase('interrupted', interrupt_at * RATE)
    prefix = before['segments']
    if before['complete'] or not prefix or before['completed_frames'] != interrupt_at * RATE:
        raise RuntimeError('Interruption did not leave the expected usable checkpoint')
    after = run_phase('resumed')
    if (not after['complete'] or after['completed_frames'] != minutes * 60 * RATE
            or phases['resumed']['first_checkpoint_frame'] != before['completed_frames'] + WINDOW
            or after['segments'][:len(prefix)] != prefix or after['identity']['audio_sha256'] != sha):
        raise RuntimeError('Resumption did not keep the prefix or finish the same WAV')
    warm = run_phase('complete_cache')
    if warm != after or phases['complete_cache']['windows']:
        raise RuntimeError('Opening a complete cache performed new decoding')
    seconds = minutes * 60
    wall = sum(phases[name]['wall_seconds'] for name in ('interrupted', 'resumed'))
    result = dict(
        duration_seconds=seconds, source_audio_seconds=source_seconds, synth_layout='30s source + silence per minute',
        audio_sha256=sha, source_audio_sha256={str(item): audio_sha256(item) for item in sources},
        engine=after['engine'], economy_mode=False, phases=phases,
        real_time_factor=wall / seconds, peak_rss_mib=max(row['peak_rss_mib'] for row in phases.values()),
        checkpoint_seconds=before['completed_frames'] / RATE, checkpoint_segments=len(prefix),
        segments=len(after['segments']), preserved_prefix_sha256=snapshot(prefix),
    )
    (folder / 'benchmark.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def main():
    if sys.argv[1:2] == ['--worker']:
        _, _, folder, phase, stop = sys.argv
        worker(Path(folder), phase, int(stop))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='A new directory for the WAV, cache and measurements')
    parser.add_argument('inputs', nargs='+', type=Path, help='PCM mono 16 kHz source excerpts to cycle')
    parser.add_argument('--minutes', type=int, default=90)
    parser.add_argument('--interrupt-at', type=int, default=300, metavar='SECONDS')
    args = parser.parse_args()
    if not 0 < args.interrupt_at < args.minutes * 60 or args.interrupt_at % 20:
        parser.error('--interrupt-at must be a positive multiple of 20 within the WAV')
    benchmark(args.output.resolve(), [path.resolve() for path in args.inputs], args.minutes, args.interrupt_at)


if __name__ == '__main__':
    main()
