import math
import re
from asr_guard import join_words, lexical
from speech_quality import clean_asr_text, usable


def phrase_rows(text, recognition, offset, start, end, first_id=0):
    words = recognition.get('word_evidence') or []
    valid = bool(words) and all(isinstance(word, dict) and isinstance(word.get('text'), str)
                               and all(type(word.get(key)) in (int, float) and math.isfinite(word[key])
                                       for key in ('start', 'end'))
                               and 0 <= word['start'] < word['end'] for word in words)
    if (not valid or lexical(text) != ''.join(lexical(word['text']) for word in words)
            or any(a['start'] > b['start'] for a, b in zip(words, words[1:]))):
        row = dict(id=first_id, start=round(start, 3), end=round(end, 3), text=text,
                   timing='audio_excerpt', needs_review=bool(recognition.get('needs_review')),
                   recognition=dict(recognition, audio_offset=offset))
        return [row] if start < end and usable(row) else []
    groups, current = [], []
    for word in words:
        if current and (word['start'] - current[-1]['end'] >= .8
                        or word['end'] - current[0]['start'] > 7 or len(current) >= 20):
            groups.append(current)
            current = []
        current.append(dict(word))
        if re.search(r'[.!?…][»"\)\]]*$', word['text']) and len(lexical(word['text'])) > 2:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    rows = []
    for group in groups:
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
    return rows
