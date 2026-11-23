"""Прогнать непрерывные окна через штатный конвейер распознавания Mac."""

import argparse
from pathlib import Path
import sys
from time import monotonic
from unittest.mock import patch

from evaluate_asr import audio_sha256, indexed_rows
from prepare_asr_qa import load, save


def evaluate(manifest, source, output):
    sys.path.insert(0, str(source / 'outputs/recorder'))
    from qwen_transcribe import run
    from quality_asr import ENGINE

    cases = indexed_rows(load(manifest), 'Лекции')
    directory = output.with_name(output.stem + '-checkpoints')
    directory.mkdir(parents=True, exist_ok=False)
    rows = []
    # Keep the test local and measure ASR without the app's power-saving pauses.
    with patch('power_budget.Budget.checkpoint', return_value=None):
        for index, (ident, case) in enumerate(cases.items()):
            path = manifest.parent / case['audio']
            sha = audio_sha256(path)
            if sha != case['audio_sha256']:
                raise ValueError(f'{ident}: WAV отличается от манифеста.')
            prepared = directory / f'{index:02}.json'
            started = monotonic()
            run(path, prepared, directory / f'{index:02}.progress.json')
            elapsed = monotonic() - started
            cache = load(prepared.with_suffix('.transcript.json'))
            if not cache['complete'] or cache['identity']['audio_sha256'] != sha:
                raise ValueError(f'{ident}: незавершённая расшифровка или другой WAV.')
            rows.append(dict(id=ident, audio_sha256=sha, duration=cache['duration'],
                             elapsed_seconds=round(elapsed, 3), segments=cache['segments'],
                             text=' '.join(row['text'] for row in cache['segments'])))
            print(ident, round(elapsed, 3), flush=True)
    save(output, dict(engine=ENGINE, cases=rows))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.manifest.resolve(), args.source_root.resolve(), args.output.resolve())
