import hashlib
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
from urllib.request import Request, urlopen

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
import audio_enhance
import app_server
import study_store
from speech_audio import enhance_audio

NAME = 'lecture-2026-11-17-10-00-00-123456.wav'


def rms(audio):
    return np.sqrt(np.mean(audio ** 2))


def write_audio(path, samples):
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'none'))
        audio.writeframes((np.clip(samples, -1, 1) * 32767).round().astype('<i2').tobytes())


class SignalTests(unittest.TestCase):
    def fixture(self):
        t = np.arange(8 * 16000) / 16000
        speech = np.zeros(len(t))
        speech[16000:48000] = .035 * np.sin(2 * np.pi * 520 * t[16000:48000])
        speech[64000:112000] = .25 * np.sin(2 * np.pi * 520 * t[64000:112000])
        noise = np.random.default_rng(83).normal(0, .008, len(t)) + .025 * np.sin(2 * np.pi * 50 * t)
        return speech + noise

    def test_background_hum_is_reduced_without_shortening_audio(self):
        audio = self.fixture()
        before = audio.copy()
        result = enhance_audio(audio, [(1, 3), (4, 7)], level=False)
        reduction = 20 * np.log10(rms(audio[:8000]) / rms(result[:8000]))
        self.assertGreater(reduction, 8)
        self.assertEqual(len(result), len(audio))
        np.testing.assert_array_equal(before, audio)

    def test_speakers_at_different_volume_become_closer_without_clipping(self):
        result = enhance_audio(self.fixture(), [(1, 3), (4, 7)])
        ratio = rms(result[80000:96000]) / rms(result[24000:40000])
        self.assertGreater(ratio, .7)
        self.assertLess(ratio, 1.5)
        self.assertLessEqual(np.max(np.abs(result)), .960001)

    def test_continuous_speech_is_not_used_as_a_noise_profile(self):
        t = np.arange(3 * 16000) / 16000
        audio = .1 * np.sin(2 * np.pi * 520 * t)
        result = enhance_audio(audio, [(0, 3)], level=False)
        self.assertGreater(rms(result[16000:32000]) / rms(audio[16000:32000]), .98)

    def test_spectrum_is_computed_only_with_enough_background_frames(self):
        from scipy.signal import stft
        samples = np.random.default_rng(9).normal(0, .02, 16003)
        times = stft(samples, fs=16000, nperseg=512, noverlap=384)[1]
        for count in (24, 25):
            boundary = times[times < len(samples) / 16000 - .032][-count] - .004
            for level in (True, False):
                with self.subTest(count=count, level=level), patch('scipy.signal.stft', wraps=stft) as transform:
                    result = enhance_audio(samples, [(0, boundary - .16)], level=level)
                    self.assertEqual(transform.call_count, int(count >= 25))
                    self.assertEqual(len(result), len(samples))
                    self.assertTrue(np.isfinite(result).all())

    def test_strong_profile_is_bounded_and_reduces_more_noise(self):
        audio = self.fixture()
        gentle = enhance_audio(audio, [(1, 3), (4, 7)], level=False)
        strong = enhance_audio(audio, [(1, 3), (4, 7)], profile='strong', level=False)
        self.assertLessEqual(rms(strong[:8000]), rms(gentle[:8000]))
        self.assertGreater(rms(strong[80000:96000]), .14)

    def test_empty_short_silent_and_nonfinite_samples_are_safe(self):
        for audio in (np.array([]), np.zeros(12000), np.array([np.nan, np.inf, -np.inf]), np.zeros(73)):
            result = enhance_audio(audio, [])
            self.assertEqual(len(result), len(audio))
            self.assertTrue(np.all(np.isfinite(result)))
            self.assertFalse(np.any(result))
        with self.assertRaises(ValueError):
            enhance_audio(np.zeros((2, 12000)), [])
        with self.assertRaises(ValueError):
            enhance_audio(np.zeros(12000), [], profile='unknown')


