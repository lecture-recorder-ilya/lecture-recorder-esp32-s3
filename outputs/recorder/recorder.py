import array
import glob
import json
import math
import os
import queue
import shutil
import socket
import threading
import time
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import serial
from serial.tools import list_ports
import ai_service
import lesson_schedule

ROOT = Path(__file__).resolve().parent
FILES = ROOT / 'recordings'
FILES.mkdir(exist_ok=True)
CONFIG = ROOT.parent.parent / 'work' / 'recorder-pairing.json'
settings = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
lock = threading.Lock()
state = dict(recording=False, busy=False, seconds=0, level=0, error='', file='', samples=0)
connection = None
worker = None
stop_recording = threading.Event()


class NetworkStream:
    def __init__(self):
        try:
            self.socket = socket.create_connection((settings['ip'], 8766), timeout=3)
        except OSError:
            if not settings.get('hostname'):
                raise
            self.socket = socket.create_connection((settings['hostname'], 8766), timeout=3)
        self.socket.settimeout(.2)
    def read(self, count):
        try:
            data = self.socket.recv(count)
        except socket.timeout:
            return b''
        if not data:
            raise RuntimeError('Связь с ESP прервалась. Полученная часть записи сохранена.')
        return data
    def readline(self):
        data = bytearray()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            byte = self.read(1)
            data.extend(byte)
            if byte == b'\n':
                return bytes(data)
        return bytes(data)
    def write(self, data):
        self.socket.sendall(data)
    def close(self):
        self.socket.close()


def usb_ports():
    # A Samsung connected for import also exposes a modem serial port.
    return sorted(p.device for p in list_ports.comports()
                  if p.vid in (0x303A, 0x1A86, 0x10C4, 0x0403, 0x067B)
                  and p.device.startswith('/dev/cu.'))


def usb():
    ports = usb_ports()
    if len(ports) != 1:
        raise RuntimeError('Подключи одну ESP по USB. Найдено портов: ' + str(len(ports)))
    s = serial.Serial(ports[0], 921600, timeout=.2, write_timeout=2)
    s.dtr = False
    s.rts = False
    time.sleep(.5)
    s.reset_input_buffer()
    return s


def pair(return_only=False):
    global settings
    with usb() as s:
        s.write(b'p')
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            line = s.readline()
            if line.startswith(b'PAIR '):
                ssid, password, token, ip = line[5:].decode().strip().split('\t')
                if return_only:
                    return dict(ssid=ssid, password=password, token=token, ip=ip)
                settings = dict(ssid=ssid, password=password, token=token, ip=ip)
                CONFIG.parent.mkdir(exist_ok=True)
                CONFIG.write_text(json.dumps(settings))
                CONFIG.chmod(0o600)
                return
    raise RuntimeError('Нет ответа для настройки Wi-Fi. Проверь прошивку и USB.')


def check_wifi():
    if not settings:
        raise RuntimeError('Сначала нажми «Подготовить Wi-Fi» при подключённом USB.')
    stream = NetworkStream()
    try:
        stream.write(('PING ' + settings['token'] + '\n').encode())
        response = stream.readline().decode().strip()
        if not response.startswith('READY ') or 'mic=1' not in response:
            raise RuntimeError('Микрофон ESP не готов.')
        return response
    finally:
        stream.close()


