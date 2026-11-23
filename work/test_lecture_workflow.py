import io
import json
import sys
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path('outputs/recorder').resolve()))
import audio_import
import transcript_quality
from media_stream import serve_audio
import app_server
import study_store

NAME = 'lecture-2026-10-20-10-00-00-123456.wav'

def wav_bytes(rate=16000, channels=1, frames=1600):
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x01\x00' * frames * channels)
    return data.getvalue()


def wait(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError('Превышено время ожидания')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'outputs/recorder'
        self.ready = []
        self.importer = audio_import.Importer(self.root, self.ready.append)
    def tearDown(self):
        self.importer.close()
        self.importer.worker.join(20)
        self.temp.cleanup()
    def receive(self, payload=None, name='Пара.wav', **metadata):
        payload = payload if payload is not None else wav_bytes()
        return self.importer.receive(io.BytesIO(payload), len(payload), name, metadata)
    def completed(self):
        return wait(lambda: next((j for j in self.importer.list() if j['status'] in ('ready', 'error')), None))
    def test_original_preserved_and_normalized_audio_committed(self):
        raw = wav_bytes()
        job = self.receive(raw, subject='Математический анализ')
        self.assertEqual(self.completed()['status'], 'ready')
        original = next(self.importer.originals.glob('*.wav'))
        self.assertEqual(original.read_bytes(), raw)
        self.assertAlmostEqual(audio_import.validate(self.root / 'recordings' / job['file']), .1)
        self.assertEqual(len(self.ready), 1)
    def test_duplicate_upload_has_one_library_record(self):
        first = self.receive(title='Пределы')
        self.completed()
        second = self.receive(title='Пределы')
        self.assertEqual(first['id'], second['id'])
        self.assertTrue(second['duplicate'])
        self.assertEqual(len(list((self.root / 'recordings').glob('*.wav'))), 1)
    def test_interrupted_upload_never_commits(self):
        with self.assertRaises(ValueError):
            self.importer.receive(io.BytesIO(b'broken'), 100, 'Пара.wav', {})
        self.assertEqual(list(self.importer.originals.iterdir()), [])
        self.assertEqual(self.importer.list(), [])
    def test_invalid_names_and_empty_files_rejected(self):
        for name in ('../x.wav', 'x\n.wav', 'x.exe'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.receive(name=name)
        with self.assertRaises(ValueError):
            self.receive(b'')
    def test_corrupted_audio_is_error_and_original_survives(self):
        self.receive(b'not audio')
        self.assertEqual(self.completed()['status'], 'error')
        self.assertEqual(len(list(self.importer.originals.iterdir())), 1)
        self.assertEqual(list((self.root / 'recordings').glob('*.wav')), [])
    @unittest.skipUnless(Path('/usr/bin/afconvert').exists(), 'Нужен CoreAudio Mac')
    def test_stereo_48khz_conversion_preserves_duration(self):
        job = self.receive(wav_bytes(48000, 2, 48000), name='Стерео.wav')
        self.assertEqual(self.completed()['status'], 'ready')
        self.assertAlmostEqual(audio_import.validate(self.root / 'recordings' / job['file']), 1, places=2)
    @unittest.skipUnless(Path('/usr/bin/afconvert').exists(), 'Нужен CoreAudio Mac')
    def test_stereo_right_channel_is_not_lost(self):
        data = io.BytesIO()
        with wave.open(data, 'wb') as audio:
            audio.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            audio.writeframes((b'\x00\x00' + (12000).to_bytes(2, 'little', signed=True)) * 48000)
        job = self.receive(data.getvalue(), name='Правый канал.wav')
        self.assertEqual(self.completed()['status'], 'ready')
        import array
        with wave.open(str(self.root / 'recordings' / job['file'])) as audio:
            samples = array.array('h', audio.readframes(audio.getnframes()))
        self.assertGreater(sum(abs(v) for v in samples) / len(samples), 4000)
    def test_truncated_pcm_header_is_not_accepted(self):
        self.receive(wav_bytes()[:-20])
        self.assertEqual(self.completed()['status'], 'error')
    def test_scheduling_error_retries_without_rewriting_audio(self):
        def fail(job):
            raise RuntimeError('Связь с обработкой прервалась')
        self.importer.on_ready = fail
        job = self.receive()
        self.assertEqual(self.completed()['status'], 'error')
        target = self.root / 'recordings' / job['file']
        before = target.stat().st_mtime_ns
        self.importer.on_ready = self.ready.append
        self.importer.retry(job['id'])
        self.assertEqual(self.completed()['status'], 'ready')
        self.assertEqual(target.stat().st_mtime_ns, before)


class QualityTests(unittest.TestCase):
    def test_uncertain_and_missing_assessment_are_distinct(self):
        value = transcript_quality.annotate({'segments': [
            {'id': 1, 'start': 0, 'end': 2, 'text': 'Предел', 'avg_logprob': -.9},
            {'id': 2, 'start': 2, 'end': 4, 'text': 'Последовательность'}]})
        self.assertEqual(value['quality']['pending'], 1)
        self.assertEqual(value['quality']['unassessed'], 1)
        self.assertFalse(value['segments'][1]['needs_review'])
    def test_review_invalidated_after_text_change(self):
        source = {'segments': [{'id': 0, 'start': 0, 'end': 2, 'text': 'Придел', 'needs_review': True}]}
        key = transcript_quality.annotate(source)['segments'][0]['review_key']
        decisions = {key: {'reviewed': True}}
        self.assertEqual(transcript_quality.annotate(source, decisions)['quality']['pending'], 0)
        source['segments'][0]['text'] = 'Предел'
        self.assertEqual(transcript_quality.annotate(source, decisions)['quality']['pending'], 1)
    def test_complete_text_restores_legacy_asides_without_duplicates(self):
        opening = {'id': 0, 'start': 0, 'end': 3, 'text': 'Сегодня разбираем производную.'}
        body = {'id': 1, 'start': 3, 'end': 6, 'text': 'Производная показывает скорость изменения.'}
        value = transcript_quality.annotate({'segments': [body], 'excluded_asides': [opening]})
        self.assertEqual(value['segments'][0]['text'], opening['text'])
        self.assertEqual(len(transcript_quality.annotate(value)['segments']), 2)
        self.assertIn(opening['text'], transcript_quality.markdown(value))
    def test_legacy_text_without_time_is_preserved_without_invented_timing(self):
        value = transcript_quality.annotate({'segments': [{'text': 'Определение'}]})
        self.assertEqual(value['segments'][0]['text'], 'Определение')
        self.assertNotIn('start', value['segments'][0])
        self.assertIn('Без таймкода', transcript_quality.plain_text(value))
    def test_invalid_times_discarded_and_hour_export_kept(self):
        r = transcript_quality.annotate({'segments': [
            {'start': -1, 'end': 2, 'text': 'Некорректное'},
            {'start': float('nan'), 'end': 2, 'text': 'Некорректное'},
            {'start': 3661, 'end': 3664, 'text': 'Определение'}]})
        self.assertEqual(len(r['segments']), 1)
        self.assertIn('01:01:01', transcript_quality.plain_text(r))


class DummyPairing:
    def __init__(self, *_): pass
    def close(self): pass


class Backend(BaseHTTPRequestHandler):
    root = None
    requests = []
    reply = app_server.Handler.reply
    def log_message(self, *_): pass
    def do_GET(self):
        return serve_audio(self, self.root / 'recordings' / NAME)
    def do_HEAD(self):
        return self.do_GET()
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(body)
        self.send_response(200)
        data = b'{"ok":true}'
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'outputs/recorder'
        (self.root / 'recordings').mkdir(parents=True)
        (self.root / 'analysis').mkdir()
        self.payload = wav_bytes()
        (self.root / 'recordings' / NAME).write_bytes(self.payload)
        self.report = {'summary': ['Есть определение предела'], 'segments': [
            {'id': 0, 'start': 0, 'end': .1, 'text': 'Придел', 'needs_review': True}]}
        study_store.save(self.root / 'analysis' / (Path(NAME).stem + '.json'), self.report)
        self.patches = [patch('app_server.ROOT', self.root), patch('study_store.ROOT', self.root), patch('app_server.Pairing', DummyPairing)]
        for p in self.patches: p.start()
        Backend.root = self.root; Backend.requests = []
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.server = app_server.ApplicationServer(('127.0.0.1', 0), 'http://127.0.0.1:' + str(self.backend.server_port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.server.importer.worker.join(20)
        self.backend.shutdown(); self.backend.server_close()
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()
    def get(self, path, **kwargs):
        return urlopen(Request(self.base + path, **kwargs), timeout=20)
    def post(self, path, value):
        with self.get(path, data=json.dumps(value).encode(), headers={'Content-Type': 'application/json'}) as r:
            return json.load(r)
    def test_app_info_reports_installed_version_during_update(self):
        project = Path(self.temp.name)
        (project / 'release.json').write_text('{"version":"0.5.6"}')
        with patch('app_server.PROJECT', project), patch.dict(app_server.update_manager.STATE, version='0.5.7'):
            with self.get('/app-info') as response:
                info = json.load(response)
        self.assertEqual(info['version'], '0.5.6')
        self.assertEqual(info['updates']['version'], '0.5.7')

    def test_range_and_head_through_application_proxy(self):
        with self.get('/recordings/' + NAME, headers={'Range': 'bytes=44-63'}) as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers['Content-Range'], f'bytes 44-63/{len(self.payload)}')
            self.assertEqual(r.read(), self.payload[44:64])
        with self.get('/recordings/' + NAME, method='HEAD') as r:
            self.assertEqual(int(r.headers['Content-Length']), len(self.payload))
            self.assertEqual(r.read(), b'')
    def test_suffix_and_unsatisfiable_range(self):
        with self.get('/recordings/' + NAME, headers={'Range': 'bytes=-8'}) as r:
            self.assertEqual(r.read(), self.payload[-8:])
        with self.assertRaises(HTTPError) as caught:
            self.get('/recordings/' + NAME, headers={'Range': 'bytes=999999-'})
        self.assertEqual(caught.exception.code, 416)
        self.assertEqual(caught.exception.headers['Content-Range'], f'bytes */{len(self.payload)}')

    def test_fragment_contains_the_exact_stereo_frames(self):
        path = self.root / 'recordings' / NAME
        frames = bytes(range(200))
        with wave.open(str(path), 'wb') as output:
            output.setparams((2, 2, 1000, 0, 'NONE', 'not compressed'))
            output.writeframes(frames)
        before = path.read_bytes()
        route = '/recordings/' + NAME + '?start=0.009&end=0.021'
        with self.get(route) as response:
            payload = response.read()
            self.assertEqual(len(payload), int(response.headers['Content-Length']))
            self.assertIn('attachment', response.headers['Content-Disposition'])
        with wave.open(io.BytesIO(payload)) as clip:
            self.assertEqual((clip.getnchannels(), clip.getsampwidth(), clip.getframerate(), clip.getnframes()), (2, 2, 1000, 12))
            self.assertEqual(clip.readframes(12), frames[9 * 4:21 * 4])
        with self.get(route, method='HEAD') as response:
            self.assertEqual(response.read(), b'')
            self.assertEqual(int(response.headers['Content-Length']), len(payload))
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_fragment_never_returns_the_full_recording(self):
        for args in ('start=0', 'end=.01', 'start=0&end=', 'start=0&end=0', 'start=nan&end=.1',
                     'start=-1&end=.1', 'start=0&end=1', 'start=0&start=.01&end=.02'):
            with self.subTest(args=args), self.assertRaises(HTTPError) as caught:
                self.get('/recordings/' + NAME + '?' + args)
            self.assertEqual(caught.exception.code, 400)

    def test_fragment_preserves_unsigned_pcm_and_riff_padding(self):
        path = self.root / 'recordings' / NAME
        with wave.open(str(path), 'wb') as output:
            output.setparams((1, 1, 1000, 0, 'NONE', 'not compressed'))
            output.writeframes(bytes(range(10)))
        with self.get('/recordings/' + NAME + '?start=.003&end=.010') as response:
            payload = response.read()
        self.assertEqual(int.from_bytes(payload[4:8], 'little') + 8, len(payload))
        self.assertEqual(payload[44:], bytes(range(3, 10)) + b'\0')
        path.write_bytes(path.read_bytes()[:-4])
        with self.assertRaises(HTTPError) as caught:
            self.get('/recordings/' + NAME + '?start=0&end=.010')
        self.assertEqual(caught.exception.code, 422)
    def test_manual_review_is_persistent_and_stale_key_rejected(self):
        with self.get('/analysis/' + NAME) as r: report = json.load(r)
        key = report['segments'][0]['review_key']
        self.post('/transcript-review', {'file': NAME, 'key': key, 'reviewed': True})
        with self.get('/analysis/' + NAME) as r: self.assertTrue(json.load(r)['segments'][0]['reviewed'])
        self.report['segments'][0]['text'] = 'Предел'
        study_store.save(self.root / 'analysis' / (Path(NAME).stem + '.json'), self.report)
        with self.assertRaises(HTTPError) as caught:
            self.post('/transcript-review', {'file': NAME, 'key': key, 'reviewed': True})
        self.assertEqual(caught.exception.code, 409)
    def test_upload_reaches_library_and_queues_analysis(self):
        query = urlencode({'name': 'Пара.wav', 'title': 'Пределы', 'subject': 'Математический анализ', 'date': '2026-10-12'})
        with self.get('/import-audio?' + query, data=self.payload, headers={'Content-Type': 'application/octet-stream'}) as response:
            self.assertEqual(response.status, 202)
            job = json.load(response)
        done = wait(lambda: next((j for j in self.server.importer.list() if j['id'] == job['id'] and j['status'] in ('ready', 'error')), None))
        self.assertEqual(done['status'], 'ready')
        self.assertTrue((self.root / 'recordings' / job['file']).is_file())
        self.assertEqual(Backend.requests[0], {'file': job['file'], 'wait_models': True})
        meta = study_store.overrides()[job['file']]
        self.assertEqual(meta['date'], '2026-10-12')
        self.assertEqual(meta['title'], 'Пределы')
    def test_partial_transcript_available_before_summary(self):
        final = self.root / 'analysis' / (Path(NAME).stem + '.json')
        final.unlink()
        study_store.save(final.with_suffix('.transcript.json'), self.report)
        with self.get('/analysis/' + NAME) as response:
            value = json.load(response)
        self.assertTrue(value['draft'])
        self.assertEqual(value['quality']['pending'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
