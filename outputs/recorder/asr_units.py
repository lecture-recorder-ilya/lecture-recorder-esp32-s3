import math
import re

from asr_guard import lexical


FORMS = {word: sign for sign, words in (
    ('₽', ('рубль', 'рубля', 'рублей')),
    ('€', ('евро',)),
    ('$', ('доллар', 'доллара', 'долларов')),
    ('%', ('процент', 'процента', 'процентов')),
) for word in words}
SIGN = re.compile(r'([₽€$%])([.,!?…]*)')
NUMBER = re.compile(r'\d+(?:[.,]\d+)?')


def _marks(result):
    tokens = result.tokens or []
    times = result.timestamps or []
    scores = result.logprobs or []
    if len(tokens) != len(times) or len(tokens) != len(scores):
        return []
    marks = []
    for i, token in enumerate(tokens):
        match = SIGN.fullmatch(token.replace('▁', ' ').strip())
        if not match or not math.isfinite(scores[i]) or scores[i] < math.log(.65):
            continue
        sign, suffix = match.groups()
        if not suffix and i+1 < len(tokens) and re.fullmatch(r'[.,!?…]+', tokens[i+1]):
            suffix = tokens[i+1]
        marks.append((sign, float(times[i]), suffix))
    return marks


def restore_spoken_units(words, ctc, rnnt, character):
    heard = [(w, FORMS[key]) for w in character if w['confidence'] >= .85
             and (key := lexical(w['text'])) in FORMS]
    if not heard or not any(NUMBER.fullmatch(w['text']) for w in words):
        return words, []
    ctc_marks, rnnt_marks = _marks(ctc), _marks(rnnt)
    restored, changes = [], []
    for i, number in enumerate(words):
        restored.append(number)
        if not NUMBER.fullmatch(number['text']):
            continue
        following = words[i+1] if i+1 < len(words) else None
        if following and lexical(following['text']) in FORMS:
            continue
        next_start = following['start'] if following else math.inf
        matches = [(w, sign) for w, sign in heard if 0 <= w['start']-number['end'] <= .5
                   and w['end'] <= next_start]
        if len(matches) != 1:
            continue
        word, sign = matches[0]
        endings = []
        for marks in (ctc_marks, rnnt_marks):
            nearby = [suffix for unit, t, suffix in marks if unit == sign and abs(t-word['start']) <= .24]
            if len(nearby) == 1:
                endings.append(nearby[0])
        if len(endings) != 2:
            continue
        suffix = endings[0] if endings[0] == endings[1] else ''
        value = word['text'].rstrip('.,!?…') + suffix
        source = sign + suffix
        restored.append(dict(word, text=value, original_text=source, needs_review=True,
                             review_reason='spoken_unit_consensus'))
        changes.append({'from': source, 'to': value, 'start': word['start'], 'source': 'spoken-unit-consensus'})
    return restored, changes
