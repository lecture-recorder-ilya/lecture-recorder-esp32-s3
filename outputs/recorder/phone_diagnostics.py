import errno
import re
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError


REASONS = {
    'unpaired': 'Сначала подключи телефон в настройках Mac.',
    'waiting': 'Ожидаю первой попытки связи.',
    'searching': 'Ищу телефон по Wi-Fi, Bluetooth и USB.',
    'offline': 'Телефон недоступен. Проверь общую сеть Wi-Fi, Bluetooth или USB.',
    'connected': 'Телефон подключён.',
    'transferring': 'Идёт передача файла.',
    'done': 'Всё перенесено.',
    'space': 'На Mac мало свободного места. Освободи место и повтори перенос.',
    'authorization': 'Телефон отклонил сопряжение. Проверь подключение на обоих устройствах.',
    'integrity': 'Копия не прошла проверку целостности.',
    'conflict': 'На Mac уже есть другой файл с этим именем.',
    'text': 'Не удалось передать текст или конспект.',
    'revision': 'На телефоне уже сохранена другая или более новая редакция текста.',
    'format': 'Не удалось проверить формат полученных данных.',
    'storage': 'Не удалось прочитать или сохранить локальные данные.',
    'failed': 'Не удалось завершить обмен. Можно повторить попытку.',
}
TRANSPORTS = ('Wi-Fi', 'USB', 'Bluetooth')
FILE_NAME = re.compile(r'lecture-[0-9-]+\.wav|board-[0-9]{13}-[a-f0-9]{32}\.jpg')


def reason(error):
    if isinstance(error, HTTPError):
        if error.code in (401, 403):
            return 'authorization'
        if error.code == 409:
            return 'conflict'
        if error.code >= 500 or error.code in (408, 429):
            return 'offline'
        return 'format'
    if isinstance(error, (URLError, ConnectionError, TimeoutError, IncompleteRead)):
        return 'offline'
    detail = str(error)
    if getattr(error, 'errno', None) == errno.ENOSPC or 'достаточно места' in detail:
        return 'space'
    if 'Сопряжение с телефоном удалено' == detail:
        return 'authorization'
    if 'с этим именем' in detail or 'другое фото' in detail:
        return 'conflict'
    if 'более новая версия' in detail:
        return 'revision'
    if 'совпала' in detail or 'совпало' in detail or 'подтвердил' in detail or 'продолжение копии' in detail:
        return 'integrity'
    if isinstance(error, OSError):
        return 'storage'
    if isinstance(error, (ValueError, EOFError)):
        return 'format'
    return 'failed'


def count(value):
    return value if type(value) is int and value >= 0 else None


def public(snapshot, paired, requested):
    from phone_updates import MESSAGES
    snapshot = snapshot if isinstance(snapshot, dict) and paired else {}
    connected = snapshot.get('connected') is True
    code = snapshot.get('reason')
    if not paired:
        code = 'unpaired'
    elif not isinstance(code, str) or code not in REASONS:
        code = 'connected' if connected else 'waiting'
    transport = snapshot.get('transport')
    if transport not in TRANSPORTS:
        transport = ''
    errors = snapshot.get('issues')
    issues = [REASONS[e] for e in errors if isinstance(e, str) and e in REASONS] if isinstance(errors, list) else []
    pending = count(snapshot.get('pending')) if snapshot.get('listed') is True or connected else None
    stamp = count(snapshot.get('last_attempt'))
    message = REASONS[code]
    active = snapshot.get('active_file')
    if code == 'transferring' and isinstance(active, str) and FILE_NAME.fullmatch(active):
        message = 'Переношу ' + active
    if connected and transport:
        message += ' · ' + transport
    update = snapshot.get('update_message')
    return dict(connected=connected, transport=transport, pending=pending, failed=count(snapshot.get('failed')) or 0,
                imported=count(snapshot.get('imported')) or 0, errors=issues[:10], message=message,
                last_attempt=stamp if stamp and stamp < 4102444800 else None, reason=REASONS[code],
                update_message=update if isinstance(update, str) and update in MESSAGES.values() else '',
                retry_requested=paired and requested, can_retry=paired)
