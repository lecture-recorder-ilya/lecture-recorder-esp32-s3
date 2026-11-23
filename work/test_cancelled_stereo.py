import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from audio_import import _restore_cancelled_stereo, normalize


class CancelledStereoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.wav'
        self.target = self.root / 'target.wav'

    def write(self, samples, channels=2):
        with wave.open(str(self.source), 'wb') as stream:
            stream.setparams((channels, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(struct.pack('<' + 'h' * len(samples), *samples))

    def test_exact_antiphase_preserves_original_left_samples_without_converter(self):
        left = [0, 1, -1, 127, -32767, 32767, 0] * 200
        self.write([v for x in left for v in (x, -x)])
        original = self.source.read_bytes()
        converter = Mock(side_effect=AssertionError('Converter must not be used'))
        normalize(self.source, self.target, self.root, run=converter)
        with wave.open(str(self.target)) as stream:
            self.assertEqual(stream.getparams()[:3], (1, 2, 16000))
            self.assertEqual(stream.readframes(stream.getnframes()), struct.pack('<'+'h'*len(left), *left))
        self.assertEqual(self.source.read_bytes(), original)
        converter.assert_not_called()

    def test_one_sample_difference_even_after_first_block_leaves_downmix_in_charge(self):
        values = [12, -12] * (30*16000+1)
        values[-1] = -11
        self.write(values)
        with wave.open(str(self.source)) as stream:
            self.assertFalse(_restore_cancelled_stereo(stream, self.target))
        self.assertFalse(self.target.exists())

    def test_ordinary_stereo_silence_and_int16_minimum_are_not_selected(self):
        for values in ([0, 0]*20, [5, 5]*20, [5, 0]*20, [-32768, -32768]*20):
            with self.subTest(values=values[:2]):
                self.write(values)
                with wave.open(str(self.source)) as stream:
                    self.assertFalse(_restore_cancelled_stereo(stream, self.target))
                self.assertFalse(self.target.exists())

    def test_mono_remains_bit_exact_without_converter(self):
        values = [0, -32768, 32767, 1, -1]
        self.write(values, channels=1)
        normalize(self.source, self.target, self.root, run=Mock(side_effect=AssertionError()))
        self.assertEqual(self.source.read_bytes(), self.target.read_bytes())

    def test_cancelled_stereo_is_streamed_across_block_boundary(self):
        count = 30*16000+7
        self.write([27, -27] * count)
        normalize(self.source, self.target, self.root, run=Mock(side_effect=AssertionError()))
        with wave.open(str(self.target)) as stream:
            self.assertEqual(stream.getnframes(), count)
            self.assertEqual(stream.readframes(count), struct.pack('<h',27)*count)

    def test_truncated_antiphase_is_rejected_before_success(self):
        self.write([1, -1]*20)
        self.source.write_bytes(self.source.read_bytes()[:-4])
        with self.assertRaisesRegex(ValueError, 'обрывается'):
            normalize(self.source, self.target, self.root, run=Mock(side_effect=AssertionError()))


if __name__ == '__main__':
    unittest.main()
