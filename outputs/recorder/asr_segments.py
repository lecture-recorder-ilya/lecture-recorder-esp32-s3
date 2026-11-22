import math
import re
from asr_guard import MIN_UNRECOGNIZED_VOICE, join_words, lexical
from speech_quality import clean_asr_text, repetition, usable

SENTENCE_END = re.compile(r'[.!?…][»"\)\]]*$')
CLAUSE_END = re.compile(r'[,;:—][»"\)\]]*$')
BINDING_WORDS = frozenset(
    'не ни в во на по к ко с со без для до от из у о об при про через и а но или либо'.split()
)


def _split_passage(words):
    first = 0
    while first < len(words):
        limit = first + 1
        while (limit < len(words) and limit - first < 20
               and words[limit]['end'] - words[first]['start'] <= 7):
            limit += 1
        end = limit
        if limit < len(words):
            minimum = first + max(3, (limit - first) // 2)
            candidates = []
            for cut in range(minimum, limit + 1):
                before, after = words[cut - 1], words[cut]
                if lexical(before['text']) in BINDING_WORDS:
                    continue
                clause = bool(CLAUSE_END.search(before['text']))
                if clause or after['start'] - before['end'] >= .35:
                    candidates.append((clause, cut))
            if candidates:
                end = max(candidates)[1]
            else:
                while end > minimum and lexical(words[end - 1]['text']) in BINDING_WORDS:
                    end -= 1
        yield words[first:end]
        first = end


def _split_phrases(words):
    first = 0
    for index, word in enumerate(words):
        sentence = SENTENCE_END.search(word['text']) and len(lexical(word['text'])) > 2
        pause = index + 1 < len(words) and words[index + 1]['start'] - word['end'] >= .8
        if sentence or pause:
            yield from _split_passage(words[first:index + 1])
            first = index + 1
    yield from _split_passage(words[first:])


def _attach_unrecognized_audio(rows, gaps, offset, start, end):
    if not rows:
        return rows
    for left, right in gaps:
        gap_start = round(max(start, offset + left), 3)
        gap_end = round(min(end, offset + right), 3)
        if gap_end - gap_start + 1e-9 < MIN_UNRECOGNIZED_VOICE:
            continue
        row = min(rows, key=lambda item: max(0, item['start'] - gap_end, gap_start - item['end']))
        row['recognition'].setdefault('unrecognized_audio', []).append(dict(start=gap_start, end=gap_end))
    return rows


def phrase_rows(text, recognition, offset, start, end, first_id=0):
    gaps = list(recognition.get('unrecognized_voice', []))
    if gaps:
        recognition = dict(recognition)
        recognition.pop('unrecognized_voice')
    words = recognition.get('word_evidence') or []
    valid = bool(words) and all(isinstance(word, dict) and isinstance(word.get('text'), str)
                               and all(type(word.get(key)) in (int, float) and math.isfinite(word[key])
                                       for key in ('start', 'end'))
                               and 0 <= word['start'] < word['end'] for word in words)
    aligned = valid and lexical(text) == ''.join(lexical(word['text']) for word in words)
    if valid and not aligned:
        aligned = lexical(text) == lexical(clean_asr_text(join_words(words)))
    if not aligned or any(a['start'] > b['start'] for a, b in zip(words, words[1:])):
        row = dict(id=first_id, start=round(start, 3), end=round(end, 3), text=text,
                   timing='audio_excerpt', needs_review=bool(recognition.get('needs_review')),
                   recognition=dict(recognition, audio_offset=offset))
        rows = [row] if start < end and usable(row) else []
        return _attach_unrecognized_audio(rows, gaps, offset, start, end)
    rows = []
    for group in _split_phrases(words):
        left, right = max(start, offset+group[0]['start']), min(end, offset+max(w['end'] for w in group))
        if left >= right:
            continue
        value = clean_asr_text(join_words(group))
        details = dict(recognition, word_evidence=group, words=len(group), audio_offset=offset)
        details.pop('original_text', None)
        details['refinements'] = [change for change in recognition.get('refinements', [])
                                  if group[0]['start'] <= change.get('start', -1) <= group[-1]['start']]
        details['uncertain_words'] = [w['text'] for w in group if w.get('confidence', 1) < .7 or w.get('needs_review')]
        details['needs_review'] = bool(details['refinements'] or details['uncertain_words']
                                      or any(w.get('needs_review') for w in group)
                                      or recognition.get('ctc_confidence', 1) < .85)
        original = join_words([dict(w, text=w.get('original_text', w['text'])) for w in group])
        if original != value:
            details['original_text'] = original
        timed = [dict(word=w['text'], start=round(max(left, offset+w['start']), 3),
                      end=round(min(right, offset+w['end']), 3), confidence=w.get('confidence')) for w in group
                 if max(left, offset+w['start']) < min(right, offset+w['end'])]
        row = dict(id=first_id+len(rows), start=round(left, 3), end=round(right, 3), text=value,
                   words=timed, timing='asr_words', needs_review=details['needs_review'], recognition=details)
        if usable(row):
            rows.append(row)
        elif repetition(value):
            gaps.append((left - offset, right - offset))
    return _attach_unrecognized_audio(rows, gaps, offset, start, end)
