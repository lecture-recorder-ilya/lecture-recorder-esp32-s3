import hashlib
import json
import math
import re
from pathlib import Path


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fingerprint(segment):
    payload = [segment.get(k) for k in ('id', 'start', 'end', 'text', 'original_text')]
    quality = segment.get('quality')
    unrecognized = quality.get('unrecognized_audio') if isinstance(quality, dict) else None
    if unrecognized:
        payload.append(unrecognized)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def assess(segment):
    reasons = []
    recognition = segment.get('recognition') if isinstance(segment.get('recognition'), dict) else {}
    context = segment.get('context_review') if isinstance(segment.get('context_review'), dict) else {}
    if segment.get('needs_review'):
        reasons.append('Распознавание требует проверки по записи')
    evidence = recognition.get('word_evidence')
    if isinstance(evidence, list) and any(
            isinstance(word, dict) and isinstance(word.get('text'), str)
            and re.search(r'[^\W\d_][.,!?;:]{2,}[^\W\d_]', word['text']) for word in evidence):
        reasons.append('В распознавании склеены части слов')
    confidence = recognition.get('ctc_confidence')
    if number(confidence) and confidence < .85:
        reasons.append('Модель неуверенно различила слова')
    if recognition.get('uncertain') or recognition.get('uncertain_words'):
        reasons.append('Варианты распознавания расходятся')
    if number(segment.get('avg_logprob')) and segment['avg_logprob'] < -.6:
        reasons.append('Слабый сигнал распознавания')
    if number(segment.get('no_speech_prob')) and segment['no_speech_prob'] > .35:
        reasons.append('Речь может быть перекрыта шумом')
    weak = [w for w in segment.get('words', []) if isinstance(w, dict)
            and number(w.get('probability')) and w['probability'] < .65]
    if weak:
        reasons.append('Есть неуверенно распознанные слова')
    if context.get('needs_review') or context.get('uncertain'):
        reasons.append('Контекст не подтвердил формулировку')
    if context.get('edits'):
        reasons.append('Фраза уточнена по контексту')
    reasons = list(dict.fromkeys(reasons))
    known = bool(recognition or 'avg_logprob' in segment or segment.get('words') or 'needs_review' in segment)
    return {'needs_review': bool(reasons), 'reasons': reasons,
            'assessment': 'review' if reasons else 'available' if known else 'unavailable'}


def annotate(report, decisions=None):
    decisions = decisions or {}
    result = dict(report)
    rows = []
    if report.get('segments') is not None and not isinstance(report['segments'], list):
        raise ValueError('Некорректные строки расшифровки')
    source_rows = list(report.get('segments') or [])
    seen = {(row.get('id'), row.get('start'), row.get('text')) for row in source_rows if isinstance(row, dict)}
    for row in report.get('excluded_asides') or []:
        if isinstance(row, dict) and (row.get('id'), row.get('start'), row.get('text')) not in seen:
            source_rows.append(row)
    for index, value in enumerate(source_rows):
        if not isinstance(value, dict) or not isinstance(value.get('text'), str):
            continue
        untimed = 'start' not in value and 'end' not in value
        if not untimed and (not number(value.get('start')) or not number(value.get('end')) or value['start'] < 0 or value['end'] <= value['start']):
            continue
        row = dict(value)
        if untimed:
            row['timing'] = 'unavailable'
        row.setdefault('id', index)
        context = row.get('context_review') if isinstance(row.get('context_review'), dict) else {}
        recognition = row.get('recognition') if isinstance(row.get('recognition'), dict) else {}
        original = context.get('original_text') or recognition.get('original_text')
        if original and original != row['text']:
            row.setdefault('original_text', original)
        row['quality'] = assess(row)
        raw_audio = recognition.get('unrecognized_audio')
        available = report.get('duration')
        if isinstance(raw_audio, list):
            unrecognized = [
                {'start': span['start'], 'end': span['end']} for span in raw_audio
                if isinstance(span, dict) and number(span.get('start')) and number(span.get('end'))
                and 0 <= span['start'] < span['end']
                and (not number(available) or span['end'] <= available + .011)
            ]
            if unrecognized:
                row['quality'].update(unrecognized_audio=unrecognized, needs_review=True, assessment='review')
                row['quality']['reasons'].append('Рядом возможна речь, которой нет в тексте')
        row['needs_review'] = row['quality']['needs_review']
        row['review_key'] = fingerprint(row)
        row['reviewed'] = decisions.get(row['review_key'], {}).get('reviewed') is True
        rows.append(row)
    result['segments'] = sorted(rows, key=lambda row: (row.get('start', float('inf')), row.get('end', float('inf'))))
    result['transcript'] = '\n'.join(f"[{time_label(row)}] {row['text']}" for row in result['segments'])
    result['quality'] = {
        'total': len(rows),
        'uncertain': sum(row['needs_review'] for row in rows),
        'pending': sum(row['needs_review'] and not row['reviewed'] for row in rows),
        'reviewed': sum(row['reviewed'] for row in rows),
        'unassessed': sum(row['quality']['assessment'] == 'unavailable' for row in rows),
    }
    return result


