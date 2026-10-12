"""Auditable final cleanup. Never changes source audio or ASR checkpoints."""
import re
from speech_quality import clean_asr_text, usable
from transcript_corrector import proofread


def review(segments, subject, fetch=None):
    cleaned, edits, removed = [], [], []
    for segment in segments:
        original = segment.get('text', '')
        text = clean_asr_text(original)
        # Only long, immediately repeated phrases: retain the first occurrence.
        pattern = r'\b((?:\w+[ ,]+){2,11}\w+)(?:[ ,]+\1){3,}\b'
        text = re.sub(pattern, r'\1', text, flags=re.I)
        candidate = dict(segment, text=text)
        if not usable(candidate):
            removed.append(dict(segment, reason='Недостоверный повтор или служебный текст'))
            continue
        if cleaned and text == cleaned[-1]['text'] and segment['start'] < cleaned[-1]['end']:
            removed.append(dict(segment, reason='Перекрывающийся дубликат'))
            continue
        if text != original:
            candidate['original_text'] = original
            edits.append({'segment_id':segment['id'], 'original':original, 'text':text, 'kind':'cleanup'})
        cleaned.append(candidate)
    checked = {'corrections':[], 'status':'unsupported'}
    # Review every segment; reference() caches public-topic lookups across the lecture.
    for segment in cleaned:
        item = proofread({'segments':[segment]}, subject, **({'fetch':fetch} if fetch else {}))
        checked['corrections'].extend(item['corrections'])
        if checked['status'] != 'partial':
            checked['status'] = item['status']
    corrections = {item['segment_id']:item for item in checked['corrections']}
    for segment in cleaned:
        correction = corrections.get(segment['id'])
        if correction:
            segment.setdefault('original_text', segment['text'])
            segment['text'] = correction['text']
            segment['source_correction'] = correction
    return cleaned, {'status':'reviewed', 'source_check':checked['status'],
                     'checked_segments':len(segments), 'cleanup':edits,
                     'corrections':checked['corrections'], 'removed':removed}
