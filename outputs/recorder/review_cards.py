import copy
import hashlib
import json
import math
import re
import time
import uuid
import wave
from pathlib import Path

import study_store as store
from transcript_quality import report_for


def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label}: введи текст до {limit} символов')
    return value.strip()


def _token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', value):
        raise ValueError('Некорректный номер запроса')
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _path(name):
    store.audio(name)
    return store.ROOT / 'study' / (Path(name).stem + '.review-cards.json')


def _data(name):
    return store.read(_path(name), dict(version=1, cards=[], requests={}, deleted=[]))


def _sources(name):
    rows = (report_for(store.ROOT, name) or {}).get('segments') or []
    if not rows:
        return []
    try:
        limit = store.duration(name)
    except (wave.Error, EOFError):
        return []
    sources = []
    for index, row in enumerate(rows):
        start, end, quote = row.get('start'), row.get('end'), row.get('text')
        if not isinstance(quote, str) or not quote.strip():
            continue
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end)):
            continue
        if not 0 <= start < end <= limit + .011:
            continue
        source = dict(segment_id=row.get('id', index), start=start, end=end, quote=quote)
        source['key'] = _digest(source)
        source['source_status'] = 'confirmed'
        source['text_reviewed'] = row.get('reviewed') is True
        source['text_needs_review'] = bool(row.get('needs_review') and not row.get('reviewed'))
        if source['text_needs_review']:
            source['source_note'] = 'Сомнительный текст: сверь фразу со звуком.'
        elif not source['text_reviewed']:
            source['source_note'] = 'Текст не отмечен как проверенный вручную.'
        sources.append(source)
    return sources


def _public(card, sources):
    result = copy.deepcopy(card)
    original = result.get('source')
    if not original:
        return result
    same = [source for source in sources if source['key'] == original['key']]
    matching = [source for source in sources if source['quote'] == original['quote']]
    current = same[0] if len(same) == 1 else matching[0] if len(matching) == 1 else None
    if current:
        result['source'] = dict(current, original_source=original)
        if current['key'] != original['key']:
            result['source']['rebound'] = True
    else:
        result['source'] = dict(quote=original['quote'], original_source=original,
                                source_status='needs_review', source_note='Источник изменился или неоднозначен. Нужно сверить цитату.')
    return result


def list_cards(name):
    store.audio(name)
    with store.transaction():
        sources = _sources(name)
        cards = _data(name)['cards']
        return dict(file=name, cards=[_public(card, sources) for card in cards], sources=sources)


def apply(body):
    if not isinstance(body, dict):
        raise ValueError('Некорректные данные карточки')
    name = body.get('file')
    store.audio(name)
    request_id = _token(body.get('request_id'))
    action = body.get('action')
    if action == 'create':
        payload = dict(action=action, question=_text(body.get('question'), 'Вопрос', 4000),
                       answer=_text(body.get('answer'), 'Ответ', 8000), source_key=body.get('source_key'))
        if payload['source_key'] is not None and not isinstance(payload['source_key'], str):
            raise ValueError('Выбери фразу из расшифровки')
    elif action == 'review':
        payload = dict(action=action, card_id=_token(body.get('card_id')), result=body.get('result'))
        if payload['result'] not in ('remember', 'again'):
            raise ValueError('Выбери «Помню» или «Ещё раз»')
    elif action == 'delete':
        payload = dict(action=action, card_id=_token(body.get('card_id')))
    else:
        raise ValueError('Неизвестное действие с карточкой')
    signature = _digest(payload)
    with store.transaction():
        data = _data(name)
        cards = data['cards']
        requests = data['requests']
        previous = requests.get(request_id)
        if previous and previous['signature'] != signature:
            raise ValueError('Этот номер запроса уже использован с другими данными')
        sources = _sources(name)
        if previous:
            card = next((card for card in cards if card['id'] == previous['card_id']), None)
            return dict(file=name, card=_public(card, sources) if card else None, replayed=True,
                        deleted=previous['card_id'] in data['deleted'])
        now = time.time()
        if action == 'create':
            if len(cards) >= 1000:
                raise ValueError('В этой записи уже 1000 карточек')
            source = None
            if payload['source_key'] is not None:
                source = next((source for source in sources if source['key'] == payload['source_key']), None)
                if source is None:
                    raise ValueError('Расшифровка изменилась. Обнови список и выбери фразу заново')
            card = dict(id=uuid.uuid4().hex, question=payload['question'], answer=payload['answer'],
                        source=source, created_at=now, review_count=0, remembered_count=0, again_count=0)
            cards.append(card)
        elif action == 'review':
            card = next((card for card in cards if card['id'] == payload['card_id']), None)
            if card is None:
                raise ValueError('Карточка не найдена в этой записи')
            card['review_count'] += 1
            card['remembered_count' if payload['result'] == 'remember' else 'again_count'] += 1
            card.update(last_result=payload['result'], reviewed_at=now)
        else:
            ident = payload['card_id']
            card = next((card for card in cards if card['id'] == ident), None)
            if card is None and ident not in data['deleted']:
                raise ValueError('Карточка не найдена в этой записи')
            data['cards'] = [card for card in cards if card['id'] != ident]
            if ident not in data['deleted']:
                data['deleted'].append(ident)
        ident = card['id'] if card else payload['card_id']
        requests[request_id] = dict(signature=signature, card_id=ident)
        store.save(_path(name), data)
        return dict(file=name, card=_public(card, sources) if action != 'delete' else None,
                    replayed=False, deleted=action == 'delete')
