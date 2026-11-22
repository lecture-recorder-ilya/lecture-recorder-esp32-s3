import fcntl
import os
import stat
import time
from http.client import HTTPException
from urllib.request import Request

import character_weights as weights

URL = f'https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/{weights.REVISION}/{weights.FILENAME}'
BLOCK = 256 * 1024
RETRY_SECONDS = 60


class ModelRefresh:
    def __init__(self, project):
        self.folder = project / 'work/models/gigaam-beam'
        self.attempts = 0
        self.retry_at = 0

    def after_check(self, current):
        self.attempts = 2 if current is True else 0
        self.retry_at = 0

    def poll(self, fetch, idle, interrupted=lambda: False):
        if not self.attempts or time.monotonic() < self.retry_at:
            return
        try:
            if self._refresh(fetch, idle, interrupted):
                self.attempts = 0
            else:
                self.retry_at = time.monotonic() + 10
        except (OSError, HTTPException, ValueError):
            self.attempts -= 1
            self.retry_at = time.monotonic() + RETRY_SECONDS

    def _refresh(self, fetch, idle, interrupted):
        if not ((self.folder / 'v3_ctc.onnx').is_file() and (self.folder.parent / 'gigaam-beam-manifest.json').is_file()):
            return True
        if interrupted() or not idle():
            return False
        if weights.available(self.folder):
            return True
        with (self.folder / '.character-download.lock').open('a') as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            if weights.available(self.folder):
                return True
            part = self.folder / f'.{weights.FILENAME}.{weights.SHA256[:12]}.part'
            try:
                info = part.lstat()
            except FileNotFoundError:
                info = None
            offset = info.st_size if info else 0
            if info and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or offset > weights.SIZE):
                part.unlink()
                offset = 0
            if offset < weights.SIZE and not receive(fetch, idle, interrupted, part, offset):
                return False
            if interrupted() or not idle():
                return False
            if not weights.valid_file(part):
                part.unlink(missing_ok=True)
                raise ValueError('Контрольная сумма модели не совпала')
            if interrupted():
                return False
            os.replace(part, self.folder / weights.FILENAME)
            return True


def receive(fetch, idle, interrupted, part, offset):
    headers = {'User-Agent': 'LectureRecorder-ModelUpdate', 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    with fetch(Request(URL, headers=headers), timeout=8) as response:
        if response.status == 200:
            offset = 0
        elif response.status != 206 or response.headers.get('Content-Range') != f'bytes {offset}-{weights.SIZE-1}/{weights.SIZE}':
            raise ValueError('Некорректный диапазон модели')
        length = response.headers.get('Content-Length')
        if length is not None and int(length) != weights.SIZE - offset:
            raise ValueError('Неверный размер модели')
        next_check = 0
        read = getattr(response, 'read1', response.read)
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if offset else 0)
        with os.fdopen(os.open(part, flags, 0o600), 'ab' if offset else 'wb') as target:
            info = os.fstat(target.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (offset and info.st_size != offset):
                raise OSError('Временный файл модели изменился')
            if not offset:
                target.truncate(0)
            while offset < weights.SIZE:
                if interrupted():
                    return False
                if time.monotonic() >= next_check:
                    if not idle():
                        return False
                    next_check = time.monotonic() + .5
                block = read(min(BLOCK, weights.SIZE - offset))
                if not block:
                    raise OSError('Загрузка модели прервалась')
                if len(block) > weights.SIZE - offset:
                    raise ValueError('Модель больше ожидаемого размера')
                target.write(block)
                offset += len(block)
            if interrupted():
                return False
            if read(1):
                part.unlink(missing_ok=True)
                raise ValueError('Модель больше ожидаемого размера')
            target.flush()
            os.fsync(target.fileno())
    return True
