import json
import re
import time
from urllib.error import HTTPError
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]/'work'
LAST = {}


def push(base, token, work=WORK):
    from phone_sync import request, request_file, digest, state
    key = (base, token)
    if time.monotonic()-LAST.get(key, -300) < 60: return
    LAST[key] = time.monotonic()
    folder = work/'updates/android'
    try:
        meta = json.loads((folder/'ready.json').read_text())
        apk = folder/'update.apk'
        expected = meta['digest'].removeprefix('sha256:')
        if not re.fullmatch('[a-f0-9]{64}', expected) or digest(apk) != expected: return
    except (OSError, ValueError, KeyError): return
    try:
        with request(base, token, '/app-update') as response: status = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            state['update_message'] = 'Для закрытых обновлений на телефоне нужна версия 0.5.1 или новее'
            return
        raise
    if status.get('sha256') == expected or status.get('installed_tag') == meta['tag']:
        state['update_message'] = status.get('message', 'Обновление телефона проверено')
        return
    if status.get('recording'):
        state['update_message'] = 'Обновление телефона передам после записи'
        return
    if status.get('rejected_digest') == expected:
        state['update_message'] = 'Телефон отклонил APK: '+status.get('message', 'Проверь подпись и версию')[:160]
        return
    result = request_file(base, token, '/app-update', apk)
    if result.get('sha256') != expected: raise ValueError('Телефон не подтвердил APK')
    state['update_message'] = 'APK передан телефону · установку нужно подтвердить на телефоне'
