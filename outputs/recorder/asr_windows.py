def audio_window(offset, step, total, rate=16000, context=2):
    return max(0, offset - context * rate), min(total, offset + step + context * rate)


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
