import argparse
import hashlib
import json
import re
import sys
import time
import wave
from pathlib import Path


def tokens(text):
    return re.findall(r'[^\W_]+', text.casefold().replace('ё', 'е'))


def distance(left, right):
    row = list(range(len(right)+1))
    for i, value in enumerate(left, 1):
        next_row = [i]
        for j, other in enumerate(right, 1):
            next_row.append(min(next_row[-1]+1, row[j]+1, row[j-1]+(value != other)))
        row = next_row
    return row[-1]


def score(reference, hypothesis):
    expected, actual = tokens(reference), tokens(hypothesis)
    letters, recognized = ''.join(expected), ''.join(actual)
    errors = distance(expected, actual)
    return dict(reference_words=len(expected), word_errors=errors,
                wer=errors/len(expected) if expected else None,
                cer=distance(letters, recognized)/len(letters) if letters else None,
                hallucinated_words=len(actual) if not expected else 0)


def evaluate(manifest, source_root):
    import numpy as np
    sys.path.insert(0, str(source_root/'outputs/recorder'))
    from quality_asr import Decoder, ENGINE
    from speech_quality import clean_asr_text
    try:
        from asr_segments import phrase_rows
    except ImportError:
        phrase_rows = None
    cases = json.loads(manifest.read_text())
    decoder, results = Decoder(), []
    try:
        for case in cases:
            path = manifest.parent/case['audio']
            with wave.open(str(path)) as stream:
                if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
                    raise ValueError('Для проверки нужен WAV PCM16 mono 16 кГц.')
                audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32)/32768
            started = time.monotonic()
            rows = []
            for offset in range(0, len(audio), 320000):
                left, right = max(0, offset-32000), min(len(audio), offset+352000)
                text = clean_asr_text(decoder.transcribe(audio[left:right], case.get('terms', []),
                                      emit_start=(offset-left)/16000, emit_end=(min(len(audio), offset+320000)-left)/16000))
                if phrase_rows:
                    rows.extend(phrase_rows(text, decoder.last, left/16000, offset/16000,
                                            min(len(audio), offset+320000)/16000, len(rows)))
                elif text:
                    rows.append(dict(start=offset/16000, end=min(len(audio), offset+320000)/16000, text=text))
            text = ' '.join(row['text'] for row in rows)
            result = dict(id=case['id'], audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          duration=len(audio)/16000, elapsed_seconds=round(time.monotonic()-started, 3),
                          reference=case['reference'], text=text, segments=rows, **score(case['reference'], text))
            results.append(result)
            print(case['id'], result['word_errors'], '/', result['reference_words'], text, flush=True)
    finally:
        decoder.close()
    count = sum(case['reference_words'] for case in results)
    return dict(engine=ENGINE, source='synthetic' if all(case.get('synthetic') is True for case in cases) else 'provided',
                normalization='Нижний регистр, ё→е, без пунктуации; цифры и слова не приравниваются.',
                word_errors=sum(case['word_errors'] for case in results), reference_words=count,
                wer=sum(case['word_errors'] for case in results)/count if count else None, cases=results)


def main():
    parser = argparse.ArgumentParser(description='Проверка распознавания по записям с эталонным текстом.')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.manifest.resolve(), args.source_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