def report_for(root, name):
    stem = Path(name).stem
    final = root / 'analysis' / (stem + '.json')
    drafts = [root / 'analysis' / (stem + suffix) for suffix in ('.live.json', '.transcript.json')]
    drafts = sorted(drafts, key=lambda path: path.stat().st_mtime_ns if path.exists() else 0, reverse=True)
    paths = [final, *drafts]
    for path in paths:
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict):
            continue
        if path.name.endswith('.transcript.json'):
            report = dict(report, draft=True, audio=name, overview='', summary=[])
        elif path.name.endswith('.live.json'):
            report = dict(report, draft=True)
        from summary_sources import reconcile
        from formula_evidence import finalize
        try:
            decisions=json.loads((root/'study'/(stem+'.notes.json')).read_text()).get('transcript_review',{})
        except (OSError,ValueError,TypeError):
            decisions={}
        report=annotate(report,decisions)
        if path!=final:
            from support_quotes import add
            report=add(report)
        return reconcile(finalize(report))
    return None


def timestamp(seconds):
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'


def time_label(row):
    return timestamp(row['start']) if number(row.get('start')) else 'Без таймкода'


def plain_text(report):
    lines = [report.get('topic') or report.get('subject') or 'Расшифровка занятия', '']
    for row in report.get('segments') or []:
        label = ' · Проверено по записи' if row.get('reviewed') else ' · Проверь по записи' if row.get('needs_review') else ''
        lines.extend([f"[{time_label(row)} - {timestamp(row['end']) if 'end' in row else '—'}]{label}", row['text'], ''])
    return '\n'.join(lines)


def markdown(report):
    from summary_sources import reconcile
    from summary_export import source_lines,timecode
    from formula_evidence import finalize
    report=reconcile(finalize(report))
    lines = ['# ' + (report.get('topic') or report.get('subject') or 'Конспект занятия'), '']
    if report.get('teacher'):
        lines.extend(['Преподаватель: ' + report['teacher'], ''])
    lines.extend(['## Главное', '', report.get('overview') or '', '', '## Ключевые мысли', ''])
    for index,point in enumerate(report.get('summary') or []):
        lines.append('- '+point)
        source=(report.get('summary_evidence') or [])[index]
        lines.extend('  '+text for text in source_lines(source))
    for title, field in [('Темы по времени', 'sections'), ('Акценты преподавателя', 'highlights'), ('Задания из записи', 'homework')]:
        if report.get(field):
            lines.extend(['', '## ' + title, ''])
            for item in report[field]:
                prefix='['+timecode(item['start'])+'] ' if field=='sections' and number(item.get('start')) else ''
                lines.append('- '+prefix + (item.get('title') or item.get('point') or item.get('task') or ''))
                if item.get('quote'):
                    lines.extend('  '+text for text in source_lines(item))
    if report.get('formulas'):
        lines.extend(['', '## Формулы из записи', ''])
        for item in report['formulas']:
            lines.extend(['$$', item.get('latex', ''), '$$', item.get('explanation', ''), ''])
            lines.extend(source_lines(item))
    for field,title in [('formula_review','Формулы для сверки'),('homework_review','Реплики без подтверждённой выдачи ДЗ')]:
        if report.get(field):
            lines.extend(['','## '+title,''])
            for item in report[field]:
                lines.append(item.get('review_note','Нужно сверить.'))
                lines.extend(source_lines(item))
    if report.get('moments'):
        from summary_sources import bind
        lines.extend(['','## Даты и понятия',''])
        for item in report['moments']:
            lines.append('- '+(item.get('date') or item.get('title',''))+' — '+item.get('description',''))
            lines.extend(source_lines(bind(item,report.get('segments',[]))))
    if report.get('warnings'):
        lines.extend(['','## Примечания','',*['- '+str(v) for v in report['warnings']]])
    lines.extend(['', '## Места для проверки', ''])
    uncertain = [row for row in report.get('segments') or [] if row.get('needs_review') and not row.get('reviewed')]
    lines.extend('- [' + time_label(row) + '] ' + row['text'] for row in uncertain)
    if not uncertain:
        lines.append('Непроверенных отметок нет. Это не гарантирует точность остальных фраз.')
    lines.extend(['', '## Полная расшифровка', '', plain_text(report), ''])
    return '\n'.join(lines)
