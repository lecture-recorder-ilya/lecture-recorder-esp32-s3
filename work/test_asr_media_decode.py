import io
import json
import shutil
import sys
import tempfile
import unittest
import wave
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from audio_import import normalize
from media_decode import decode


class MediaDecodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.wav'
        self.target = self.root / 'result.wav'
        with wave.open(str(self.source), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x11\x01' * 3200)

    def test_ready_pcm_does_not_launch_any_converter(self):
        with patch('audio_import.subprocess.run', side_effect=AssertionError('Unexpected conversion')):
            normalize(self.source, self.target, self.root)
        self.assertEqual(self.source.read_bytes(), self.target.read_bytes())

    def test_fallback_runs_only_after_existing_converters_fail(self):
        project = self.root / 'project'
        decoder = project / 'outputs/recorder/media_decode.py'
        decoder.parent.mkdir(parents=True)
        decoder.touch()
        python = project / 'work/asr-env/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        source = self.root / 'compressed.mp4'
        source.write_bytes(b'conversion dispatch fixture')
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if str(decoder) in command:
                shutil.copyfile(self.source, self.target)
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=1)

        with patch('audio_import.shutil.which', return_value='/fixture/ffmpeg'):
            self.assertEqual(normalize(source, self.target, project, run=run), .2)
        self.assertEqual(calls[0][0], '/fixture/ffmpeg')
        self.assertEqual(calls[-1], [str(python), str(decoder), str(source), str(self.target)])
        self.assertEqual(source.read_bytes(), b'conversion dispatch fixture')

    def test_successful_converter_does_not_use_fallback(self):
        project = self.root / 'project'
        (project / 'outputs/recorder').mkdir(parents=True)
        (project / 'outputs/recorder/media_decode.py').touch()
        (project / 'work/asr-env/bin').mkdir(parents=True)
        (project / 'work/asr-env/bin/python').symlink_to(sys.executable)
        source = self.root / 'compressed.mp4'
        source.write_bytes(b'conversion dispatch fixture')
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            shutil.copyfile(self.source, self.target)
            return SimpleNamespace(returncode=0)

        with patch('audio_import.shutil.which', return_value='/fixture/ffmpeg'):
            normalize(source, self.target, project, run=run)
        self.assertEqual(len(calls), 1)

    def test_decoder_keeps_pcm_samples_and_rejects_same_path(self):
        before = self.source.read_bytes()
        self.assertEqual(decode(self.source, self.target), .2)
        self.assertEqual(self.target.read_bytes(), before)
        with self.assertRaises(ValueError):
            decode(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), before)

    def test_limit_failure_keeps_existing_output_and_cleans_temporary_file(self):
        self.target.write_bytes(b'previous result')
        with self.assertRaises(ValueError):
            decode(self.source, self.target, max_seconds=.1)
        self.assertEqual(self.target.read_bytes(), b'previous result')
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_bad_media_keeps_existing_output_and_cleans_temporary_file(self):
        self.source.write_bytes(b'invalid media fixture')
        self.target.write_bytes(b'previous result')
        with self.assertRaises(Exception):
            decode(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'previous result')
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_resampler_flushes_tail(self):
        with wave.open(str(self.source), 'wb') as wav:
            wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x11\x01' * 5111)
        decode(self.source, self.target)
        with wave.open(str(self.target)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
            self.assertLessEqual(abs(wav.getnframes() - 5111 * 16000 / 44100), 1)

    def test_audio_timestamp_gap_remains_silence(self):
        import av
        import numpy as np
        source = self.root / 'gap.nut'
        with av.open(str(source), mode='w', format='nut') as container:
            stream = container.add_stream('pcm_s16le', rate=16000)
            stream.layout = 'mono'
            for pts, value in [(0, 273), (3200, 546)]:
                frame = av.AudioFrame.from_ndarray(np.full((1, 1600), value, dtype=np.int16), format='s16', layout='mono')
                frame.sample_rate, frame.time_base, frame.pts = 16000, Fraction(1, 16000), pts
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        decode(source, self.target)
        with wave.open(str(self.target)) as wav:
            data = wav.readframes(wav.getnframes())
        self.assertEqual(data, b'\x11\x01' * 1600 + bytes(3200) + b'\x22\x02' * 1600)


if __name__ == '__main__':
    unittest.main()
