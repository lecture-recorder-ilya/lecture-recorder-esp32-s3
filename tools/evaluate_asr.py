import argparse
import hashlib
import json
import re
import sys
import time
import wave
from collections import Counter
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


EDIT_OPERATIONS = ('substitutions', 'deletions', 'insertions')


def word_edits(expected, actual):
    """Return one minimal alignment, preferring substitution, deletion, insertion on ties."""
    row = list(range(len(actual) + 1))
    trace = [bytearray([0] + [3] * len(actual))]
    for i, value in enumerate(expected, 1):
        prior, row = row, [i]
        directions = bytearray([2])
        for j, other in enumerate(actual, 1):
            diagonal = prior[j - 1] + (value != other)
            delete, insert = prior[j] + 1, row[-1] + 1
            best = min(diagonal, delete, insert)
            row.append(best)
            if best == diagonal:
                directions.append(int(value != other))
            else:
                directions.append(2 if best == delete else 3)
        trace.append(directions)
    edits = []
    i, j = len(expected), len(actual)
    while i or j:
        direction = trace[i][j]
        if direction:
            edits.append({
                'op': EDIT_OPERATIONS[direction - 1],
                'reference_index': i - 1 if direction != 3 else None,
                'hypothesis_index': j - 1 if direction != 2 else None,
                'reference': expected[i - 1] if direction != 3 else None,
                'hypothesis': actual[j - 1] if direction != 2 else None,
            })
        i -= direction != 3
        j -= direction != 2
    return list(reversed(edits))


def phrase_count(words, phrase):
    return sum(words[index:index+len(phrase)] == phrase
               for index in range(len(words)-len(phrase)+1))


NEGATIONS = set('не ни нет без'.split())
NUMBER_WORDS = set((
    'ноль нуль нуля один одна одно два две двух три трех четыре четырех пять пяти шесть шести '
    'семь семи восемь восьми девять девяти десять десяти одиннадцать двенадцать тринадцать '
    'четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать двадцати '
    'тридцать тридцати сорок сорока пятьдесят пятидесяти шестьдесят шестидесяти семьдесят семидесяти '
    'восемьдесят восьмидесяти девяносто девяноста сто двести триста '
    'четыреста пятьсот шестьсот семьсот восемьсот девятьсот тысяча тысячи тысяч '
    'миллион миллиона миллионов миллиард миллиарда миллиардов'
).split())


def count_errors(expected, actual):
    return dict(missed=sum((expected-actual).values()), extra=sum((actual-expected).values()))


def numeric_token(word):
    return word in NUMBER_WORDS or bool(re.fullmatch(r'\d+[а-я]*', word))


def numbers(words):
    return Counter(word for word in words if numeric_token(word))


def negations(words):
    return Counter(word for word in words if word in NEGATIONS)


def score(reference, hypothesis, critical_phrases=()):
    expected, actual = tokens(reference), tokens(hypothesis)
    letters, recognized = ''.join(expected), ''.join(actual)
    edits = word_edits(expected, actual)
    counts = Counter(edit['op'] for edit in edits)
    errors = len(edits)
    critical, found = Counter(), Counter()
    if not isinstance(critical_phrases, (tuple, list)) or not all(isinstance(phrase, str) for phrase in critical_phrases):
        raise ValueError('Критические фразы должны быть списком строк.')
    for phrase in critical_phrases:
        words = tokens(phrase)
        key = ' '.join(words)
        if not words or not (count := phrase_count(expected, words)):
            raise ValueError(f'Критическая фраза отсутствует в эталоне: {phrase!r}')
        critical[key] = count
        found[key] = phrase_count(actual, words)
    return dict(reference_words=len(expected), word_errors=errors,
                word_error_breakdown={key: counts[key] for key in EDIT_OPERATIONS}, word_edits=edits,
                wer=errors/len(expected) if expected else None,
                cer=distance(letters, recognized)/len(letters) if letters else None,
                hallucinated_words=len(actual) if not expected else 0,
                critical_phrases=count_errors(critical, found),
                numeric_tokens=count_errors(numbers(expected), numbers(actual)),
                negations=count_errors(negations(expected), negations(actual)))


def audio_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def indexed_rows(rows, label):
    if not isinstance(rows, list):
        raise ValueError(f'{label}: ожидается список записей.')
    index = {}
    for row in rows:
        name = row.get('id') if isinstance(row, dict) else None
        if not isinstance(name, str) or not name or name in index:
            raise ValueError(f'{label}: нужен неповторяющийся id у каждой записи.')
        index[name] = row
    if not index:
        raise ValueError(f'{label}: пустой набор.')
    return index


