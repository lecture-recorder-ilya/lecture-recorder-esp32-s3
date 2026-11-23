import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_pair_capture import check


class PairCaptureTests(unittest.TestCase):
    def test_three_distances_and_reject_wrong_original_or_missing_measurement(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            content = b'fixture'
            (path / 'capture.wav').write_bytes(content)
            sha = hashlib.sha256(content).hexdigest()
            series = dict(room='fixture', source='fixture', takes=[],
                          reference=dict(reference_type='scripted', text='Не пятнадцать.',
                                         wav='capture.wav', sha256=sha))
            for distance in (1, 3, 5):
                device = dict(wav='capture.wav', original='capture.wav', original_sha256=sha, channel=1,
                              device='fixture', microphone='fixture', position='fixture',
                              distance_measured_m=distance, height_m=1)
                result = dict(channel=1, sha256=sha, marker_times_s=[1.125, 25.125])
                sync = path / f'{distance}.json'
                sync.write_text(json.dumps(dict(distance_m=distance, ClipMic=result, phone=result)))
                series['takes'].append(dict(id=str(distance), distance_m=distance, sync_json=sync.name,
                                            ClipMic=dict(device), phone=dict(device)))
            passport = path / 'series.json'

            def save():
                passport.write_text(json.dumps(series))

            save()
            self.assertEqual(check(passport), 3)
            phone = series['takes'][1]['phone']
            phone['original_sha256'] = '0' * 64
            save()
            with self.assertRaisesRegex(ValueError, 'файлы или канал phone отличаются'):
                check(passport)
            phone['original_sha256'] = sha
            phone['distance_measured_m'] = None
            save()
            with self.assertRaisesRegex(ValueError, 'нужно фактическое измерение'):
                check(passport)


if __name__ == '__main__':
    unittest.main()
