import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import prepare_asr_sound_checks as prepare


class QuietHoldoutTests(unittest.TestCase):
    def test_rebuild_quiet_holdout_from_pinned_bytes_and_reference(self):
        audio = BytesIO()
        with wave.open(audio, 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\x02\x00' * 64)
        raw = audio.getvalue()
        reference = 'Сколько сантиметров?'
        digest = hashlib.sha256(raw).hexdigest()
        revision = 'pinned-revision'
        url = f'https://example.com/{revision}/sound.wav'
        case = dict(id='golos-0001', source_id=1, source_audio_sha256=digest, audio_sha256=digest,
                    reference_sha256=hashlib.sha256(reference.encode()).hexdigest(), subset='quiet')
        lock = dict(source_revision=revision, cases=[case])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root/'tests/fixtures/asr'
            fixtures.mkdir(parents=True)
            report = fixtures/'quiet-holdout.json'
            report.write_text(json.dumps(lock))

            def run(output, downloaded, transcript):
                fixture = {1: {'audio': [{'src': url}], 'transcription': transcript}}
                with patch.object(prepare, 'ROOT', root), patch.object(sys, 'argv', ['prepare', str(output), '--quiet-holdout']), \
                     patch.object(prepare, 'golos_page', return_value=fixture) as page, \
                     patch.object(prepare, 'download', return_value=downloaded) as download:
                    prepare.main()
                    page.assert_called_once_with(0, revision)
                    download.assert_called_once_with(url)

            output = root/'correct'
            run(output, raw, reference)
            self.assertEqual((output/'golos-0001.wav').read_bytes(), raw)
            self.assertEqual(json.loads((output/'manifest.json').read_text()),
                             [dict(id=case['id'], audio='golos-0001.wav', audio_sha256=digest,
                                   reference=reference, subset='quiet')])

            for downloaded, transcript in ((raw[:-1], reference), (raw, 'Другой эталон.')):
                output = root/'rejected'
                with self.assertRaisesRegex(ValueError, 'Изменилось аудио или эталон golos-0001'):
                    run(output, downloaded, transcript)
                self.assertFalse(output.exists())

            invalid = b'not WAV'
            case['source_audio_sha256'] = case['audio_sha256'] = hashlib.sha256(invalid).hexdigest()
            report.write_text(json.dumps(lock))
            output = root/'invalid'
            with self.assertRaisesRegex(ValueError, 'Некорректный WAV.*golos-0001'):
                run(output, invalid, reference)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