def setup_hotspot(body):
    global settings
    ssid = body.get('ssid', '')
    password = body.get('password', '')
    if not isinstance(ssid, str) or not isinstance(password, str):
        raise RuntimeError('Проверь название сети и пароль.')
    if not 1 <= len(ssid.encode()) <= 32 or '\0' in ssid or '\0' in password:
        raise RuntimeError('Название сети должно занимать от 1 до 32 байт.')
    if password and not 8 <= len(password.encode()) <= 63:
        raise RuntimeError('Пароль должен занимать от 8 до 63 байт.')
    paired = pair(return_only=True)
    with usb() as s:
        command = 'w' + ssid.encode().hex() + '\t' + password.encode().hex() + '\n'
        s.write(command.encode())
        deadline = time.monotonic() + 32
        while time.monotonic() < deadline:
            line = s.readline()
            if line.startswith(b'WIFI_ERROR '):
                raise RuntimeError('ESP не подключилась. Проверь пароль, включённую точку доступа и диапазон 2,4 ГГц.')
            if line.startswith(b'WIFI_READY '):
                ip, hostname = line[11:].decode().strip().split('\t')
                settings = dict(paired, ip=ip, hostname=hostname, ssid=ssid, mode='hotspot')
                settings.pop('password', None)
                CONFIG.write_text(json.dumps(settings))
                CONFIG.chmod(0o600)
                return
    raise RuntimeError('Нет ответа от ESP. Проверь USB и повтори подключение.')


def exact(s, length):
    data = bytearray()
    deadline = time.monotonic() + 3
    while len(data) < length and time.monotonic() < deadline:
        if stop_recording.is_set():
            raise InterruptedError('Запись остановлена.')
        data.extend(s.read(length - len(data)))
    if len(data) != length:
        raise RuntimeError('Плата перестала передавать звук. Проверь питание и соединение.')
    return data


def open_recording_stream(transport):
    # DNS resolution may outlast socket timeouts; keep Stop responsive.
    result = queue.Queue()
    cancelled = threading.Event()
    def connect():
        try:
            stream = NetworkStream() if transport == 'wifi' else usb()
            if cancelled.is_set():
                stream.close()
            else:
                result.put((stream, None))
        except Exception as exc:
            result.put((None, exc))
    threading.Thread(target=connect, daemon=True).start()
    deadline = time.monotonic() + 10
    while not stop_recording.is_set() and time.monotonic() < deadline:
        try:
            stream, error = result.get(timeout=.1)
            if error:
                raise error
            return stream
        except queue.Empty:
            pass
    cancelled.set()
    try:
        stream, _ = result.get_nowait()
        if stream:
            stream.close()
    except queue.Empty:
        pass
    if stop_recording.is_set():
        raise InterruptedError('Запись остановлена.')
    raise TimeoutError('ESP пока недоступна.')


