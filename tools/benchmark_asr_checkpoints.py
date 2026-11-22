import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch


def replay(source, snapshot):
    sys.path.insert(0, str(source/'outputs/recorder'))
    import qwen_transcribe
    from quality_asr import Decoder
    from speech_gate import SpeechProfile

    data = json.loads(snapshot.read_text())
    frames = data['completed_frames']
    if not data['complete'] or abs(frames / 16000 - data['duration']) > .001:
        raise ValueError('Для замера нужна полная сохранённая расшифровка.')
    rows = iter(data['segments'])
    remaining = next(rows, None)

    def phrase_rows(text, recognition, offset, start, end, first_id):
        nonlocal remaining
        result = []
        while remaining is not None and remaining['end'] <= end + .011:
            result.append(remaining)
            remaining = next(rows, None)
        return result

    pcm = bytes(24 * 16000 * 2)
    stream = MagicMock()
    stream.getframerate.return_value = 16000
    stream.getsampwidth.return_value = 2
    stream.getnchannels.return_value = 1
    stream.getnframes.return_value = frames
    stream.readframes.side_effect = lambda count: pcm[:count * 2]
    writes = total_bytes = 0
    seconds = 0.
    save = qwen_transcribe.save
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        transcript = root/'result.transcript.json'

        def timed(path, value):
            nonlocal seconds, writes, total_bytes
            started = time.perf_counter()
            save(path, value)
            elapsed = time.perf_counter() - started
            if path == transcript:
                seconds += elapsed
                writes += 1
                total_bytes += path.stat().st_size

        with (patch('wave.open') as open_wav, patch.object(qwen_transcribe, 'save', timed),
              patch.object(qwen_transcribe, 'identity', return_value=data['identity']),
              patch.object(qwen_transcribe, 'phrase_rows', phrase_rows),
              patch.object(qwen_transcribe, 'boundary_at_pause', side_effect=lambda samples, frame, rate: frame),
              patch('speech_gate.speech_profile', side_effect=lambda x: SpeechProfile([], [(0, len(x)/16000)], [])),
              patch.object(Decoder, 'transcribe', return_value='Речь.'),
              patch('power_budget.Budget.checkpoint')):
            open_wav.return_value.__enter__.return_value = stream
            qwen_transcribe.run(root/'input.wav', root/'result.json', root/'progress.json')
        if remaining is not None or json.loads(transcript.read_text()) != data:
            raise ValueError('Содержимое итоговой расшифровки изменилось.')
    return dict(seconds=round(seconds, 4), writes=writes, bytes=total_bytes)


def main():
    parser = argparse.ArgumentParser(description='Замерить только сохранение текста через штатный цикл записи.')
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error('Нужна хотя бы одна пара прогонов.')
    runs = []
    for i in range(args.pairs):
        for version in (('after', 'before') if i % 2 else ('before', 'after')):
            raw = subprocess.check_output([sys.executable, __file__, '--worker',
                                           str(getattr(args, version).resolve()), str(args.snapshot.resolve())])
            runs.append(dict(version=version, pair=i + 1, **json.loads(raw)))
    args.output.write_text(json.dumps(runs, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--worker']:
        print(json.dumps(replay(Path(sys.argv[2]), Path(sys.argv[3]))))
    else:
        main()
