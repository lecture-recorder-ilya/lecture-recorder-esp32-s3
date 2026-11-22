import re
from functools import lru_cache
from asr_guard import lexical
from context_review import distance, protected


@lru_cache(maxsize=1024)
def term_protected(word):
    if protected(word):
        return True
    try:
        from context_review import morphology
        return any(p.tag.POS == 'NUMR' or 'Anum' in p.tag for p in morphology().parse(lexical(word)))
    except ImportError:
        return False


@lru_cache(maxsize=512)
def forms(word):
    result = {lexical(word)}
    try:
        from context_review import morphology
        analyzer = morphology()
        if analyzer.word_is_known(word):
            result.update(lexical(form.word) for form in analyzer.parse(word)[0].lexeme)
    except ImportError:
        pass
    return tuple(value for value in result if len(value) >= 4 and not term_protected(value))


def negation_pair(first, second):
    return any(first == prefix+second or second == prefix+first for prefix in ('не', 'без', 'бес'))


def term_words(terms):
    return {form: word for term in terms or [] if isinstance(term, str)
            for word in re.findall(r'[^\W_]+', term) if len(lexical(word)) >= 4 and not term_protected(word)
            for form in forms(word)}


def apply_terms(primary, alternatives, terms):
    hints = term_words(terms)
    output, changes = [dict(word) for word in primary], []
    if not hints:
        return output, changes
    for i, word in enumerate(primary):
        before = lexical(word['text'])
        if word['confidence'] >= .9 or len(before) < 4 or term_protected(word['text']) or before in hints:
            continue
        if before not in hints and any(0 < distance(before, hint) <= 2
                                       and distance(before, hint)/max(len(before), len(hint)) <= .34 for hint in hints):
            output[i]['needs_review'] = True
            output[i]['review_reason'] = 'term_mismatch'
        options = {}
        for source, words in alternatives:
            for j, other in enumerate(words):
                after = lexical(other['text'])
                if (abs(other['start'] - word['start']) > .35 or other['confidence'] < .65
                        or after not in hints or term_protected(other['text']) or after == before):
                    continue
                if negation_pair(before, after):
                    output[i]['needs_review'] = True
                    output[i]['review_reason'] = 'term_negation_mismatch'
                    continue
                delta = distance(before, after)
                if delta > 2 or delta / max(len(before), len(after)) > .34:
                    continue
                anchored = any(0 <= i+d < len(primary) and 0 <= j+d < len(words)
                               and lexical(primary[i+d]['text']) == lexical(words[j+d]['text'])
                               and abs(primary[i+d]['start'] - words[j+d]['start']) <= .35
                               for d in (-1, 1))
                if anchored:
                    options.setdefault(after, (other, source))
        if len(options) != 1:
            continue
        after, (other, source) = next(iter(options.items()))
        text = re.sub(r'[\W_]+$', '', other['text'])
        suffix = re.search(r'[\W_]+$', word['text'])
        text += suffix.group() if suffix else ''
        output[i]['text'] = text
        output[i].setdefault('original_text', word['text'])
        changes.append(dict(start=word['start'], source='user-term-acoustic-pass',
                            acoustic_source=source, term=hints[after], **{'from': word['text'], 'to': text}))
    return output, changes
