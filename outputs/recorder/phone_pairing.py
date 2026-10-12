import base64
import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8784
DISCOVERY_PORT = 8785
LIFETIME = 300


class PairingError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def certificate_code(der):
    return base64.b32encode(hashlib.sha256(der).digest()).decode()[:12]


def addresses():
    try:
        text = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True, timeout=3, check=True).stdout
        return sorted({v for v in re.findall(r'\binet ([0-9.]+)', text)
                       if not ipaddress.ip_address(v).is_loopback})
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


class PairingServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, context, manager):
        self.context = context
        self.manager = manager
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, PairingHandler)

    def get_request(self):
        connection, peer = super().get_request()
        connection.settimeout(5)
        try:
            return self.context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False), peer
        except Exception:
            connection.close()
            raise

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.close_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, *_):
        pass


class PairingHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply({'error': 'Открой сопряжение в приложении на телефоне'}, 405)

    def do_POST(self):
        try:
            if self.headers.get('Origin') is not None:
                raise PairingError('Запрос отклонён', 403)
            if self.headers.get('Transfer-Encoding') is not None:
                raise PairingError('Некорректный запрос')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2048:
                raise PairingError('Некорректный размер запроса', 413)
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise PairingError('Некорректный запрос')
            result = self.server.manager.remote(self.path, value, self.client_address[0])
            self.reply(result)
        except PairingError as error:
            self.reply({'error': str(error)}, error.status)
        except (ValueError, UnicodeDecodeError, TypeError):
            self.reply({'error': 'Некорректный запрос'}, 400)


