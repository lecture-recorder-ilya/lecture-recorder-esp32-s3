import hashlib
import json
import selectors
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/recorder'))
from phone_sync import auth_headers, validate

NAME = 'lecture-2026-11-17-12-00-00-123456.wav'
KEY = 'local-ios-fixture'


class IOSProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        folder = Path(cls.build.name)
        harness = folder / 'Harness.swift'
        harness.write_text('''import Foundation
import Darwin
@main struct Harness {
 static func main() throws {
  let files = try PhoneFiles(root: URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true))
  let writer = try WaveWriter(files.folder("recordings").appendingPathComponent("''' + NAME + '''"))
  try writer.write(Data(repeating: 0, count: 64000)); try writer.finish()
  let server = PhoneSyncServer(files: files, key: "local-ios-fixture", port: 0, discoveryPort: 0)
  server.onReady = { port in print(port); fflush(stdout) }
  try server.start(); withExtendedLifetime(server) { dispatchMain() }
 }
}''')
        cls.binary = folder / 'ios-protocol'
        subprocess.run(['xcrun', 'swiftc', '-target', 'arm64-apple-macos14.0',
                        *[str(ROOT / 'outputs/ios/LectureRecorder' / file) for file in ('RecorderCore.swift', 'PhoneSyncServer.swift', 'MacConnection.swift')],
                        str(harness), '-o', str(cls.binary)], check=True, capture_output=True, text=True, timeout=90)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.process = subprocess.Popen([str(self.binary), self.temp.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        selector = selectors.DefaultSelector(); selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            if not selector.select(15):
                raise AssertionError('iOS-протокол не запустился')
            line = self.process.stdout.readline().strip()
            if not line.isdigit():
                raise AssertionError('Не получен порт iOS-протокола: ' + line)
            self.base = 'http://127.0.0.1:' + line
        finally:
            selector.close()

    def tearDown(self):
        self.process.terminate()
        self.process.communicate(timeout=10)
        self.temp.cleanup()

    def request(self, route, body=None, extra=None, headers=None):
        data = json.dumps(body).encode() if body is not None else b''
        method = 'POST' if body is not None else 'GET'
        signed = headers if headers is not None else auth_headers(KEY, method, route, data, extra)
        return urlopen(Request(self.base + route, data=data if body is not None else None, headers=signed, method=method), timeout=5)

    def test_wav_is_compatible_with_mac_import_and_list_hash(self):
        path = self.root / 'recordings' / NAME
        validate(path)
        with wave.open(str(path)) as audio:
            self.assertEqual(audio.getnframes(), 32000)
            self.assertEqual(audio.getframerate(), 16000)
        with self.request('/list') as response:
            files = json.load(response)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_range_transfer_matches_the_original_bytes(self):
        path = self.root / 'recordings' / NAME
        with self.request('/file/' + NAME, extra={'Range': 'bytes=500-'}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers['Content-Range'], 'bytes 500-64043/64044')
            self.assertEqual(response.read(), path.read_bytes()[500:])

    def test_replay_and_bad_signature_are_rejected(self):
        headers = auth_headers(KEY, 'GET', '/list')
        with self.request('/list', headers=headers) as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(HTTPError) as error:
            self.request('/list', headers=headers)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.request('/list', headers=auth_headers('wrong', 'GET', '/list'))
        self.assertEqual(error.exception.code, 403)

    def test_notes_round_trip_uses_exact_body_hash(self):
        note = {'file': NAME, 'report': {'summary': ['Определение'], 'segments': [{'start': .1, 'end': 1, 'text': 'Функция непрерывна.', 'needs_review': True}]}}
        with self.request('/notes', note) as response:
            result = json.load(response)
        digest = hashlib.sha256(json.dumps(note).encode()).hexdigest()
        self.assertEqual(result['sha256'], digest)
        with self.request('/notes-index') as response:
            self.assertEqual(json.load(response), {NAME: digest})

    def test_ack_keeps_audio_on_phone_and_wrong_hash_never_removes_it(self):
        path = self.root / 'recordings' / NAME
        original = path.read_bytes()
        with self.assertRaises(HTTPError):
            self.request('/ack', {'name': NAME, 'sha256': '0' * 64})
        self.assertEqual(path.read_bytes(), original)
        with self.request('/ack', {'name': NAME, 'sha256': hashlib.sha256(original).hexdigest()}) as response:
            self.assertTrue(json.load(response)['ok'])
        self.assertEqual((self.root / 'library' / NAME).read_bytes(), original)
        with self.request('/list') as response:
            self.assertEqual(json.load(response), [])

    def test_android_update_and_path_traversal_are_not_accepted(self):
        for route in ('/app-update', '/file/../secret'):
            with self.assertRaises(HTTPError) as error:
                self.request(route)
            self.assertIn(error.exception.code, (400, 404))

    def test_mac_import_downloads_verifies_and_acknowledges_the_recording(self):
        import phone_sync
        with self.request('/list') as response:
            item = json.load(response)[0]
        original = (self.root / 'recordings' / NAME).read_bytes()
        mac = self.root / 'mac'
        mac.mkdir()
        with patch('phone_sync.queue_pending'), patch('lesson_schedule.organize'):
            name = phone_sync.import_one(item, self.base, KEY, files=mac / 'recordings', ledger_path=mac / 'ledger.json')
        self.assertEqual(name, NAME)
        self.assertEqual((mac / 'recordings' / NAME).read_bytes(), original)
        self.assertEqual((self.root / 'library' / NAME).read_bytes(), original)
        self.assertEqual(json.loads((mac / 'ledger.json').read_text())[NAME]['sha256'], item['sha256'])


if __name__ == '__main__':
    unittest.main()