def capture(transport):
    global connection
    stream = None
    output = None
    raw = None
    last_checkpoint = 0
    count = 0
    gaps = []
    gap_start = None
    filename = ''
    last_audio = None

    def close_stream():
        nonlocal stream
        global connection
        with lock:
            connection = None
        if stream:
            try:
                stream.write(b'x')
            except Exception:
                pass
            stream.close()
            stream = None

    def finish_gap():
        nonlocal gap_start, count
        if gap_start is None:
            return
        missing = round((time.monotonic() - gap_start) * 16000)
        gaps.append({'start':round(count/16000, 2), 'duration':round(missing/16000, 2)})
        remaining = missing
        while remaining:
            block = min(remaining, 16000)
            output.writeframesraw(bytes(block*2))
            remaining -= block
        count += missing
        gap_start = None
        (FILES / filename).with_suffix('.gaps.json').write_text(json.dumps(gaps, ensure_ascii=False))
        with lock:
            state.update(seconds=round(count/16000, 2), samples=count,
                         missing_seconds=round(sum(g['duration'] for g in gaps), 2))

    try:
        if transport == 'wifi' and not settings:
            raise RuntimeError('Сначала подготовь Wi-Fi через USB.')
        while not stop_recording.is_set():
            try:
                if stream is None:
                    stream = open_recording_stream(transport)
                    with lock:
                        connection = stream
                    stream.write(('START ' + settings['token'] + '\n').encode() if transport == 'wifi' else b's')
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and not stop_recording.is_set():
                        if stream.readline().strip() == b'STREAM 16000':
                            break
                    else:
                        if stop_recording.is_set():
                            break
                        raise RuntimeError('Нет ответа от программы микрофона.')
                    if output is None:
                        filename = datetime.now(ZoneInfo('Europe/Moscow')).strftime('lecture-%Y-%m-%d-%H-%M-%S') + '-' + str(time.time_ns() % 1000000) + '.wav'
                        raw = (FILES / filename).open('w+b')
                        output = wave.open(raw, 'wb')
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(16000)
                    with lock:
                        state.update(recording=True, busy=False, file=filename, transport=transport,
                                     reconnecting=False, error='')
                header = exact(stream, 6)
                if header[:4] != b'PCM1':
                    raise RuntimeError('Ошибка передачи звука.')
                length = int.from_bytes(header[4:], 'little')
                if length == 0:
                    if transport == 'wifi':
                        raise RuntimeError('ESP остановила передачу звука.')
                    break
                if length > 512 or length % 2:
                    raise RuntimeError('Некорректный блок звука.')
                data = exact(stream, length)
                finish_gap()
                output.writeframesraw(data)
                count += length // 2
                if time.monotonic() - last_checkpoint >= 2:
                    output.writeframes(b'')
                    raw.flush()
                    os.fsync(raw.fileno())
                    last_checkpoint = time.monotonic()
                last_audio = time.monotonic()
                values = array.array('h', data)
                rms = math.sqrt(sum(v*v for v in values) / len(values))
                with lock:
                    state.update(seconds=round(count/16000, 2), samples=count, level=round(rms, 1))
            except InterruptedError:
                break
            except Exception:
                close_stream()
                if stop_recording.is_set():
                    break
                if transport != 'wifi':
                    raise
                if output and gap_start is None:
                    gap_start = last_audio or time.monotonic()
                with lock:
                    state.update(reconnecting=True, level=0)
                # Interruptible backoff; retries continue until the user stops recording.
                if stop_recording.wait(2):
                    break
    except Exception as exc:
        with lock:
            state['error'] = str(exc)
    finally:
        close_stream()
        if output:
            finish_gap()
            output.close()
            raw.flush()
            os.fsync(raw.fileno())
            raw.close()
        with lock:
            state.update(recording=False, busy=False, reconnecting=False, level=0)
            completed = filename if filename and not state.get('error') else None
        if filename:
            try:
                lesson_schedule.organize(filename)
            except OSError as exc:
                with lock:
                    state['error'] = 'Запись сохранена, но папка занятия не создана: '+str(exc)
        if completed and ai_service.auto:
            try:
                ai_service.submit(completed, wait_models=True)
            except Exception:
                pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, payload, status=200, mime='application/json'):
        if isinstance(payload, dict):
            payload = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/':
            return self.reply((ROOT / 'index.html').read_bytes(), mime='text/html; charset=utf-8')
        if self.path == '/status':
            with lock:
                result = dict(state)
            result['files'] = sorted([p.name for p in FILES.glob('*.wav')], reverse=True)
            result['wifi'] = {k: settings.get(k, '') for k in ('ssid', 'password', 'ip', 'mode')}
            result['usb_present'] = bool(usb_ports())
            result['ai'] = ai_service.status()
            result['schedule'] = lesson_schedule.current()
            result['lessons'] = {name:lesson_schedule.metadata(name) for name in result['files']}
            return self.reply(result)
        if self.path.startswith('/analysis/') or self.path.startswith('/export/'):
            from urllib.parse import unquote
            name = unquote(self.path.split('/', 2)[2])
            try:
                ai_service.file_path(name)
                result, _ = ai_service.paths(name)
                path = result if self.path.startswith('/analysis/') else result.with_suffix('.md')
                if not path.exists():
                    return self.reply({'error':'Разбор ещё не готов.'}, 404)
                return self.reply(path.read_bytes(), mime='application/json' if path.suffix=='.json' else 'text/markdown; charset=utf-8')
            except ValueError as exc:
                return self.reply({'error':str(exc)}, 400)
        if self.path.startswith('/recordings/'):
            name = self.path[len('/recordings/'):]
            if '/' not in name and '\\' not in name and name.endswith('.wav') and (FILES / name).is_file():
                with lock:
                    active = state['recording'] and state['file'] == name
                if active:
                    return self.reply({'error': 'Сначала останови запись.'}, 409)
                path = FILES / name
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(path.stat().st_size))
                self.end_headers()
                with path.open('rb') as audio:
                    shutil.copyfileobj(audio, self.wfile)
                return
        self.reply({'error': 'Не найдено'}, 404)

    def do_POST(self):
        global worker
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'):
            return self.reply({'error': 'Запрос отклонён'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            return self.reply({'error': 'Некорректный размер запроса'}, 400)
        if not 0 <= length <= 4096:
            return self.reply({'error': 'Слишком большой запрос'}, 413)
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (ValueError, UnicodeDecodeError):
            return self.reply({'error': 'Некорректный запрос'}, 400)
        if not isinstance(body, dict):
            return self.reply({'error': 'Нужен объект JSON'}, 400)
        with lock:
            if state.get('updating'):
                return self.reply({'error': 'Устанавливается обновление'}, 409)
        if self.path == '/ai-settings':
            if 'economical' in body:
                ai_service.set_economical(body['economical'])
            if 'paused' in body:
                ai_service.set_paused(body['paused'])
            if 'speech' in body:
                try:
                    ai_service.set_speech(body['speech'])
                except ValueError as exc:
                    return self.reply({'error':str(exc)},400)
            if 'auto' in body:
                ai_service.set_auto(body['auto'])
            return self.reply({'ok':True})
        if self.path == '/analyze':
            with lock:
                active = state['recording'] and state['file'] == body.get('file')
            if active:
                return self.reply({'error':'Сначала останови эту запись.'}, 409)
            try:
                ai_service.submit(body.get('file'))
                return self.reply({'ok':True})
            except (ValueError, RuntimeError) as exc:
                return self.reply({'error':str(exc)}, 400)
        if self.path in ('/pair', '/check-wifi', '/setup-hotspot'):
            with lock:
                if state['recording'] or state['busy']:
                    return self.reply({'error': 'Сначала останови запись.'}, 409)
                state['busy'] = True
            try:
                if self.path == '/pair':
                    pair()
                    return self.reply({'ok': True})
                if self.path == '/setup-hotspot':
                    setup_hotspot(body)
                    return self.reply({'ok': True})
                return self.reply({'ok': True, 'status': check_wifi()})
            except Exception as exc:
                return self.reply({'error': str(exc)}, 400)
            finally:
                with lock:
                    state['busy'] = False
        if self.path == '/start':
            with lock:
                if state['recording'] or state['busy']:
                    return self.reply({'error': 'Запись уже запускается или идёт.'}, 409)
                stop_recording.clear()
                state.update(busy=True, error='', seconds=0, samples=0, file='', reconnecting=False, missing_seconds=0)
            transport = body.get('transport', 'usb')
            worker = threading.Thread(target=capture, args=(transport,), daemon=True)
            worker.start()
            return self.reply({'ok': True})
        if self.path == '/shutdown-for-update':
            with lock:
                with ai_service.lock:
                    if state['recording'] or state['busy'] or ai_service.pending:
                        return self.reply({'error': 'Запись или обработка ещё идёт'}, 409)
                    state.update(busy=True, updating=True)
                    ai_service.stopping = True
            self.reply({'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path == '/stop':
            stop_recording.set()
            with lock:
                if connection:
                    try:
                        connection.write(b'x')
                    except Exception:
                        pass
            if worker:
                worker.join(timeout=5)
            return self.reply({'ok': True})
        self.reply({'error': 'Не найдено'}, 404)


if __name__ == '__main__':
    from wav_recovery import recover
    recover(FILES)
    lesson_schedule.organize_existing()
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    print('Recorder: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_recording.set()
        with lock:
            if connection:
                try:
                    connection.write(b'x')
                except Exception:
                    pass
        if worker:
            worker.join(timeout=5)
    finally:
        ai_service.shutdown()
        server.server_close()
