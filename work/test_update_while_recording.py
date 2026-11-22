"""Проверка штатных /start, /status и запрета остановки при локальном обновлении."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]


def record(directory):
    sys.path.insert(0, str(directory / 'outputs/recorder'))
    # Стенд подаёт кадры через объект USB-потока. Реальные порты не нужны.
    serial = ModuleType('serial')
    tools = ModuleType('serial.tools')
    tools.list_ports = ModuleType('serial.tools.list_ports')
    tools.list_ports.comports = lambda: []
    with patch.dict(sys.modules, {'serial': serial, 'serial.tools': tools}):
        import recorder
    import update_manager

    pcm = bytes(range(256)) * 2
    packet = b'PCM1' + len(pcm).to_bytes(2, 'little') + pcm
    class Stream:
        data = b''
        def write(self, data): pass
        def readline(self): return b'STREAM 16000\n'
        def close(self): pass
        def read(self, count):
            if not self.data:
                time.sleep(.005)
                self.data = packet
            value, self.data = self.data[:count], self.data[count:]
            return value

    server = ThreadingHTTPServer(('127.0.0.1', 0), recorder.Handler)
    url = f'http://127.0.0.1:{server.server_port}'
    def post(path):
        with urlopen(Request(url + path, data=b'{}'), timeout=3) as response:
            return json.load(response)
    def status():
        with urlopen(url + '/status', timeout=3) as response:
            return json.load(response)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with patch.object(recorder, 'open_recording_stream', return_value=Stream()):
            assert post('/start')['ok']
            for _ in range(100):
                state = status()
                if state['samples'] >= 512:
                    break
                time.sleep(.02)
            assert state['recording'] and state['samples'] >= 512
            assert not update_manager.idle(url)
            try:
                post('/shutdown-for-update')
            except HTTPError as error:
                assert error.code == 409
                error.close()
            else:
                raise AssertionError('Сервис разрешил обновление во время записи')
            assert post('/stop')['ok'] and update_manager.idle(url)
            with wave.open(str(recorder.FILES / state['file'])) as audio:
                frames = audio.getnframes()
                data = audio.readframes(frames)
            assert frames >= 512 and data == pcm * (len(data) // len(pcm))
            assert post('/shutdown-for-update')['ok']
            return dict(recording_shutdown=409, stopped_shutdown=200, frames=frames,
                        pcm_sha256=hashlib.sha256(data).hexdigest())
    finally:
        recorder.stop_recording.set()
        server.shutdown()
        server.server_close()
        worker.join()


class RecordingUpdate(unittest.TestCase):
    def test_update_waits_for_persisted_pcm(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'work').mkdir()
            (root / 'work/ai-settings.json').write_text('{"auto":false}')
            destination = root / 'outputs/recorder'
            destination.mkdir(parents=True)
            for source in (SOURCE / 'outputs/recorder').glob('*.py'):
                shutil.copyfile(source, destination / source.name)
            shutil.copyfile(SOURCE / 'outputs/recorder/schedule.example.json', destination / 'schedule.example.json')
            shutil.copyfile(SOURCE / 'release.json', root / 'release.json')
            response = subprocess.run([sys.executable, '-B', __file__, '--isolated', name],
                                      capture_output=True, text=True, timeout=20)
            self.assertEqual(response.returncode, 0, response.stderr)
            measurement = json.loads(response.stdout)
            self.assertEqual(measurement['recording_shutdown'], 409)
            print(json.dumps(measurement))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--isolated':
        print(json.dumps(record(Path(sys.argv[2]))))
    else:
        unittest.main()
