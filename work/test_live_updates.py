import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/recorder'
sys.path.insert(0, str(SOURCE))
submitted = []
ai = types.ModuleType('ai_service')
ai.auto = True
ai.status = lambda: {'ready': True, 'auto': ai.auto, 'jobs': {}}
ai.submit = lambda name, **kwargs: submitted.append(name)
ai.set_auto = lambda value: setattr(ai, 'auto', value)
ai.set_speech = lambda value: None
schedule = types.ModuleType('lesson_schedule')
schedule.current = lambda: {}
schedule.metadata = lambda name: None
schedule.organize = lambda name: None
sys.modules.update(ai_service=ai, lesson_schedule=schedule)
spec = importlib.util.spec_from_file_location('isolated_recorder', SOURCE / 'recorder.py')
recording = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recording)
recording.settings = {'token': 'fixture'}

class Microphone:
    def __init__(self):
        self.data = bytearray()
    def readline(self):
        return b'STREAM 16000\n'
    def read(self, count):
        if not self.data:
            time.sleep(.005)
            pcm = (321).to_bytes(2, 'little', signed=True) * 256
            self.data.extend(b'PCM1' + len(pcm).to_bytes(2, 'little') + pcm)
        result = bytes(self.data[:count])
        del self.data[:count]
        return result
    def write(self, data):
        pass
    def close(self):
        pass
recording.NetworkStream = Microphone

def request(base, path, body=None, origin=None):
    headers = {'Content-Type': 'application/json'}
    if origin:
        headers['Origin'] = origin
    req = Request(base + path, data=body, headers=headers)
    try:
        response = urlopen(req, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.code, response.read()

def get(base, path):
    code, data = request(base, path)
    assert code == 200, (code, data)
    return json.loads(data)

def wait_for(check, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (URLError, OSError):
            pass
        time.sleep(.03)
    raise AssertionError('Timed out')

with tempfile.TemporaryDirectory() as folder:
    directory = Path(folder)/'project/outputs/recorder'
    directory.mkdir(parents=True)
    recording.FILES = directory / 'recordings'
    recording.FILES.mkdir()
    for source in SOURCE.glob('*.py'):
        shutil.copy(source, directory)
    shutil.copy(SOURCE/'schedule.example.json',directory)
    (directory / 'index.html').write_text('before update')
    engine = recording.ThreadingHTTPServer(('127.0.0.1', 0), recording.Handler)
    engine_thread = threading.Thread(target=engine.serve_forever, daemon=True)
    engine_thread.start()
    engine_url = 'http://127.0.0.1:' + str(engine.server_port)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        app_port = reservation.getsockname()[1]
    app_url = 'http://127.0.0.1:' + str(app_port)
    command = [sys.executable, str(directory / 'app_server.py'), '--port', str(app_port),
               '--service-url', engine_url, '--no-start-service']
    processes = []
    def launch():
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        processes.append(process)
        wait_for(lambda: get(app_url, '/app-info'))
        return process
    try:
        process = launch()
        assert request(app_url, '/start', b'{"transport":"wifi"}', app_url)[0] == 200
        initial = wait_for(lambda: (s if (s := get(app_url, '/status'))['samples'] > 0 else None))
        audio = recording.FILES / initial['file']
        inode = audio.stat().st_ino
        assert request(app_url, '/analyze', json.dumps({'file': initial['file']}).encode())[0] == 409
        assert request(app_url, '/stop', b'{}', 'https://example.org')[0] == 403
        assert request(app_url, '/start', b'{}')[0] == 409
        assert request(app_url, '/ai-settings', b'[]')[0] == 400
        assert request(app_url, '/unknown', b'{}')[0] == 404
        assert request(app_url, '/ai-settings', b'{"auto":true}')[0] == 200
        for index in range(2):
            before = get(app_url, '/app-info')
            (directory / 'index.html').write_text('updated interface ' + str(index))
            (directory / 'app_server.py').write_text((SOURCE / 'app_server.py').read_text().replace("'pid': os.getpid()", "'pid': os.getpid(), 'build_marker': " + repr(str(index))))
            assert request(app_url, '/reload-app', b'', app_url)[0] == 200
            wait_for(lambda: get(app_url, '/app-info')['generation'] != before['generation'])
            assert get(app_url, '/app-info')['build_marker'] == str(index)
            current = get(app_url, '/status')
            assert current['recording'] and not current['error']
            assert current['file'] == initial['file'] and current['samples'] > initial['samples']
            assert audio.stat().st_ino == inode
            assert request(app_url, '/')[1] == ('updated interface ' + str(index)).encode()
        valid_source = (directory / 'app_server.py').read_text()
        (directory / 'app_server.py').write_text('def invalid(')
        generation = get(app_url, '/app-info')['generation']
        assert request(app_url, '/reload-app', b'')[0] == 400
        assert get(app_url, '/app-info')['generation'] == generation
        (directory / 'app_server.py').write_text(valid_source)
        process.terminate()
        process.wait(timeout=5)
        assert get(engine_url, '/status')['recording']
        launch()
        current = get(app_url, '/status')
        assert current['recording'] and current['file'] == initial['file']
        assert request(app_url, '/stop', b'{}')[0] == 200
        assert not get(app_url, '/status')['recording']
        with wave.open(str(audio)) as wav:
            assert wav.getparams()[:3] == (1, 2, 16000)
            assert wav.getnframes() == recording.state['samples']
            pcm = wav.readframes(wav.getnframes())
            assert len(pcm) == wav.getnframes() * 2
            assert pcm == (321).to_bytes(2, 'little', signed=True) * wav.getnframes()
        assert submitted == [initial['file']], submitted
        assert request(app_url, '/recordings/' + initial['file'])[1] == audio.read_bytes()
        print('PASS: two code/interface reloads and application server termination/restart preserve one recording')
        print('PASS: Stop finalizes valid mono 16-bit 16000 Hz WAV; all samples preserved; auto transcription submitted once')
        print('PASS: audio download, settings proxy, active-file guard, duplicate Start and Origin/input validation')
    finally:
        recording.stop_recording.set()
        if recording.worker:
            recording.worker.join(5)
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            if process.returncode not in (0, -15):
                print(process.stderr.read().decode(), file=sys.stderr)
        engine.shutdown()
        engine.server_close()