class FileTests(unittest.TestCase):
    def test_long_recording_preserves_every_frame_and_original(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, target, info = [folder / name for name in ('original.wav', 'clean.wav', 'info.json')]
            samples = .03 * np.sin(np.arange(61 * 16000 + 73) * .13)
            write_audio(source, samples)
            original = source.read_bytes()
            with patch('speech_gate.strict_speech_ranges', return_value=[(0, 34)]):
                audio_enhance.render(source, target, info, 'gentle')
            self.assertEqual(source.read_bytes(), original)
            with wave.open(str(target)) as audio:
                self.assertEqual(audio.getnframes(), len(samples))
                data = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2') / 32768
                self.assertLess(max(abs(data[30 * 16000] - data[30 * 16000 - 1]), abs(data[60 * 16000] - data[60 * 16000 - 1])), .04)
            meta = json.loads(info.read_text())
            self.assertEqual(meta['source_sha256'], hashlib.sha256(original).hexdigest())
            self.assertTrue(meta['timeline_preserved'])

    def test_changed_source_is_not_committed_as_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, target, info = [folder / name for name in ('original.wav', 'clean.wav', 'info.json')]
            write_audio(source, np.zeros(16000))
            with patch('speech_gate.strict_speech_ranges', return_value=[]), patch('audio_enhance.signature', side_effect=[{'size': 1}, {'size': 2}]):
                with self.assertRaises(ValueError):
                    audio_enhance.render(source, target, info, 'gentle')
            self.assertFalse(target.exists())
            self.assertFalse(info.exists())
            self.assertFalse(list(folder.glob('*.tmp')))

    def test_invalid_paths_and_profiles_are_rejected(self):
        for name, profile in (('../x.wav', 'gentle'), ('x\\y.wav', 'gentle'), ('/x.wav', 'gentle'), ('x.wav', 'other')):
            with self.assertRaises(ValueError):
                audio_enhance.key(name, profile)


class Backend(BaseHTTPRequestHandler):
    recording = False
    def log_message(self, *_):
        pass
    def do_GET(self):
        body = json.dumps({'recording': self.recording, 'file': NAME}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Pairing:
    def __init__(self, *_):
        pass
    def close(self):
        pass
    def public(self):
        return {'active': False}


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'outputs/recorder'
        (self.root / 'recordings').mkdir(parents=True)
        write_audio(self.root / 'recordings' / NAME, np.zeros(8000))
        self.patches = [patch('app_server.ROOT', self.root), patch('study_store.ROOT', self.root), patch('app_server.Pairing', Pairing)]
        for item in self.patches:
            item.start()
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        Backend.recording = False
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.server = app_server.ApplicationServer(('127.0.0.1', 0), f'http://127.0.0.1:{self.backend.server_port}')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.backend.shutdown()
        self.backend.server_close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def request(self, path, value=None, **kwargs):
        if value is not None:
            kwargs.update(data=json.dumps(value).encode(), headers={'Content-Type': 'application/json'})
        return urlopen(Request(self.base + path, **kwargs), timeout=10)

    def ready(self):
        target, info, _ = self.server.enhancer._paths(NAME, 'gentle')
        target.write_bytes((self.root / 'recordings' / NAME).read_bytes())
        audio_enhance.atomic(info, {'source': audio_enhance.signature(self.root / 'recordings' / NAME), 'output': audio_enhance.signature(target), 'engine': audio_enhance.ENHANCEMENT, 'seconds': .5})
        return target.read_bytes()

    def test_playback_range_head_and_cache_invalidation(self):
        payload = self.ready()
        path = '/enhanced-audio/' + NAME
        with self.request(path, headers={'Range': 'bytes=44-63'}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), payload[44:64])
        with self.request(path, method='HEAD') as response:
            self.assertEqual(int(response.headers['Content-Length']), len(payload))
            self.assertEqual(response.read(), b'')
        (self.root / 'recordings' / NAME).touch()
        with self.assertRaises(HTTPError) as error:
            self.request(path)
        self.assertEqual(error.exception.code, 400)

    def test_recording_cannot_be_processed_until_stopped(self):
        Backend.recording = True
        with self.assertRaises(HTTPError) as error:
            self.request('/audio-enhancement', {'file': NAME})
        self.assertEqual(error.exception.code, 409)
        self.assertFalse(self.server.enhancer.active())

    def test_damaged_processed_file_is_not_served_as_ready(self):
        self.ready()
        target = self.server.enhancer.audio(NAME)
        target.write_bytes(b'broken')
        self.assertEqual(self.server.enhancer.status(NAME)['status'], 'idle')
        with self.assertRaises(ValueError):
            self.server.enhancer.audio(NAME)

    def test_reload_waits_for_audio_processing(self):
        with patch.object(self.server.enhancer, 'active', return_value=True):
            with self.assertRaises(HTTPError) as error:
                self.request('/reload-app', {})
        self.assertEqual(error.exception.code, 409)

    def test_missing_components_give_retryable_error_without_losing_source(self):
        before = (self.root / 'recordings' / NAME).read_bytes()
        with self.request('/audio-enhancement', {'file': NAME}) as response:
            self.assertEqual(response.status, 202)
        deadline = time.monotonic() + 5
        while self.server.enhancer.active() and time.monotonic() < deadline:
            time.sleep(.02)
        with self.request('/audio-enhancement?file=' + NAME) as response:
            value = json.load(response)
        self.assertEqual(value['status'], 'error')
        self.assertIn('установку', value['message'])
        self.assertEqual((self.root / 'recordings' / NAME).read_bytes(), before)

    def test_bad_profile_and_cross_origin_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/audio-enhancement', {'file': NAME, 'profile': 'unknown'})
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.request('/audio-enhancement', data=b'{}', headers={'Origin': 'https://example.org'})
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
