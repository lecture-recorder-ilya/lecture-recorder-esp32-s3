def audio_window(offset, step, total, rate=16000, context=2):
    return max(0, offset - context * rate), min(total, offset + step + context * rate)


def boundary_at_pause(samples, nominal, rate=16000):
    import numpy as np

    frame = rate // 40
    radius = (rate * 2 // frame) * frame
    if nominal < radius or len(samples) - nominal < radius:
        return nominal
    window = samples[nominal - radius:nominal + radius].reshape(-1, frame)
    envelope = np.sqrt(np.var(window, axis=1, dtype=np.float64))
    quiet, voice = np.quantile(envelope, [.10, .75])
    if voice <= 1e-5 or quiet >= .65 * voice:
        return nominal
    threshold = min(.65 * voice, max(.25 * voice, 1.2 * quiet))
    edges = np.flatnonzero(np.diff(np.r_[False, envelope <= threshold, False]))
    middle = radius // frame
    lower = middle - (rate * 3 // 2) // frame
    nearby = []
    for start, end in edges.reshape(-1, 2):
        if end - start < 14:
            continue
        if start <= middle <= end:
            return nominal
        center = (start + end) // 2
        if lower <= center < middle:
            nearby.append(center)
    return nominal + (max(nearby, default=middle) - middle) * frame


def central_segment(segment, start, end):
    words = [w for w in segment.get('words', [])
             if start <= (w['start'] + w['end']) / 2 < end]
    if not words:
        return None
    left, right = max(start, words[0]['start']), min(end, words[-1]['end'])
    if left >= right:
        return None
    return dict(segment, words=words, start=left, end=right,
                text=' '.join(w['word'].strip() for w in words).strip())
