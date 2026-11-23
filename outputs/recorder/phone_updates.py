import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from android_packages import ASSETS, apk_identity, cache_folder, installed_package

WORK = Path(__file__).resolve().parents[2]/'work'
LAST = {}
MESSAGES = {
    'legacy': 'Для закрытых обновлений на телефоне нужна версия 0.5.1 или новее',
    'unknown': 'Для этого Android-приложения нет канала обновлений',
    'uncached': 'На Mac нет проверенного APK для этой версии приложения',
    'current': 'На телефоне установлена актуальная версия',
    'staged': 'APK передан телефону · установку нужно подтвердить на телефоне',
    'recording': 'Обновление телефона передам после записи',
    'rejected': 'Телефон отклонил APK. Проверь подпись и версию.',
    'retry': 'Обновление телефона повторю при следующем подключении',
}


def cached_update(work, package):
    folder = cache_folder(work, package)
    apk = folder / 'update.apk'
    meta = json.loads((folder / 'ready.json').read_text())
    if not isinstance(meta, dict) or meta.get('package', package) != package:
        raise ValueError('Некорректный канал в кэше')
    digest = meta.get('digest')
    if not isinstance(digest, str) or not re.fullmatch('sha256:[a-f0-9]{64}', digest):
        raise ValueError('Некорректная контрольная сумма')
    actual, code = apk_identity(apk)
    if actual != package:
        raise ValueError('Имя пакета в APK отличается от канала обновления')
    return apk, digest[7:], code, meta.get('tag')


def push(base, token, work=WORK):
    key = (base, token)
    if time.monotonic()-LAST.get(key, -300) < 60: return
    check_phone(base, token, work)
    LAST[key] = time.monotonic()


def check_phone(base, token, work):
    from phone_sync import request, request_file, state
    if not any((cache_folder(work, package) / 'ready.json').is_file() for package in ASSETS):
        return
    try:
        with request(base, token, '/app-update') as response: status = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            error.close()
            state['update_message'] = MESSAGES['legacy']
            return
        raise
    package = installed_package(status)
    if package is None:
        state['update_message'] = MESSAGES['unknown']
        return
    try:
        apk, expected, code, tag = cached_update(work, package)
    except (OSError, ValueError):
        state['update_message'] = MESSAGES['uncached']
        return
    installed_code = status.get('installed_code')
    if type(installed_code) is int:
        current = installed_code >= code
    else:
        current = bool(tag) and status.get('installed_tag') == tag
    if status.get('sha256') == expected or current:
        state['update_message'] = MESSAGES['current' if current else 'staged']
        return
    pending_code = status.get('pending_code')
    if type(pending_code) is int and pending_code >= code:
        state['update_message'] = MESSAGES['staged']
        return
    if status.get('analyzing'):
        state['update_message'] = 'Обновление телефона передам после разбора записи'
        return
    if status.get('recording'):
        state['update_message'] = MESSAGES['recording']
        return
    if status.get('rejected_digest') == expected:
        state['update_message'] = MESSAGES['rejected']
        return
    result = request_file(base, token, '/app-update', apk, expected_digest=expected)
    if result.get('sha256') != expected: raise ValueError('Телефон не подтвердил APK')
    state['update_message'] = MESSAGES['staged']
