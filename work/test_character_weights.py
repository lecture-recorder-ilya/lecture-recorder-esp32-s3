import hashlib
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

import numpy
import onnxruntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/recorder'))
sys.path.insert(0, str(ROOT / 'tools'))
import character_weights as weights
import quality_asr
import qwen_transcribe
from speech_gate import SpeechProfile


class CharacterWeights(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / 'work/models/gigaam-beam'
        self.folder.mkdir(parents=True)
        self.fast = self.folder / weights.FILENAME
        self.original_digest, self.original_size = weights.SHA256, weights.SIZE
        self.content = b'compact fixture'
        paths = {'CHAR': self.folder, 'MODEL': self.folder.parent / 'gigaam',
                 'RNNT': self.folder.parent / 'gigaam-rnnt', 'PROJECT': self.root}
        for item in [patch.multiple(quality_asr, **paths),
                     patch.multiple(weights, SIZE=len(self.content), SHA256=hashlib.sha256(self.content).hexdigest())]:
            item.start()
            self.addCleanup(item.stop)

    def test_catalog_keeps_two_precisions_and_pins_actual_checksum(self):
        catalog = json.loads((ROOT / 'installer/models.json').read_text())
        spec = next(model for model in catalog if model['folder'] == 'gigaam-beam')
        files = {item['name']: item for item in spec['files']}
        self.assertIn('v3_ctc.onnx', files)
        self.assertEqual(spec['revision'], weights.REVISION)
        self.assertEqual(files[weights.FILENAME]['sha256'], self.original_digest)
        self.assertEqual(files[weights.FILENAME]['bytes'], self.original_size)

    def test_existing_offline_models_stay_ready_during_partial_download(self):
        for spec in json.loads((ROOT / 'installer/models.json').read_text()):
            if spec['folder'] not in ('gigaam', 'gigaam-rnnt', 'gigaam-beam'):
                continue
            folder = self.folder.parent / spec['folder']
            folder.mkdir(exist_ok=True)
            for item in spec['files']:
                if item['name'] != weights.FILENAME:
                    (folder / item['name']).touch()
            (folder.parent / (folder.name + '-manifest.json')).write_text('{}')
        part = self.fast.with_suffix('.onnx.download')
        part.write_bytes(self.content)
        with patch.object(weights.hashlib, 'file_digest', wraps=hashlib.file_digest) as digest:
            self.assertTrue(quality_asr.ready())
            self.assertFalse(quality_asr.Decoder().fast_character)
            digest.assert_not_called()
            part.replace(self.fast)
            self.assertTrue(quality_asr.Decoder().fast_character)
            for _ in range(5):
                self.assertTrue(quality_asr.ready())
                self.assertTrue(quality_asr.Decoder().fast_character)
            self.assertEqual(digest.call_count, 1)
            part.write_bytes(b'x' * len(self.content))
            part.replace(self.fast)
            self.assertFalse(quality_asr.Decoder().fast_character)
            self.assertEqual(digest.call_count, 2)
            self.fast.write_bytes(b'partial')
            self.assertFalse(weights.available(self.folder))
            self.assertEqual(digest.call_count, 2)

    def test_fast_alias_uses_full_model_once_when_missing(self):
        factory = Mock()
        with patch.dict(sys.modules, onnx_asr=factory):
            decoder = quality_asr.Decoder()
            self.assertIs(decoder._load('char_fast'), decoder._load('char'))
            self.assertEqual(factory.load_model.call_count, 1)
            self.assertIsNone(factory.load_model.call_args.kwargs['quantization'])
            self.fast.write_bytes(self.content)
            decoder = quality_asr.Decoder()
            decoder._load('char_fast')
            self.assertEqual(factory.load_model.call_args.args, ('gigaam-v3-ctc',))
            self.assertEqual(factory.load_model.call_args.kwargs['quantization'], 'int8')
            decoder._load('char')
            self.assertIsNone(factory.load_model.call_args.kwargs['quantization'])

    def test_report_uses_decoder_identity_and_accepts_the_old_interface(self):
        from evaluate_asr import evaluate
        wave_path = self.root / 'clip.wav'
        with wave.open(str(wave_path), 'wb') as clip:
            clip.setparams((1, 2, 16000, 0, 'NONE', 'uncompressed'))
            clip.writeframes(bytes(64000))
        manifest = self.root / 'checks.json'
        manifest.write_text(json.dumps([{'id': 'clip', 'audio': 'clip.wav', 'reference': ''}]))
        old = SimpleNamespace(transcribe=lambda *_args, **_kwargs: '', last={}, close=lambda: None)
        with patch.dict(sys.modules, quality_asr=SimpleNamespace(Decoder=lambda: old, ENGINE='legacy')):
            self.assertEqual(evaluate(manifest, ROOT)['engine'], 'legacy')
            old.engine = 'installed-set'
            self.assertEqual(evaluate(manifest, ROOT)['engine'], 'installed-set')
            def replace_model(*args, **kwargs):
                old.engine = 'changed-set'
                return ''
            old.transcribe = replace_model
            with self.assertRaisesRegex(RuntimeError, 'Набор моделей'):
                evaluate(manifest, ROOT)

    def test_external_replacement_restarts_the_saved_transcript_in_full_precision(self):
        audio = self.root / 'lecture.wav'
        with wave.open(str(audio), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(bytes(32000))
        self.fast.write_bytes(self.content)
        calls = []

        def transcribe(decoder, *_args, **_kwargs):
            calls.append(decoder.fast_character)
            if decoder.fast_character:
                self.fast.unlink()
                decoder._load('char_fast')
            return 'Запись.'

        report, progress = self.root / 'result.json', self.root / 'progress.json'
        profile = SpeechProfile([(0, 1)], [(0, 1)], [(0, 1)])
        with patch.dict(sys.modules, onnx_asr=Mock()), patch('speech_gate.speech_profile', return_value=profile), \
             patch.object(quality_asr.Decoder, 'transcribe', transcribe):
            qwen_transcribe.run(audio, report, progress)
            self.assertEqual(calls, [True, False])
            cache = report.with_suffix('.transcript.json')
            self.assertEqual(json.loads(cache.read_text())['engine'], quality_asr.BASE_ENGINE)
            self.assertEqual(json.loads(progress.read_text())['transcript_engine'], quality_asr.BASE_ENGINE)
            self.fast.write_bytes(self.content)
            with patch.object(quality_asr.Decoder, 'transcribe', return_value='Другая запись.'):
                qwen_transcribe.run(audio, report, progress)
            self.assertEqual(json.loads(cache.read_text())['engine'], quality_asr.engine_for(True))
            self.assertEqual(len(list(self.root.glob('*.before-quality-*.json'))), 1)
            progress.unlink()
            with patch.object(quality_asr.Decoder, 'transcribe', side_effect=AssertionError('Повторный проход')):
                qwen_transcribe.run(audio, report, progress)
            self.assertEqual(json.loads(progress.read_text())['transcript_engine'], quality_asr.engine_for(True))


if __name__ == '__main__':
    unittest.main()