class Pairing:
    def __init__(self, project, port=PORT, discovery_port=DISCOVERY_PORT):
        self.project = Path(project)
        self.config = self.project / 'work/phone-sync.json'
        self.port = port
        self.discovery_port = discovery_port
        self.lock = threading.RLock()
        self.server = None
        self.discovery = None
        self.directory = None
        self.code = ''
        self.deadline = 0
        self.pending = None
        self.denied = set()
        self.attempts = {}
        self.stop_event = threading.Event()
        self.name = socket.gethostname().removesuffix('.local')[:80] or 'Mac'

    def public(self):
        with self.lock:
            current = read(self.config)
            active = self.server is not None and time.monotonic() < self.deadline
            pending = self.pending
            return {'paired': bool(current.get('token')), 'phone_name': current.get('name', 'Телефон'),
                    'mac_name': self.name, 'active': active,
                    'code': self.code if active else '',
                    'remaining': max(0, math.ceil(self.deadline - time.monotonic())) if active else 0,
                    'addresses': self.local_addresses if active else [],
                    'pending': {key: pending[key] for key in ('id', 'name', 'verification', 'state')} if active and pending else None}

    def start(self):
        with self.lock:
            if self.server and time.monotonic() < self.deadline:
                return self.public()
            self.close()
            work = self.project / 'work'
            work.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix='phone-pairing-', dir=work))
            server = discovery = None
            try:
                key, cert = folder / 'key.pem', folder / 'cert.pem'
                settings = folder / 'openssl.cnf'
                settings.write_text('[req]\ndistinguished_name=subject\nx509_extensions=server\nprompt=no\n'
                                    '[subject]\nCN=Lecture Recorder Pairing\n'
                                    '[server]\nbasicConstraints=critical,CA:TRUE,pathlen:0\n'
                                    'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n'
                                    'extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n'
                                    'authorityKeyIdentifier=keyid:always\nsubjectAltName=DNS:lecture-recorder.local\n')
                subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                                '-keyout', str(key), '-out', str(cert), '-days', '1',
                                '-config', str(settings)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20, check=True)
                key.chmod(0o600)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(cert, key)
                code = certificate_code(ssl.PEM_cert_to_DER_cert(cert.read_text()))
                server = PairingServer(('0.0.0.0', self.port), context, self)
                discovery = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                discovery.bind(('', self.discovery_port))
                discovery.settimeout(.5)
                self.local_addresses = addresses()
                self.directory, self.server, self.discovery = folder, server, discovery
                self.code, self.deadline = code, time.monotonic() + LIFETIME
                self.pending, self.denied, self.attempts = None, set(), {}
                self.stop_event = threading.Event()
                threading.Thread(target=server.serve_forever, daemon=True, name='Phone pairing TLS').start()
                threading.Thread(target=self.discover, args=(discovery, self.stop_event), daemon=True, name='Phone pairing discovery').start()
                threading.Thread(target=self.expire, args=(self.stop_event,), daemon=True, name='Phone pairing expiry').start()
                return self.public()
            except Exception:
                if discovery:
                    discovery.close()
                if server:
                    server.server_close()
                shutil.rmtree(folder, ignore_errors=True)
                raise PairingError('Не удалось открыть сопряжение. Закрой второе окно приложения и повтори.', 503)

    def discover(self, udp, stop):
        while not stop.is_set():
            try:
                message, peer = udp.recvfrom(256)
                if not re.fullmatch(rb'LECTUREPAIR1 [a-f0-9]{32}', message):
                    continue
                with self.lock:
                    if not self.server or time.monotonic() >= self.deadline:
                        continue
                    value = {'protocol': 'LECTUREPAIR1', 'nonce': message.decode().split()[1],
                             'name': self.name, 'port': self.server.server_port}
                udp.sendto(json.dumps(value, ensure_ascii=False).encode(), peer)
            except (OSError, ValueError):
                pass

    def expire(self, stop):
        while not stop.wait(.5):
            with self.lock:
                if time.monotonic() >= self.deadline:
                    self.close()
                    return

    def close(self):
        with self.lock:
            self.stop_event.set()
            server, self.server = self.server, None
            udp, self.discovery = self.discovery, None
            folder, self.directory = self.directory, None
            self.pending = None
            self.code, self.deadline = '', 0
            if udp:
                udp.close()
            if server:
                server.shutdown()
                server.server_close()
            if folder:
                shutil.rmtree(folder, ignore_errors=True)

    def remote(self, route, value, address):
        with self.lock:
            if not self.server or time.monotonic() >= self.deadline:
                raise PairingError('Код истёк. Открой сопряжение на Mac заново.', 410)
            if route == '/pair/request':
                name, device, nonce = value.get('name'), value.get('device_id'), value.get('nonce')
                if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                        or any(ord(c) < 32 for c in name)
                        or not isinstance(device, str) or not re.fullmatch(r'[a-f0-9]{32}', device)
                        or not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce)):
                    raise PairingError('Некорректное имя телефона')
                ipaddress.ip_address(address)
                pending = self.pending
                if pending:
                    if pending['device_id'] == device and pending['nonce'] == nonce:
                        return {'request_id': pending['id'], 'verification': pending['verification']}
                    raise PairingError('Mac уже ожидает подтверждения другого телефона.', 409)
                now = time.monotonic()
                recent = [stamp for stamp in self.attempts.get(address, []) if now - stamp < 60]
                if len(recent) >= 5 or len(self.denied) >= 64:
                    raise PairingError('Слишком много запросов. Повтори через минуту.', 429)
                self.attempts[address] = recent + [now]
                pending = {'id': secrets.token_urlsafe(32), 'name': name.strip(), 'device_id': device,
                           'nonce': nonce, 'address': address, 'verification': f'{secrets.randbelow(1000000):06d}',
                           'token': secrets.token_urlsafe(32), 'state': 'waiting'}
                self.pending = pending
                return {'request_id': pending['id'], 'verification': pending['verification']}
            request_id = value.get('request_id')
            if not isinstance(request_id, str):
                raise PairingError('Запрос сопряжения не найден', 404)
            if request_id in self.denied:
                raise PairingError('Запрос отклонён на Mac.', 403)
            pending = self.pending
            if not pending or not secrets.compare_digest(request_id, pending['id']):
                raise PairingError('Запрос сопряжения не найден', 404)
            if route == '/pair/cancel':
                if pending['state'] == 'waiting':
                    self.denied.add(pending['id'])
                    self.pending = None
                return {'ok': True}
            if route == '/pair/ack':
                if pending['state'] not in ('approved', 'complete'):
                    raise PairingError('Сначала подтверди телефон на Mac.', 409)
                pending['state'] = 'complete'
                import phone_sync
                phone_sync.WAKE.set()
                return {'ok': True}
            if route == '/pair/status':
                result = {'status': pending['state'], 'mac_name': self.name}
                if pending['state'] in ('approved', 'complete'):
                    result['sync_token'] = pending['token']
                    esp = read(self.project / 'work/recorder-pairing.json')
                    result['esp'] = {key: esp[key] for key in ('ip', 'hostname', 'token', 'ble_address')
                                     if isinstance(esp.get(key), str) and esp[key]}
                return result
            raise PairingError('Не найдено', 404)

    def decide(self, request_id, accept):
        with self.lock:
            pending = self.pending
            if not self.server or time.monotonic() >= self.deadline:
                raise PairingError('Код истёк. Открой сопряжение заново.', 410)
            if not pending or pending['id'] != request_id:
                raise PairingError('Запрос уже изменился. Проверь экран телефона.', 409)
            if not accept:
                if pending['state'] != 'waiting':
                    raise PairingError('Телефон уже подтверждён. Можно удалить сопряжение.', 409)
                self.denied.add(pending['id'])
                self.pending = None
            elif pending['state'] == 'waiting':
                previous = read(self.config)
                save(self.config, {'token': pending['token'], 'name': pending['name'],
                                   'device_id': pending['device_id'], 'address': pending['address'],
                                   'paired_at': int(time.time())})
                pending['state'] = 'approved'
                import phone_sync
                if previous.get('token') and previous['token'] != pending['token']:
                    phone_sync.revoke(previous['token'])
                phone_sync.WAKE.set()
            return self.public()

    def forget(self):
        with self.lock:
            self.close()
            previous = read(self.config)
            self.config.unlink(missing_ok=True)
            import phone_sync
            if previous.get('token'):
                phone_sync.revoke(previous['token'])
            phone_sync.state.update(connected=False, message='Телефон не подключён. Добавь его в настройках Mac.')
            phone_sync.WAKE.set()
            return self.public()
