import io
import json
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
import wave
import sys
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlsplit

WORK = Path(__file__).resolve().parent
UI = WORK.parent / 'outputs/recorder'
FILES = [f'lecture-2026-11-{day:02}-10-00-00.wav' for day in range(1, 11)]
LESSONS = {name: {'date': '2026-11-01', 'folder': 'Архив', 'subject': 'Алгебра',
                  'topic': f'Тема {i}', 'teacher': 'Пётр Волков' if i == 8 else 'Ирина',
                  'original_name': f'семинар-{i}.m4a', 'has_summary': i == 8} for i, name in enumerate(FILES[1:], 1)}
STATE = {'wifi': {}, 'files': FILES, 'recording': True, 'file': FILES[-1], 'lessons': LESSONS, 'ai': {'jobs': {}}}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, content, mime):
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', len(content))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == '/':
            html = (UI / 'index.html').read_text().replace('</html>', '<script src="/test.js"></script></html>')
            self.send(html.encode(), 'text/html; charset=utf-8')
        elif route == '/test.js':
            self.send((WORK / 'test_mac_library.js').read_bytes(), 'text/javascript')
        elif route.startswith('/analysis/'):
            self.send(json.dumps({'subject': 'Алгебра', 'overview': 'Линейные отображения.',
                                  'summary': ['Пример из записи'], 'segments': [
                                      {'id': 0, 'start': 0.5, 'end': 2, 'text': 'Длина вектора.'},
                                      {'id': 1, 'start': 4, 'end': 9, 'text': 'Координаты в базисе.'}]}).encode(), 'application/json')
        elif route.startswith('/recordings/'):
            out = io.BytesIO()
            with wave.open(out, 'wb') as wav:
                wav.setparams((1, 2, 8000, 0, 'NONE', ''))
                wav.writeframes(bytes(12 * 8000 * 2))
            self.send(out.getvalue(), 'audio/wav')
        elif (UI / route.lstrip('/')).is_file():
            super().do_GET()
        else:
            data = {'/status': STATE, '/calendar': {'entries': [], 'group': ''},
                    '/imports': {'jobs': []}, '/mirea-profile': {'configured': True}}.get(route, {})
            if 'phase=entry' in self.headers.get('Referer', ''):
                job = getattr(self.server, 'imported', None)
                if route == '/mirea-profile':
                    data = {'configured': False, 'group': ''}
                elif route == '/imports':
                    data = {'jobs': [job] if job else []}
                elif route == '/status':
                    name = job['file'] if job else ''
                    data = {'wifi': {}, 'files': [name] if job else [], 'recording': False, 'usb_present': False,
                            'lessons': {name: {'title': job['title'], 'has_summary': True,
                                               'date': datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()}} if job else {},
                            'ai': {'ready': True, 'jobs': {}}}
            self.send(json.dumps(data).encode(), 'application/json')

    def do_POST(self):
        route = urlsplit(self.path)
        if route.path != '/import-audio':
            return self.send_error(404)
        query = parse_qs(route.query)
        original = query['name'][0]
        payload = self.rfile.read(int(self.headers['Content-Length']))
        if original != 'Свет.m4a' or payload != b'test-audio' or query['analyze'] != ['1']:
            return self.send_error(400)
        job = {'id': 'a' * 32, 'file': 'lecture-2026-11-24-14-00-00.wav', 'name': original,
               'title': query['title'][0], 'status': 'ready', 'analyze': True}
        self.server.imported = job
        self.send(json.dumps(job).encode(), 'application/json')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI, **kwargs)


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swift'), 'Нужен WebKit на macOS')
class LibraryTests(unittest.TestCase):
    def test_library_and_player(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run(['swift', WORK.parent / 'tests/mac_library_webkit.swift',
                                         f'http://127.0.0.1:{server.server_port}'],
                                        text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                server.shutdown()
                thread.join()


if __name__ == '__main__':
    unittest.main()
