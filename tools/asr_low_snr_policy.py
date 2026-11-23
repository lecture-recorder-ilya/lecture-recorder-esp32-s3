from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
import re

from asr_guard import lexical
from context_review import protected
from evaluate_asr import numeric_token

CONFIDENCE_MARGIN = .04
MAX_GAP_WORDS = 2
MAX_GAP_SECONDS = 1.2


def critical(text):
    return protected(text) or numeric_token(lexical(text)) or lexical(text) in {
        'ста', 'стам', 'стами', 'стах', 'полтора', 'полторы', 'полутора'
    } or bool(re.search(r'[+−=<>×÷/]', text)) or bool(re.match(
        r'^(?:нол|нул|один|одн|дв[аеу]|три|тр[её]х|четыр|пят|шест|сем|'
        r'вос[ье]м|девят|десят|сот|тысяч|милли|млн|млрд)', lexical(text)))


def protected_counts(words):
    return Counter(lexical(w['text']) for w in words if critical(w['text']))


def gap_windows(words, core, duration):
    if len(words) < 3:
        return []
    candidates = []
    for left, right in zip(words, words[1:]):
        first, last = left['end'], right['start']
        gap = last-first
        if not .35 <= gap <= 2.0:
            continue
        support = sum(max(0, min(last, b)-max(first, a)) for a, b in core)
        if support < max(.16, gap*.3):
            continue
        candidates.append((gap, max(0, left['start']-.65), min(duration, right['end']+.65)))
    return [(left, right) for _, left, right in sorted(candidates, reverse=True)[:2]]


def choose_audio(clean, raw, *, margin=CONFIDENCE_MARGIN):
    first, second = clean.get('word_evidence', []), raw.get('word_evidence', [])
    if len(first) < 3 or len(second) < max(3, .9 * len(first)):
        return deepcopy(clean), 'clean'
    if raw.get('ctc_confidence', 0) < clean.get('ctc_confidence', 0) + margin:
        return deepcopy(clean), 'clean'
    if protected_counts(first) != protected_counts(second):
        return deepcopy(clean), 'clean'
    a, b = [lexical(w['text']) for w in first], [lexical(w['text']) for w in second]
    alignment = SequenceMatcher(None, a, b, autojunk=False)
    for kind, i, end, j, until in alignment.get_opcodes():
        if kind != 'equal' and any(critical(w['text']) for w in first[i:end]+second[j:until]):
            return deepcopy(clean), 'clean'
    matched = sum(block.size for block in alignment.get_matching_blocks())
    if matched < .65 * max(len(a), len(b)):
        return deepcopy(clean), 'clean'
    chosen = deepcopy(raw)
    chosen['original_text'] = ' '.join(w['text'] for w in first)
    chosen['needs_review'] = True
    for word in chosen['word_evidence']:
        word.update(needs_review=True, review_reason='raw_audio_choice')
    return chosen, 'raw'


def proposals(primary, other, *, word_confidence=.75, mean_confidence=.85):
    a, b = [lexical(w['text']) for w in primary], [lexical(w['text']) for w in other]
    found = {}
    for kind, i, end, j, until in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if kind != 'insert' or i == 0 or i == len(a) or not 1 <= until-j <= MAX_GAP_WORDS:
            continue
        if j == 0 or until == len(b) or a[i-1] != b[j-1] or a[i] != b[until]:
            continue
        left, right = primary[i-1], primary[i]
        if abs(left['start']-other[j-1]['start']) > .28 or abs(right['start']-other[until]['start']) > .28:
            continue
        words = other[j:until]
        if any(not lexical(w['text']) or critical(w['text']) or w['confidence'] < word_confidence for w in words):
            continue
        if sum(w['confidence'] for w in words)/len(words) < mean_confidence:
            continue
        if words[0]['start'] < left['end']-.04 or words[-1]['end'] > right['start']+.08:
            continue
        if not 0 < words[-1]['end']-words[0]['start'] <= MAX_GAP_SECONDS:
            continue
        if any(x['end'] > y['start']+.04 for x, y in zip(words, words[1:])):
            continue
        found[(i, tuple(lexical(w['text']) for w in words))] = words
    return found


def recover_gaps(clean, raw_trace, *, word_confidence=.75, mean_confidence=.85):
    primary = clean.get('word_evidence', [])
    if len(primary) < 3:
        return deepcopy(clean), []
    insertions = {}
    for trace in raw_trace:
        if trace['group'] != 1:
            continue
        ctc = proposals(primary, trace['ctc'], word_confidence=word_confidence, mean_confidence=mean_confidence)
        rnnt = proposals(primary, trace['rnnt'], word_confidence=word_confidence, mean_confidence=mean_confidence)
        for key in ctc.keys() & rnnt.keys():
            a, b = ctc[key], rnnt[key]
            if any(abs(x['start']-y['start']) > .24 or abs(x['end']-y['end']) > .24 for x, y in zip(a, b)):
                continue
            if key[0] in insertions:
                insertions[key[0]] = None
            else:
                insertions[key[0]] = a
    output, added = [], []
    for index, original in enumerate(primary):
        for word in insertions.get(index) or []:
            item = dict(word, needs_review=True, review_reason='two_decoder_gap', recovery_sources=['raw_ctc', 'raw_rnnt'])
            output.append(item)
            added.append(item)
        output.append(deepcopy(original))
    result = deepcopy(clean)
    if added:
        result.update(word_evidence=output, words=len(output), needs_review=True,
                      original_text=' '.join(w['text'] for w in primary))
    return result, added
