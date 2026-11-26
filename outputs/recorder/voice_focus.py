import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import uuid
import wave
from pathlib import Path
from urllib.parse import urlencode

from audio_import import atomic


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def stamp(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ino]


def audio_info(path):
    with wave.open(str(path), 'rb') as audio:
        if (audio.getframerate(), audio.getsampwidth(), audio.getnchannels()) != (16000, 2, 1):
            raise ValueError('Для разбора открой запись через импорт в библиотеку.')
        return audio.getnframes()


def reference_frames(start, end, frames):
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)):
        raise ValueError('Укажи начало и конец образца в секундах.')
    a, b = round(16000 * start), round(16000 * end)
    if not (0 <= a < b <= frames and 3 * 16000 <= b - a <= 20 * 16000):
        raise ValueError('Выбери от 3 до 20 секунд в пределах записи, где слышен один голос.')
    return a, b


def focus_frames(start, frames):
    if start is None:
        return 0, frames
    if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
        raise ValueError('Выбери момент в исходной записи.')
    first = round(start * 16000)
    if frames - first < 16000:
        raise ValueError('Выбери момент хотя бы за секунду до конца записи.')
    return first, min(frames, first + 20 * 16000)


def write_reference(source, target, bounds):
    with wave.open(str(source), 'rb') as audio, wave.open(str(target), 'wb') as sample:
        sample.setparams(audio.getparams())
        audio.setpos(bounds[0])
        data = audio.readframes(bounds[1] - bounds[0])
        if len(data) != 2 * (bounds[1] - bounds[0]):
            raise ValueError('Запись изменилась. Выбери образец ещё раз.')
        sample.writeframes(data)


def mask_intervals(source, target, intervals):
    with wave.open(str(source), 'rb') as src, wave.open(str(target), 'wb') as out:
        out.setparams(src.getparams())
        ranges = [(round(row['start'] * 16000), round(row['end'] * 16000)) for row in intervals]
        index = 0
        for start in range(0, src.getnframes(), 16000):
            data = bytearray(src.readframes(16000))
            end = start + len(data) // 2
            while index < len(ranges) and ranges[index][1] <= start:
                index += 1
            for i in range(index, len(ranges)):
                left, right = ranges[i]
                if left >= end:
                    break
                a, b = 2 * (max(start, left) - start), 2 * (min(end, right) - start)
                data[a:b] = bytes(b - a)
            out.writeframesraw(data)


