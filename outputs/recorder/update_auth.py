import json
import ssl
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[2]


class Keychain:
    def __init__(self, project=PROJECT):
        self.helper = project/'outputs/Запись лекций.app/Contents/MacOS/UpdateCredentials'

    def run(self, action, value=None):
        try:
            result = subprocess.run([str(self.helper), action],
                                    input=json.dumps(value).encode() if value is not None else None,
                                    capture_output=True, timeout=45, check=True)
            return json.loads(result.stdout or b'{}')
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ValueError('Разреши доступ к Связке ключей macOS и повтори вход.') from None

    def read(self): return self.run('read')
    def write(self, value): self.run('write', value)
    def delete(self): self.run('delete')


def exchange(route, values):
    request = Request('https://github.com/login/'+route, data=urlencode(values).encode(),
                      headers={'Accept': 'application/json', 'User-Agent': 'LectureRecorder-Updater'})
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem') if Path('/etc/ssl/cert.pem').exists() else ssl.create_default_context()
    with urlopen(request, timeout=20, context=context) as response:
        return json.loads(response.read(32768))


class Authorization:
    def __init__(self, project=PROJECT, vault=None, send=exchange, clock=time.time):
        self.project, self.vault, self.send, self.clock = project, vault or Keychain(project), send, clock
        self.lock = threading.RLock()
        self.credentials = None
        self.pending = None
        self.message = 'Войди в GitHub для закрытых обновлений.'
        self.wake = lambda: None

    def config(self):
        try: return json.loads((self.project/'release.json').read_text()).get('updates', {})
        except (OSError, ValueError): return {}

    def public(self):
        with self.lock:
            pending = self.pending
            return dict(configured=bool(self.config().get('client_id')), authorized=bool(self.credentials),
                        pending=bool(pending), message=self.message,
                        user_code=pending['user_code'] if pending else '',
                        verification_uri='https://github.com/login/device' if pending else '',
                        expires_at=pending['expires_at'] if pending else 0,
                        installation_url=self.config().get('installation_url', ''))

    def begin(self):
        with self.lock:
            if self.pending: return self.public()
            client = self.config().get('client_id')
            if not client: raise ValueError('В этой сборке ещё не настроен закрытый канал.')
            value = self.send('device/code', {'client_id': client})
            if (not value.get('device_code') or not value.get('user_code')
                    or value.get('verification_uri') != 'https://github.com/login/device'):
                raise ValueError('GitHub не выдал код входа. Повтори позже.')
            self.pending = dict(device_code=value['device_code'], user_code=value['user_code'],
                                expires_at=self.clock()+min(int(value.get('expires_in', 900)), 900),
                                interval=max(5, int(value.get('interval', 5))), next_poll=0)
            self.message = 'Открой GitHub и введи код. Доступ нужен только для чтения обновлений.'
            return self.public()

    def cancel(self):
        with self.lock:
            self.pending = None
            self.message = 'Вход отменён. Можно получить новый код.'
            return self.public()

    def disconnect(self):
        with self.lock:
            self.vault.delete()
            self.credentials, self.pending = {}, None
            self.wake()
            self.message = 'Выход выполнен. Доступ на этом Mac удалён из Связки ключей.'
            return self.public()

    def store(self, value):
        if not isinstance(value.get('access_token'), str) or not value['access_token']:
            raise ValueError('GitHub не подтвердил вход.')
        credentials = {key: value[key] for key in ('access_token', 'refresh_token') if key in value}
        credentials['expires_at'] = self.clock()+int(value.get('expires_in', 28800))
        credentials['refresh_expires_at'] = self.clock()+int(value.get('refresh_token_expires_in', 15552000))
        self.vault.write(credentials)
        self.credentials, self.pending = credentials, None
        self.message = 'GitHub подключён · закрытые обновления включены.'
        self.wake()

    def poll(self):
        with self.lock:
            pending = self.pending
            if not pending: return
            now = self.clock()
            if now >= pending['expires_at']:
                self.pending = None
                self.message = 'Код истёк. Нажми «Войти в GitHub» ещё раз.'
                return
            if now < pending['next_poll']: return
            pending['next_poll'] = now+pending['interval']
            values = dict(client_id=self.config()['client_id'], device_code=pending['device_code'],
                          grant_type='urn:ietf:params:oauth:grant-type:device_code')
            if self.config().get('repository_id'): values['repository_id'] = self.config()['repository_id']
            try: value = self.send('oauth/access_token', values)
            except (OSError, ValueError):
                pending['next_poll'] = now+max(30, pending['interval'])
                self.message = 'Ожидаю связь с GitHub. Код остаётся действующим.'
                return
            error = value.get('error')
            if error == 'authorization_pending': return
            if error == 'slow_down':
                pending['interval'] += 5
                pending['next_poll'] = now+pending['interval']
                return
            if error:
                self.pending = None
                self.message = 'Вход не подтверждён. Получи новый код и повтори.'
                return
            self.store(value)

    def token(self):
        with self.lock:
            if self.credentials is None: self.credentials = self.vault.read()
            if not self.credentials: return None
            if self.clock()+120 < self.credentials.get('expires_at', 0):
                if not self.pending: self.message = 'GitHub подключён · закрытые обновления включены.'
                return self.credentials['access_token']
            if not self.credentials.get('refresh_token') or self.clock() >= self.credentials.get('refresh_expires_at', 0):
                self.message = 'Доступ истёк. Войди в GitHub ещё раз.'
                self.credentials = {}
                return None
            value = self.send('oauth/access_token', dict(client_id=self.config()['client_id'],
                              grant_type='refresh_token', refresh_token=self.credentials['refresh_token']))
            if value.get('error'):
                self.message = 'GitHub просит повторный вход.'
                self.credentials = {}
                return None
            self.store(value)
            return self.credentials['access_token']


AUTH = Authorization()
