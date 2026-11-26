import json
import os
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from voice_focus import VoiceFocus, focus_frames, mask_intervals, reference_frames, stamp, write_reference


class VoiceFocusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.source = self.folder / 'original.wav'
        with wave.open(str(self.source), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x2a\x01' * 64000)

    def test_reference_is_bounded(self):
        for selection in ((True,4), (float('nan'),4), (-1,3), (1,5), (0,2.9)):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                reference_frames(*selection, 64000)
        cut = self.folder / 'sample.wav'
        write_reference(self.source, cut, reference_frames(.25, 3.5, 64000))
        with wave.open(str(cut)) as sample:
            self.assertEqual(sample.getnframes(), 52000)

    def test_unknown_windows_keep_positions_and_are_silent_for_asr(self):
        masked = self.folder / 'recognize.wav'
        mask_intervals(self.source, masked, [{'start':.25,'end':1.5}, {'start':2,'end':3.125}])
        with wave.open(str(masked)) as wav:
            self.assertEqual(wav.getnframes(), 64000)
            data = wav.readframes(64000)
        expected = b''.join([b'\x2a\x01' * 4000, bytes(40000), b'\x2a\x01' * 8000, bytes(36000), b'\x2a\x01' * 14000])
        self.assertEqual(data, expected)
        with wave.open(str(self.source)) as wav:
            self.assertEqual(wav.readframes(64000), b'\x2a\x01' * 64000)

    def test_no_match_does_not_start_asr_or_adopt_other_speech(self):
        job = VoiceFocus(self.folder)
        report = dict(status='not_found',timeline_preserved=True,
                      uncertain_intervals=[dict(start=0,end=2),dict(start=2,end=4)])
        (self.folder/'decisions.json').write_text(json.dumps(report))
        self.assertEqual(job.recognize(self.source, self.folder), ([],[dict(start=0,end=4)],'not_found'))

    def test_invalid_result_identity_cannot_serve_audio(self):
        root = self.folder / 'project/outputs/recorder'
        (root / 'recordings').mkdir(parents=True)
        (root / 'recordings/record.wav').symlink_to(self.source)
        feature = VoiceFocus(root)
        self.assertEqual(feature.status('record.wav')['status'], 'idle')
        with self.assertRaises(ValueError):
            feature.audio('record.wav','../original.wav')
        with self.assertRaises(ValueError):
            feature.source('../record.wav')

    def test_preview_keeps_source_position_at_end(self):
        total = 61 * 16000
        self.assertEqual(focus_frames(None, total), (0, total))
        self.assertEqual(focus_frames(12.5, total), (200000, 520000))
        self.assertEqual(focus_frames(51, total), (816000, total))
        with self.assertRaises(ValueError):
            focus_frames(61, total)


class VoiceFocusCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'project/outputs/recorder'
        (self.root / 'recordings').mkdir(parents=True)
        self.source = self.root / 'recordings/record.wav'
        with wave.open(str(self.source), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x2a\x01' * 64000)
        self.feature = VoiceFocus(self.root)
        for name in ('voice_focus.py', 'target_speech.py', 'qwen_transcribe.py', 'quality_asr.py', 'asr_guard.py'):
            (self.root / name).write_text('revision one\n')
        for interpreter in (self.feature.runtime / 'bin/python', self.feature.work / 'asr-env/bin/python'):
            interpreter.parent.mkdir(parents=True, exist_ok=True)
            interpreter.touch()
        models = self.feature.runtime / 'models'
        models.mkdir(parents=True)
        for name in ('frozen.json', 'pins.json'):
            (models / name).write_text('{}')
        self.weight = self.feature.work / 'models/gigaam-beam/v3_ctc.int8.onnx'
        self.weight.parent.mkdir(parents=True)
        self.weight.write_bytes(b'original weights')
        self.record = dict(source=stamp(self.source), reference_stamp=stamp(self.source), reference='record.wav',
                           start=0, end=4, offset=0, until=4, id='a' * 32, segments=[], unsure=[], match='not_found',
                           method=stamp(self.root / 'target_speech.py'),
                           models=stamp(models / 'frozen.json'), pipeline=self.feature.pipeline_signature())
        self.folder = self.feature.directory('record.wav')
        self.folder.mkdir(parents=True)
        self.current = self.folder / 'current.json'
        self.current.write_text(json.dumps(self.record))
        old = self.folder / self.record['id']
        old.mkdir()
        shutil.copyfile(self.source, old / 'focus.wav')

    def test_unchanged_pipeline_reuses_result_without_another_job(self):
        self.assertEqual(self.feature.result('record.wav'), self.record)
        with patch.object(self.feature, '_run', side_effect=AssertionError('Unexpected recognition')):
            self.assertEqual(self.feature.start('record.wav', 'record.wav', 0, 4)['status'], 'ready')
        self.assertIsNone(self.feature.thread)

    def test_legacy_cache_is_not_deleted_or_presented_as_current(self):
        del self.record['pipeline']
        self.current.write_text(json.dumps(self.record))
        self.assertEqual(self.feature.result('record.wav'), {})
        self.assertEqual(self.feature.status('record.wav')['status'], 'idle')
        self.assertTrue((self.folder / self.record['id'] / 'focus.wav').is_file())
        self.assertEqual(json.loads(self.current.read_text()), self.record)

    def test_changed_code_configuration_and_weights_invalidate_cache(self):
        paths = [self.root / name for name in ('target_speech.py', 'qwen_transcribe.py', 'quality_asr.py', 'asr_guard.py')]
        paths += [self.feature.runtime / 'models' / name for name in ('frozen.json', 'pins.json')]
        manifest = self.feature.work / 'models/gigaam-beam-manifest.json'
        manifest.write_text('{}')
        paths += [manifest, self.weight]
        for path in paths:
            with self.subTest(path=path.name):
                self.record['pipeline'] = self.feature.pipeline_signature()
                self.current.write_text(json.dumps(self.record))
                self.assertTrue(self.feature.result('record.wav'))
                info = path.stat()
                content = path.read_bytes()
                path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                self.assertEqual(self.feature.result('record.wav'), {})
                with self.assertRaises(ValueError):
                    self.feature.audio('record.wav', self.record['id'])

    def test_optional_model_installation_and_linked_model_replacement_invalidate(self):
        model = self.feature.runtime / 'models/ecapa'
        external = self.root.parent / 'embedding'
        external.mkdir()
        model.symlink_to(external, target_is_directory=True)
        self.record['pipeline'] = self.feature.pipeline_signature()
        self.current.write_text(json.dumps(self.record))
        (external / 'embedding_model.ckpt').write_bytes(b'new speaker model')
        self.assertEqual(self.feature.result('record.wav'), {})
        self.record['pipeline'] = self.feature.pipeline_signature()
        self.current.write_text(json.dumps(self.record))
        (external / 'embedding_model.ckpt').write_bytes(b'replacement model')
        self.assertEqual(self.feature.result('record.wav'), {})

    def test_output_changes_do_not_invalidate_input_identity(self):
        before = self.feature.pipeline_signature()
        (self.folder / 'worker.log').write_text('progress')
        (self.root / 'recordings/another.wav').write_bytes(b'another recording')
        self.assertEqual(self.feature.pipeline_signature(), before)

    def test_start_after_asr_update_schedules_a_new_job(self):
        (self.root / 'quality_asr.py').write_text('new ASR implementation\n')
        with patch.object(self.feature, '_run') as run:
            self.feature.start('record.wav', 'record.wav', 0, 4)
            self.feature.thread.join()
        run.assert_called_once()
        signature = run.call_args.args[-1]
        self.assertNotEqual(signature['pipeline'], self.record['pipeline'])
        self.assertEqual(signature['pipeline'], self.feature.pipeline_signature())

    def test_update_before_processing_does_not_run_or_replace_previous_result(self):
        (self.root / 'quality_asr.py').write_text('changed before execution\n')
        self.feature.job = {'file': 'record.wav', 'status': 'processing'}
        with patch.object(self.feature, 'separate', side_effect=AssertionError('Unexpected separation')):
            self.feature._run(self.source, self.source, (0, 64000), (0, 64000), self.record)
        self.assertEqual(self.feature.job['status'], 'error')
        self.assertIn('изменились', self.feature.job['message'])
        self.assertEqual(json.loads(self.current.read_text()), self.record)

    def test_update_during_recognition_does_not_publish_mixed_pipeline_result(self):
        self.feature.job = {'file': 'record.wav', 'status': 'processing'}
        before = self.source.read_bytes()

        def separate(source, reference, output, decisions, folder):
            shutil.copyfile(source, output)

        def recognize(focused, folder):
            self.weight.write_bytes(b'weights replaced during recognition')
            return [{'start': 1, 'end': 2, 'text': 'Sample'}], [], 'matched'

        with patch.object(self.feature, 'separate', separate), patch.object(self.feature, 'recognize', recognize):
            self.feature._run(self.source, self.source, (0, 64000), (0, 64000), self.record)
        self.assertEqual(self.feature.job['status'], 'error')
        self.assertEqual(json.loads(self.current.read_text()), self.record)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [self.record['id'], 'current.json'])

    def test_valid_run_retains_segments_and_records_pipeline(self):
        self.feature.job = {'file': 'record.wav', 'status': 'processing'}
        before = self.source.read_bytes()

        def separate(source, reference, output, decisions, folder):
            shutil.copyfile(source, output)

        with patch.object(self.feature, 'separate', separate), patch.object(self.feature, 'recognize',
                return_value=([{'start': 1, 'end': 2, 'text': 'Sample'}], [{'start': 0, 'end': 1}], 'partial')):
            self.feature._run(self.source, self.source, (0, 64000), (0, 64000), self.record)
        saved = self.feature.result('record.wav')
        self.assertEqual(saved['segments'], [{'start': 1, 'end': 2, 'text': 'Sample'}])
        self.assertEqual(saved['unsure'], [{'start': 0, 'end': 1}])
        self.assertEqual(saved['pipeline'], self.feature.pipeline_signature())
        self.assertEqual(self.feature.audio('record.wav', saved['id']).read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), before)