class VoiceFocus:
    def __init__(self, root):
        self.root = Path(root)
        self.work = self.root.parent.parent / 'work'
        self.runtime = self.work / 'target-speech'
        self.library = self.work / 'voice-focus'
        self.lock = threading.RLock()
        self.job = None
        self.child = None
        self.thread = None
        self.stopping = False

    def available(self):
        return all(p.is_file() for p in (self.runtime / 'bin/python', self.runtime / 'models/pins.json',
                                         self.runtime / 'models/frozen.json', self.root / 'target_speech.py',
                                         self.work / 'asr-env/bin/python'))

    def source(self, name):
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.wav') or any(c in name for c in ('\\', '\x00')):
            raise ValueError('Некорректное имя записи.')
        path = self.root / 'recordings' / name
        if not path.is_file():
            raise ValueError('Запись не найдена.')
        return path

    def directory(self, name):
        return self.library / hashlib.sha256(name.encode()).hexdigest()

    def pipeline_signature(self):
        code = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.root.glob('*.py'))}
        models = {}
        folders = [self.runtime / 'models'] + [self.runtime / 'models' / name
                                              for name in ('libri', 'whamr', 'ecapa')]
        folders += [self.work / 'models' / name for name in ('gigaam', 'gigaam-rnnt', 'gigaam-beam')]
        for folder in folders:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    info = path.stat()
                    models[str(path.relative_to(self.work))] = [info.st_size, info.st_mtime_ns,
                                                                info.st_ctime_ns, info.st_ino]
        for path in sorted((self.work / 'models').glob('gigaam*-manifest.json')):
            models[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ('frozen.json', 'pins.json'):
            path = self.runtime / 'models' / name
            if path.is_file():
                models[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        payload = json.dumps({'schema': 1, 'code': code, 'models': models}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def result(self, name):
        source = self.source(name)
        folder = self.directory(name)
        result = read_json(folder / 'current.json')
        if not result or result.get('source') != stamp(source):
            return {}
        ref = self.root / 'recordings' / result['reference']
        if not ref.is_file() or result.get('reference_stamp') != stamp(ref):
            return {}
        try:
            if result.get('pipeline') != self.pipeline_signature():
                return {}
        except OSError:
            return {}
        return result

    def status(self, name):
        result = self.result(name)
        with self.lock:
            job = dict(self.job) if self.job and self.job['file'] == name else {}
        value = {'available': self.available(), 'status': 'idle'}
        if result:
            value.update(status='ready', reference=result['reference'], start=result['start'], end=result['end'],
                         audio='/voice-focus/audio?' + urlencode({'file': name, 'id': result['id']}),
                         segments=result['segments'], unsure=result['unsure'], match=result['match'],
                         offset=result.get('offset', 0), until=result.get('until'))
        value.update(job)
        return value

    def audio(self, name, result_id):
        result = self.result(name)
        if not result or result['id'] != result_id:
            raise ValueError('Этот разбор больше не доступен.')
        return self.directory(name) / result_id / 'focus.wav'

    def active(self):
        with self.lock:
            return bool(self.job and self.job.get('status') == 'processing')

    def start(self, name, reference, start, end, clip_start=None):
        src = self.source(name)
        ref = self.source(reference)
        bounds = reference_frames(start, end, audio_info(ref))
        interval = focus_frames(clip_start, audio_info(src))
        selection = [reference, *bounds, *interval]
        if not self.available():
            raise ValueError('На этом Mac ещё нет локального модуля выделения голоса.')
        signature = {'source': stamp(src), 'reference_stamp': stamp(ref), 'reference': reference,
                     'start': bounds[0] / 16000, 'end': bounds[1] / 16000,
                     'method': stamp(self.root / 'target_speech.py'), 'models': stamp(self.runtime / 'models/frozen.json'),
                     'pipeline': self.pipeline_signature(),
                     'offset': interval[0] / 16000, 'until': interval[1] / 16000}
        with self.lock:
            if self.stopping:
                raise ValueError('Приложение перезапускается.')
            if self.active():
                if self.job['file'] == name and self.job.get('selection') == selection:
                    return self.status(name)
                raise ValueError('Дождись текущего разбора голоса.')
            previous = self.result(name)
            if previous and all(previous.get(k) == v for k, v in signature.items()):
                self.job = None
                return self.status(name)
            self.job = {'file': name, 'selection': selection, 'status': 'processing',
                        'message': 'Разделяю голоса на этом Mac…'}
            self.thread = threading.Thread(target=self._run, args=(src, ref, bounds, interval, signature), daemon=True)
            self.thread.start()
            return self.status(name)

    def _execute(self, command, folder):
        with self.lock:
            if self.stopping:
                raise ValueError('Обработка прервана. Можно запустить ещё раз.')
            env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                       PYTORCH_ENABLE_MPS_FALLBACK='1')
            with (folder / 'worker.log').open('a') as log:
                self.child = subprocess.Popen([str(v) for v in command], stdin=subprocess.DEVNULL,
                                              stdout=log, stderr=log, env=env)
                child = self.child
        if child.wait() != 0:
            raise ValueError('Обработка прервалась. Проверь образец и повтори.')

    def separate(self, source, reference, output, decisions, folder):
        models = self.runtime / 'models'
        device = 'mps' if platform.system() == 'Darwin' and platform.machine() == 'arm64' else 'cpu'
        interpreter = (self.runtime / 'bin').resolve() / 'python'
        self._execute([interpreter, self.root / 'target_speech.py', '--mixture', source,
                       '--reference', reference, '--output', output, '--report', decisions, '--models', models,
                       '--config', models / 'frozen.json', '--device', device], folder)

    def recognize(self, focused, folder):
        decisions = read_json(folder / 'decisions.json')
        state = decisions.get('status')
        if state not in ('matched', 'partial', 'not_found') or decisions.get('timeline_preserved') is not True:
            raise ValueError('Модуль не подтвердил границы дорожки.')
        unknown = []
        for item in decisions['uncertain_intervals']:
            if unknown and item['start'] == unknown[-1]['end']:
                unknown[-1]['end'] = item['end']
            else:
                unknown.append({'start': item['start'], 'end': item['end']})
        if state == 'not_found':
            return [], unknown, state
        audio = focused
        if unknown:
            audio = folder / 'recognition.wav'
            mask_intervals(focused, audio, unknown)
        self._execute([self.work / 'asr-env/bin/python', self.root / 'qwen_transcribe.py', audio,
                       folder / 'text.json', folder / 'progress.json'], folder)
        transcript = read_json(folder / 'text.transcript.json')
        if transcript.get('complete') is not True:
            raise ValueError('Расшифровка прервалась. Можно запустить ещё раз.')
        rows = []
        for row in transcript['segments']:
            if not any(a['start'] < row['end'] and a['end'] > row['start'] for a in unknown):
                rows.append({key: row[key] for key in ('start', 'end', 'text')})
        return rows, unknown, state

    def _run(self, src, ref, bounds, interval, signature):
        folder = self.directory(src.name)
        try:
            if self.pipeline_signature() != signature['pipeline']:
                raise ValueError('Код или модели распознавания изменились. Запусти разбор ещё раз.')
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='run-', dir=folder) as scratch:
                temp = Path(scratch)
                sample, focused = temp / 'reference.wav', temp / 'focus.wav'
                write_reference(ref, sample, bounds)
                mixture = src
                if interval != (0, audio_info(src)):
                    mixture = temp / 'excerpt.wav'
                    write_reference(src, mixture, interval)
                self.separate(mixture, sample, focused, temp / 'decisions.json', temp)
                if audio_info(focused) != interval[1] - interval[0]:
                    raise ValueError('Длина дорожки изменилась. Сохранили исходную запись.')
                with self.lock:
                    self.job['message'] = 'Распознаю выделенную дорожку на Mac…'
                segments, unsure, state = self.recognize(focused, temp)
                for item in segments + unsure:
                    for key in ('start', 'end'):
                        item[key] += signature['offset']
                if stamp(src) != signature['source'] or stamp(ref) != signature['reference_stamp']:
                    raise ValueError('Запись изменилась. Открой её заново.')
                if self.pipeline_signature() != signature['pipeline']:
                    raise ValueError('Код или модели распознавания изменились. Запусти разбор ещё раз.')
                result_id = uuid.uuid4().hex
                output = folder / result_id
                output.mkdir()
                try:
                    old = read_json(folder / 'current.json')
                    os.replace(focused, output / 'focus.wav')
                    atomic(folder / 'current.json', dict(signature, id=result_id, segments=segments, unsure=unsure, match=state))
                except BaseException:
                    shutil.rmtree(output, ignore_errors=True)
                    raise
                old_id = old.get('id', '')
                if len(old_id) == 32 and all(c in '0123456789abcdef' for c in old_id):
                    shutil.rmtree(folder / old_id, ignore_errors=True)
                with self.lock:
                    self.job = None
        except (OSError, ValueError, KeyError, wave.Error) as error:
            with self.lock:
                self.job = {'file': src.name, 'status': 'error', 'message': str(error)}
        finally:
            with self.lock:
                if self.thread is threading.current_thread():
                    self.child = None

    def close(self):
        with self.lock:
            self.stopping = True
            child, thread = self.child, self.thread
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        if thread:
            thread.join()
