from asr_guard import lexical, prepare, supported_words
from speech_gate import BRIEF_CONTEXT


def confirmed_brief_words(samples, intervals, emit_start, emit_end, load):
    import numpy as np

    duration = len(samples) / 16000
    words = []
    windows = frames = 0
    for i, (left, right) in enumerate(intervals):
        lower = max(emit_start, left - .20, 0)
        upper = min(emit_end, right + .12, duration)
        if i:
            lower = max(lower, (intervals[i - 1][1] + left) / 2)
        if i + 1 < len(intervals):
            upper = min(upper, (right + intervals[i + 1][0]) / 2)
        if lower >= upper:
            continue
        begin = max(0, round((left - BRIEF_CONTEXT) * 16000))
        finish = min(len(samples), round((right + BRIEF_CONTEXT) * 16000))
        padding = 4000
        origin = (begin - padding) / 16000
        audio = prepare(np.pad(samples[begin:finish], (padding, padding)), highpass=False)
        windows += 1
        frames += len(audio)
        core = [(left - origin, right - origin)]
        word = _confirmed_word(load, audio, core)
        if word:
            start, end = word['start'] + origin, word['end'] + origin
            if lower <= (start + end) / 2 < upper:
                words.append(dict(word, start=max(0, start), end=min(duration, end)))
    return words, windows, frames / 16000


def _confirmed_word(load, audio, core):
    import numpy as np

    def recognize(kind, threshold, prefix_frames=0):
        shift = prefix_frames / 16000
        sample = np.pad(audio, (prefix_frames, 0)) if prefix_frames else audio
        result = load(kind).recognize(sample, sample_rate=16000)
        words = supported_words(result, [(a + shift, b + shift) for a, b in core])
        if len(words) == 1 and words[0]['confidence'] >= threshold:
            word = words[0]
            return dict(word, start=word['start'] - shift, end=word['end'] - shift)

    primary = recognize('rnnt', .65)
    if not primary:
        return None
    aligned = recognize('char', .95)
    if not aligned:
        return None
    key = lexical(aligned['text'])

    def agrees(candidate):
        return candidate and lexical(candidate['text']) == key and abs(candidate['start'] - aligned['start']) <= .16

    if not agrees(primary):
        return None
    if primary['confidence'] < .80 and not agrees(recognize('rnnt', .80, prefix_frames=2560)):
        return None
    if len(key) < 3 and not agrees(recognize('ctc', .80)):
        return None
    return dict(text=primary['text'], start=aligned['start'], end=aligned['end'],
                confidence=primary['confidence'], needs_review=True, review_reason='brief_speech_consensus')
