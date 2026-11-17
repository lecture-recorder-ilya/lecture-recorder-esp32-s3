import argparse
import hashlib
import json
import os
import queue
import subprocess
import threading
import uuid
import wave
from pathlib import Path

from audio_import import atomic, validate
from speech_audio import ENHANCEMENT, PROFILES


def signature(path):
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'inode': stat.st_ino}


def read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def key(name, profile):
    if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name or '\x00' in name or not name.endswith('.wav'):
        raise ValueError('Некорректное имя записи.')
    if profile not in PROFILES:
        raise ValueError('Выбери бережную или усиленную очистку.')
    return hashlib.sha256((name + '\n' + profile + '\n' + ENHANCEMENT).encode()).hexdigest()


def render(source, target, info_path, profile):
    import numpy as np
    from speech_audio import enhance_audio
    from speech_gate import strict_speech_ranges

    seconds = validate(source)
    before = signature(source)
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with wave.open(str(source)) as audio, wave.open(str(temporary), 'wb') as output:
            output.setparams(audio.getparams())
            total = audio.getnframes()
            step, margin = 30 * 16000, 2 * 16000
            for offset in range(0, total, step):
                start, end = max(0, offset - margin), min(total, offset + step + margin)
                audio.setpos(start)
                samples = np.frombuffer(audio.readframes(end - start), dtype='<i2').astype(np.float32) / 32768
                if len(samples) != end - start:
                    raise ValueError('Запись изменилась во время очистки. Повтори после окончания записи.')
                clean = enhance_audio(samples, strict_speech_ranges(samples), profile=profile)
                clean = clean[offset - start:min(total, offset + step) - start]
                output.writeframesraw((np.clip(clean, -1, 1) * 32767).round().astype('<i2').tobytes())
        if signature(source) != before:
            raise ValueError('Запись изменилась во время очистки. Повтори после окончания записи.')
        if validate(temporary) != seconds:
            raise ValueError('Длительность обработанного файла не совпала с оригиналом.')
        os.replace(temporary, target)
        atomic(info_path, {'source': before, 'source_sha256': digest.hexdigest(), 'engine': ENHANCEMENT,
                           'profile': profile, 'seconds': seconds, 'output': signature(target), 'timeline_preserved': True})
    finally:
        temporary.unlink(missing_ok=True)


class Enhancer:
    def __init__(self, root):
        self.root = Path(root)
        self.folder = self.root / 'enhanced'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.tasks = queue.Queue()
        self.stopped = threading.Event()
        self.process = None
        self.pending = set()
        for path in self.folder.glob('*.job.json'):
            job = read(path)
            if job.get('status') in ('queued', 'processing'):
                try:
                    if path.name != key(job['file'], job['profile']) + '.job.json':
                        continue
                    job.update(status='queued', message='Продолжаю очистку звука')
                    atomic(path, job)
                    self.pending.add(path.stem.removesuffix('.job'))
                    self.tasks.put(job)
                except (ValueError, KeyError, TypeError):
                    continue
        self.worker = threading.Thread(target=self._work, daemon=True, name='Очистка записи')
        self.worker.start()

    def _paths(self, name, profile):
        ident = key(name, profile)
        return tuple(self.folder / (ident + suffix) for suffix in ('.wav', '.info.json', '.job.json'))

    def status(self, name, profile='gentle'):
        target, info_path, job_path = self._paths(name, profile)
        source = self.root / 'recordings' / name
        info = read(info_path)
        if target.is_file() and info.get('output') == signature(target) and info.get('source') == signature(source) and info.get('engine') == ENHANCEMENT:
            from urllib.parse import quote
            return {'status': 'ready', 'profile': profile, 'message': 'Звук очищен · таймкоды сохранены',
                    'url': '/enhanced-audio/' + quote(name) + '?profile=' + profile,
                    'seconds': info['seconds']}
        job = read(job_path)
        return {k: job[k] for k in ('status', 'message', 'profile') if k in job} if job.get('status') in ('queued', 'processing', 'error') else {'status': 'idle', 'profile': profile}

    def audio(self, name, profile='gentle'):
        if self.status(name, profile)['status'] != 'ready':
            raise ValueError('Сначала подготовь очищенную запись.')
        return self._paths(name, profile)[0]

    def request(self, name, profile='gentle'):
        target, _, job_path = self._paths(name, profile)
        source = self.root / 'recordings' / name
        if not source.is_file():
            raise ValueError('Запись не найдена.')
        ident = target.stem
        with self.lock:
            if self.stopped.is_set():
                raise ValueError('Приложение перезапускается. Повтори после запуска.')
            current = self.status(name, profile)
            if current['status'] == 'ready' or ident in self.pending:
                return current
            job = {'file': name, 'profile': profile, 'status': 'queued', 'message': 'Запись в очереди на очистку'}
            atomic(job_path, job)
            self.pending.add(ident)
            self.tasks.put(job)
            return current | {'status': 'queued', 'message': job['message']}

    def active(self):
        with self.lock:
            return bool(self.pending)

    def _work(self):
        while not self.stopped.is_set():
            job = self.tasks.get()
            if job is None:
                self.tasks.task_done()
                return
            target, info_path, job_path = self._paths(job['file'], job['profile'])
            try:
                job.update(status='processing', message='Убираю фоновый шум и выравниваю громкость')
                atomic(job_path, job)
                project = self.root.parent.parent
                python = project / 'work/ai-env/bin/python'
                if not python.is_file():
                    raise ValueError('Компоненты обработки ещё не готовы. Заверши установку приложения.')
                with self.lock:
                    if self.stopped.is_set():
                        raise ValueError('Очистка прервана. Нажми повторить после запуска.')
                    self.process = subprocess.Popen([str(python), str(Path(__file__).resolve()), str(self.root / 'recordings' / job['file']),
                                                     str(target), str(info_path), '--profile', job['profile']],
                                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    code = self.process.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                    raise ValueError('Очистка заняла слишком много времени. Попробуй более короткую запись.')
                if code != 0 or self.status(job['file'], job['profile'])['status'] != 'ready':
                    raise ValueError('Не удалось очистить звук. Оригинал сохранён, можно повторить.')
                job.update(status='ready', message='Звук очищен · таймкоды сохранены')
            except (OSError, ValueError) as error:
                job.update(status='error', message=str(error)[:300])
            finally:
                atomic(job_path, job)
                with self.lock:
                    self.process = None
                    self.pending.discard(target.stem)
                self.tasks.task_done()

    def close(self):
        with self.lock:
            self.stopped.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self.tasks.put(None)
        self.worker.join(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('info', type=Path)
    parser.add_argument('--profile', choices=PROFILES, default='gentle')
    args = parser.parse_args()
    os.nice(10)
    render(args.source, args.target, args.info, args.profile)
