import argparse
import os
import sys
import uuid
import wave
from pathlib import Path


def decode(source, target, max_seconds=8 * 3600):
    import av

    source = Path(source).resolve(strict=True)
    target = Path(target).resolve()
    if not source.is_file() or source == target:
        raise ValueError('Исходная запись и подготовленный WAV должны быть разными файлами.')
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    limit = round(max_seconds * 16000)
    written, origin = 0, None
    try:
        with av.open(str(source)) as container, wave.open(str(temporary), 'wb') as output:
            if not container.streams.audio:
                raise ValueError('В файле нет аудиодорожки.')
            output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)

            def write(frame):
                nonlocal written, origin
                position = round(frame.pts * frame.time_base * 16000) if frame.pts is not None else None
                if origin is None and position is not None:
                    origin = position - written
                start = position - origin if position is not None else written
                if start < written:
                    raise ValueError('В аудиодорожке перекрываются временные метки. Экспортируй её в WAV.')
                if start + frame.samples > limit:
                    raise ValueError('Поддерживаются записи длительностью до 8 часов.')
                while written < start:
                    count = min(16000, start - written)
                    output.writeframesraw(bytes(count * 2))
                    written += count
                data = frame.to_ndarray().astype('<i2', copy=False).tobytes()
                if len(data) != frame.samples * 2:
                    raise ValueError('Не удалось подготовить монофонический звук.')
                output.writeframesraw(data)
                written += frame.samples

            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    write(converted)
            for converted in resampler.resample(None):
                write(converted)
        if not written:
            raise ValueError('В файле нет звуковых отсчётов.')
        os.replace(temporary, target)
        return written / 16000
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    try:
        decode(args.source, args.target)
    except Exception as error:
        print(str(error)[:1000], file=sys.stderr)
        raise SystemExit(2)
