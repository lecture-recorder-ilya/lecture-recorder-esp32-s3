import hashlib
from array import array
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MAX_BYTES = 2 * 1024 ** 3
MAX_SECONDS = 8 * 3600
EXTENSIONS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.aif', '.aiff', '.caf', '.ogg', '.opus', '.webm', '.mp4'}


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_cancelled_stereo(audio, target):
    if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (2, 2, 16000, 'NONE'):
        return False
    expected = audio.getnframes() * 4
    if not 0 < expected <= MAX_SECONDS * 64000:
        raise ValueError('Выбери запись длительностью от одного отсчёта до 8 часов.')
    copied, signal = 0, False
    while block := audio.readframes(16000 * 30):
        copied += len(block)
        if len(block) % 4:
            raise ValueError('WAV обрывается посреди стереоотсчёта.')
        values = array('h', block)
        if sys.byteorder != 'little':
            values.byteswap()
        if any(left + right for left, right in zip(values[::2], values[1::2])):
            return False
        signal = signal or any(values)
    if copied != expected:
        raise ValueError('WAV обрывается раньше указанной длительности.')
    if not signal:
        return False
    audio.rewind()
    with wave.open(str(target), 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        while block := audio.readframes(16000 * 30):
            output.writeframesraw(array('h', block)[::2].tobytes())
    return True


def normalize(source, target, project, run=subprocess.run):
    try:
        with wave.open(str(source)) as audio:
            ready = audio.getnchannels() == 1 and audio.getsampwidth() == 2 and audio.getframerate() == 16000 and audio.getcomptype() == 'NONE'
            if ready:
                expected = audio.getnframes() * 2
                if expected <= 0 or expected > MAX_SECONDS * 32000:
                    raise ValueError('Выбери запись длительностью от одного отсчёта до 8 часов.')
                with wave.open(str(target), 'wb') as output:
                    output.setparams(audio.getparams())
                    copied = 0
                    while block := audio.readframes(16000 * 30):
                        output.writeframesraw(block)
                        copied += len(block)
                if copied != expected:
                    raise ValueError('WAV обрывается раньше указанной длительности.')
                return validate(target)
            if _restore_cancelled_stereo(audio, target):
                return validate(target)
    except (wave.Error, EOFError):
        pass
    converters = []
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        candidates = sorted((project / 'work').glob('**/imageio_ffmpeg/binaries/ffmpeg*'))
        ffmpeg = str(candidates[0]) if candidates else None
    if ffmpeg:
        converters.append([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-f', 'wav', str(target)])
    if Path('/usr/bin/afconvert').exists():
        converters.append(['/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1', '--mix', str(source), str(target)])
    if not converters:
        raise ValueError('Не удалось открыть этот формат. Экспортируй запись в WAV, MP3 или M4A на Mac.')
    for command in converters:
        target.unlink(missing_ok=True)
        try:
            result = run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900)
            if result.returncode == 0:
                return validate(target)
        except subprocess.TimeoutExpired:
            raise ValueError('Подготовка аудио заняла слишком много времени. Попробуй экспортировать запись в WAV.')
        except (OSError, ValueError, wave.Error):
            continue
    raise ValueError('Аудио не открылось. Проверь воспроизведение файла или экспортируй его в WAV, MP3 либо M4A.')


def validate(path):
    with wave.open(str(path)) as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000:
            raise ValueError('Не удалось подготовить аудио для распознавания.')
        seconds = audio.getnframes() / 16000
        if not 0 < seconds <= MAX_SECONDS:
            raise ValueError('Поддерживаются записи длительностью до 8 часов.')
        audio.setpos(max(0, audio.getnframes() - 1))
        if len(audio.readframes(1)) != 2:
            raise ValueError('Аудиофайл обрывается до окончания записи.')
        return round(seconds, 3)


class Importer:
    def __init__(self, root, on_ready):
        self.root = Path(root)
        self.project = self.root.parent.parent
        self.folder = self.root / 'imports'
        self.jobs = self.folder / 'jobs'
        self.originals = self.folder / 'originals'
        for folder in (self.jobs, self.originals, self.root / 'recordings'):
            folder.mkdir(parents=True, exist_ok=True)
        self.on_ready = on_ready
        self.lock = threading.RLock()
        self.tasks = queue.Queue()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True, name='Импорт аудио')
        for path in self.jobs.glob('*.json'):
            try:
                job = json.loads(path.read_text())
                if job.get('status') in ('queued', 'converting', 'scheduling'):
                    job.update(status='queued', message='Продолжаю подготовку записи')
                    self._save(job)
                    self.tasks.put(job['id'])
            except (OSError, ValueError, KeyError):
                continue
        self.worker.start()

    def _save(self, job):
        job['updated'] = time.time()
        atomic(self.jobs / (job['id'] + '.json'), job)

    def list(self):
        result = []
        with self.lock:
            for path in self.jobs.glob('*.json'):
                try:
                    value = json.loads(path.read_text())
                    result.append({k: value[k] for k in ('id', 'name', 'file', 'status', 'message', 'seconds', 'created', 'updated', 'subject', 'title', 'analyze') if k in value})
                except (OSError, ValueError):
                    continue
        return sorted(result, key=lambda value: value['created'], reverse=True)[:100]

    def active(self):
        return any(job['status'] in ('queued', 'converting', 'scheduling') for job in self.list())

    def receive(self, source, size, name, metadata):
        if not isinstance(size, int) or not 0 < size <= MAX_BYTES:
            raise ValueError('Выбери непустой аудиофайл размером до 2 ГБ.')
        if not isinstance(name, str) or not name.strip() or len(name) > 255 or re.search(r'[\x00-\x1f/\\]', name):
            raise ValueError('Некорректное имя аудиофайла.')
        extension = Path(name).suffix.lower()
        if extension not in EXTENSIONS:
            raise ValueError('Выбери WAV, MP3, M4A, AAC, FLAC, AIFF, OGG или другую аудиозапись.')
        clean = {}
        for key in ('title', 'subject', 'date', 'teacher'):
            value = metadata.get(key, '')
            if not isinstance(value, str) or len(value) > 160 or re.search(r'[\x00-\x1f]', value):
                raise ValueError('Проверь название и данные занятия.')
            clean[key] = value.strip()
        if clean['date']:
            try:
                datetime.strptime(clean['date'], '%Y-%m-%d')
            except ValueError:
                raise ValueError('Выбери дату занятия в календаре.')
        ident = uuid.uuid4().hex
        original = self.originals / (ident + extension)
        temporary = original.with_suffix(extension + '.upload')
        digest = hashlib.sha256()
        try:
            with temporary.open('xb') as output:
                remaining = size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Загрузка прервалась. Исходный файл остался у тебя; повтори загрузку.')
                    output.write(block)
                    digest.update(block)
                    remaining -= len(block)
                output.flush()
                os.fsync(output.fileno())
            with self.lock:
                if self.stopped.is_set():
                    raise ValueError('Приложение перезапускается. Повтори загрузку после запуска.')
                fingerprint = digest.hexdigest()
                for path in self.jobs.glob('*.json'):
                    try:
                        old = json.loads(path.read_text())
                    except (ValueError, OSError):
                        continue
                    if old.get('sha256') == fingerprint and all(old.get(k, '') == v for k, v in clean.items()) and old.get('status') != 'error':
                        return dict(old, duplicate=True)
                os.replace(temporary, original)
                now = datetime.now(ZoneInfo('Europe/Moscow'))
                name_wav = 'lecture-' + now.strftime('%Y-%m-%d-%H-%M-%S-%f') + '.wav'
                job = dict(clean, id=ident, name=name, source=original.name, sha256=fingerprint, bytes=size,
                           file=name_wav, created=time.time(), status='queued', message='Аудио загружено · готовлю запись',
                           analyze=metadata.get('analyze', True) is not False)
                self._save(job)
                self.tasks.put(ident)
                return job
        finally:
            temporary.unlink(missing_ok=True)

    def retry(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise ValueError('Загрузка не найдена.')
        with self.lock:
            job = json.loads((self.jobs / (ident + '.json')).read_text())
            if job['status'] != 'error':
                return job
            job.update(status='queued', message='Повторяю подготовку записи')
            self._save(job)
            self.tasks.put(ident)
            return job

    def _work(self):
        while not self.stopped.is_set():
            ident = self.tasks.get()
            if ident is None:
                return
            path = self.jobs / (ident + '.json')
            temporary = self.folder / (ident + '.' + uuid.uuid4().hex + '.prepared.wav')
            job = {'id': ident, 'created': time.time()}
            try:
                with self.lock:
                    job = json.loads(path.read_text())
                    job.update(status='converting', message='Подготавливаю звук для распознавания')
                    self._save(job)
                destination = self.root / 'recordings' / job['file']
                if destination.exists():
                    seconds = validate(destination)
                else:
                    seconds = normalize(self.originals / job['source'], temporary, self.project)
                    os.replace(temporary, destination)
                with self.lock:
                    job.update(status='scheduling', seconds=seconds, message='Запись сохранена · добавляю в библиотеку')
                    self._save(job)
                self.on_ready(job)
                with self.lock:
                    job.update(status='ready', message='Запись в библиотеке · ожидает разбора' if job['analyze'] else 'Запись сохранена в библиотеке')
                    self._save(job)
            except Exception as error:
                with self.lock:
                    job.update(status='error', message=str(error)[:500] or 'Не удалось подготовить аудио. Повтори загрузку.')
                    self._save(job)
            finally:
                temporary.unlink(missing_ok=True)
                self.tasks.task_done()

    def close(self):
        self.stopped.set()
        self.tasks.put(None)
