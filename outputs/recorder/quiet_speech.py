from asr_guard import join_words, lexical, prepare, speech_windows, supported_words

_MINIMUM_CONFIDENCE = {'ctc': .82, 'rnnt': .60, 'char': .89}


def _midpoint(word):
    return (word['start'] + word['end']) / 2


def _word_key(text):
    if any(character.isdigit() for character in text):
        return text.casefold().rstrip('.!?;:')
    return lexical(text)


def _consensus(load, audio, ranges):
    recognized = {}
    signature = None
    for model, threshold in _MINIMUM_CONFIDENCE.items():
        result = load(model).recognize(audio, sample_rate=16000)
        words = supported_words(result, ranges)
        if len(words) < 2 or min(word['confidence'] for word in words) < threshold:
            return []
        keys = [_word_key(word['text']) for word in words]
        if signature is not None and keys != signature:
            return []
        signature = keys
        recognized[model] = words
    aligned = recognized['char']
    for index, word in enumerate(aligned):
        midpoint = _midpoint(word)
        if not any(start - .12 <= midpoint <= end + .12 for start, end in ranges):
            return []
        if any(abs(_midpoint(recognized[model][index]) - midpoint) > .20 for model in ('ctc', 'rnnt')):
            return []
    return [dict(word, text=ctc['text'], confidence=min(word['confidence'], ctc['confidence'], rnnt['confidence']),
                 needs_review=True, review_reason='quiet_speech_consensus', alternatives=[])
            for word, ctc, rnnt in zip(aligned, recognized['ctc'], recognized['rnnt'])]


def confirmed_quiet_words(samples, ranges, emit_start, emit_end, load):
    duration = len(samples) / 16000
    output = []
    decoded_seconds = 0
    window_count = 0
    windows = speech_windows(ranges, duration, padding=.30, merge_gap=.35, max_seconds=6)
    for index, (left, right) in enumerate(windows):
        lower = max(left, emit_start)
        upper = min(right, emit_end)
        if index and windows[index - 1][1] > left:
            lower = max(lower, (windows[index - 1][1] + left) / 2)
        if index + 1 < len(windows) and windows[index + 1][0] < right:
            upper = min(upper, (right + windows[index + 1][0]) / 2)
        if lower >= upper:
            continue
        begin, finish = round(left * 16000), round(right * 16000)
        left, right = begin / 16000, finish / 16000
        audio = prepare(samples[begin:finish], highpass=False)
        local = [(max(a, left) - left, min(b, right) - left) for a, b in ranges if b > left and a < right]
        window_count += 1
        decoded_seconds += len(audio) / 16000
        for word in _consensus(load, audio, local):
            if lower <= left + _midpoint(word) < upper:
                output.append(dict(word, start=left + word['start'], end=min(right, left + word['end'])))
    details = {'selected': 'quiet_consensus' if output else 'silence', 'words': len(output),
               'word_evidence': output, 'needs_review': bool(output), 'decoded_seconds': round(decoded_seconds, 3),
               'speech_windows': window_count}
    return join_words(output), details