def summarize_scores(rows):
    words = sum(row['reference_words'] for row in rows)
    errors = sum(row['word_errors'] for row in rows if row['reference_words'])
    summary = dict(clips=len(rows), reference_words=words, word_errors=errors,
                   wer=errors/words if words else None,
                   hallucinated_words=sum(row['hallucinated_words'] for row in rows),
                   noise_cases=sum(not row['reference_words'] for row in rows),
                   failed_noise_cases=sum(row['hallucinated_words'] > 0 for row in rows))
    summary['word_error_breakdown'] = {
        kind: sum(row['word_error_breakdown'][kind] for row in rows if row['reference_words'])
        for kind in EDIT_OPERATIONS
    }
    if all('elapsed_seconds' in row and 'duration' in row for row in rows):
        duration = sum(row['duration'] for row in rows)
        elapsed = sum(row['elapsed_seconds'] for row in rows)
        summary.update(duration_seconds=round(duration, 3), elapsed_seconds=round(elapsed, 3),
                       real_time_factor=elapsed / duration if duration else None)
    for metric in ('critical_phrases', 'numeric_tokens', 'negations'):
        summary[metric] = {kind: sum(row[metric][kind] for row in rows) for kind in ('missed', 'extra')}
    return summary


def summarize_subsets(rows):
    groups = {}
    for row in rows:
        subset = row.get('subset')
        if isinstance(subset, str) and subset:
            groups.setdefault(subset, []).append(row)
    return {subset: summarize_scores(group) for subset, group in groups.items()}


def compare_transcripts(manifest, paths):
    cases = indexed_rows(json.loads(manifest.read_text()), 'Эталон')
    for name, case in cases.items():
        if not isinstance(case.get('reference'), str) or not isinstance(case.get('audio'), str) or not case['audio']:
            raise ValueError(f'{name}: укажи путь WAV и эталонный текст.')
    hashes = {name: audio_sha256(manifest.parent/case['audio']) for name, case in cases.items()}
    systems = {}
    for label, path in paths.items():
        data = json.loads(path.read_text())
        results = indexed_rows(data.get('cases') if isinstance(data, dict) else data, label)
        if results.keys() != cases.keys():
            raise ValueError(f'{label}: состав записей отличается от эталона.')
        rows = []
        for name, case in cases.items():
            result = results[name]
            if result.get('audio_sha256') != hashes[name]:
                raise ValueError(f'{label}, {name}: SHA-256 WAV не совпадает с эталоном.')
            if not isinstance(result.get('text'), str):
                raise ValueError(f'{label}, {name}: ожидается текст расшифровки.')
            rows.append(dict(id=name, subset=case.get('subset'),
                             **score(case['reference'], result['text'], case.get('critical_phrases', []))))
        systems[label] = dict(summary=summarize_scores(rows), subsets=summarize_subsets(rows), cases=rows)
    return dict(audio_sha256=hashes, systems=systems)


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
    engine = getattr(decoder, 'engine', ENGINE)
    try:
        for case in cases:
            path = manifest.parent/case['audio']
            sha = audio_sha256(path)
            if case.get('audio_sha256', sha) != sha:
                raise ValueError(f"{case['id']}: SHA-256 WAV не совпадает с манифестом.")
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
                if getattr(decoder, 'engine', ENGINE) != engine:
                    raise RuntimeError('Набор моделей изменился во время проверки. Повтори сравнение.')
                if phrase_rows:
                    rows.extend(phrase_rows(text, decoder.last, left/16000, offset/16000,
                                            min(len(audio), offset+320000)/16000, len(rows)))
                elif text:
                    rows.append(dict(start=offset/16000, end=min(len(audio), offset+320000)/16000, text=text))
            text = ' '.join(row['text'] for row in rows)
            elapsed = time.monotonic() - started
            result = dict(id=case['id'], subset=case.get('subset'), audio_sha256=sha,
                          duration=len(audio)/16000, elapsed_seconds=round(elapsed, 3),
                          reference=case['reference'], text=text, segments=rows,
                          **score(case['reference'], text, case.get('critical_phrases', [])))
            results.append(result)
            print(case['id'], result['word_errors'], '/', result['reference_words'], text, flush=True)
    finally:
        decoder.close()
    return dict(engine=engine, source='synthetic' if all(case.get('synthetic') is True for case in cases) else 'provided',
                normalization='Нижний регистр, ё→е, без пунктуации; цифры и слова не приравниваются.',
                **summarize_scores(results),
                subsets=summarize_subsets(results), cases=results)


def main():
    parser = argparse.ArgumentParser(description='Проверка распознавания по записям с эталонным текстом.')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', action='append', metavar='СИСТЕМА=JSON',
                        help='Сравнить готовые транскрипты одних WAV. JSON содержит список '
                             'объектов с id, audio_sha256 и text. Укажи флаг для каждой системы.')
    args = parser.parse_args()
    if args.compare:
        paths = {}
        for value in args.compare:
            label, separator, path = value.partition('=')
            if not separator or not label.strip() or not path or label in paths:
                parser.error('Для --compare нужен уникальный ярлык и путь в формате СИСТЕМА=JSON.')
            paths[label] = Path(path)
        if len(paths) < 2:
            parser.error('Для сравнения нужны минимум две системы.')
        try:
            report = compare_transcripts(args.manifest.resolve(), paths)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    else:
        report = evaluate(args.manifest.resolve(), args.source_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
