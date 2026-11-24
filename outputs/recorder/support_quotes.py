import math
import re

from homework_evidence import AFTER

NOTICE = 'Черновик: первые опорные цитаты из расшифровки. Полный конспект ещё не готов; смысл и слова нужно сверить со звуком.'
NONCLAIM = re.compile(
    r'[?]|^(?:(?:а|и|ну|так)[,\s]+)*(?:чему|чем|кто|что|как|когда|где|почему|зачем|откуда|сколько|какой|какая|какие)\b'
    r'|^(?:правда|верно|можно|нужно|надо|будет|есть)\s+ли\b'
    r'|например|допустим|представьте|вероятно|возможно|кажется|наверно|по-моему'
    r'|(?:мне|нам)\s+(?:надо|нужно)|(?:сосед|одногруппник|студент|кто-то|он|она|они)\b.{0,35}(?:сказал|говорит|спросил)|^по словам'
    r'|проверк\w* (?:звука|микрофона)|проверяем (?:звук|микрофон)|неразборчив'
    r'|^(?:здравствуйте|привет|раз[, ]+два)\b', re.I)


def add(report, limit=3):
    from ai_worker import summary_anchor
    from speech_quality import usable
    originals = report.get('segments') or []
    rows = [dict(row, id=index, needs_review=bool(row.get('needs_review') and not row.get('reviewed')))
            for index, row in enumerate(originals[:240])]
    texts = {row['id']: row for row in rows
             if all(type(row.get(key)) in (int, float) and math.isfinite(row[key]) for key in ('start', 'end'))
             and 0 <= row['start'] < row['end']}
    result = dict(report, summary=[], summary_evidence=[], overview='', homework=[], homework_review=[])
    duration = report.get('duration')
    for row in rows:
        if len(result['summary']) >= limit:
            break
        if row['id'] not in texts or row['needs_review'] or row.get('speaker_role') in ('student', 'audience') or not usable(row):
            continue
        anchor = summary_anchor(dict(quote=row['text'], segment_id=row['id']), texts)
        if not anchor or not 40 <= len(anchor['quote']) <= 900:
            continue
        quote = anchor['quote']
        if NONCLAIM.search(quote) or AFTER.search(quote.lower()):
            continue
        span = []
        for candidate in rows[anchor['segment_id']:]:
            if candidate['id'] not in texts:
                break
            span.append(candidate)
            if candidate['end'] == anchor['end'] and ' '.join(item['text'] for item in span) == quote:
                break
        if not span or span[-1]['end'] != anchor['end'] or ' '.join(item['text'] for item in span) != quote:
            continue
        if any(item['needs_review'] or item.get('speaker_role') in ('student', 'audience') or not usable(item) for item in span):
            continue
        if type(duration) in (int, float) and math.isfinite(duration) and not 0 <= anchor['start'] < anchor['end'] <= duration + .011:
            continue
        if any(anchor['start'] < item['end'] and anchor['end'] > item['start'] for item in result['summary_evidence']):
            continue
        anchor.update(segment_id=originals[anchor['segment_id']].get('id', anchor['segment_id']),
                      selection_method='support_quote_draft')
        result['summary'].append(quote)
        result['summary_evidence'].append(anchor)
    if result['summary']:
        result.update(draft=True, draft_kind='support_quotes', draft_notice=NOTICE, overview=NOTICE)
    return result
