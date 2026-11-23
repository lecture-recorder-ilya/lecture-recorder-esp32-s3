from pathlib import Path
import sys
import unittest
import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'tools'), str(Path(__file__).resolve().parents[1]/'outputs/recorder')]
from speech_channels import choose_speech_channel


class Tests(unittest.TestCase):
    def setUp(self):
        self.signal = (.08*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
        self.voice = lambda _: [(0, 1)]

    def test_mono_does_not_even_call_vad(self):
        def forbidden(_):raise AssertionError('Моно не требует VAD')
        before = self.signal.copy()
        self.assertIsNone(choose_speech_channel(self.signal, forbidden)[0])
        np.testing.assert_array_equal(self.signal, before)

    def test_clipped_channel_loses_to_clean_voice(self):
        clipped = np.clip(self.signal*100, -1, 1)
        self.assertEqual(choose_speech_channel(np.column_stack([clipped, self.signal]), self.voice)[0], 1)

    def test_anti_phase_does_not_cancel_the_voice(self):
        choice, report = choose_speech_channel(np.column_stack([self.signal, -self.signal]), self.voice)
        self.assertEqual(choice, 0)
        self.assertTrue(report['anti_phase'])

    def test_same_channels_keep_existing_import(self):
        self.assertIsNone(choose_speech_channel(np.column_stack([self.signal]*2), self.voice)[0])

    def test_constant_channel_not_treated_as_voice(self):
        self.assertEqual(choose_speech_channel(np.column_stack([np.ones(16000)*.9, self.signal]), self.voice)[0], 1)

    def test_input_and_no_voice_are_preserved(self):
        data = np.column_stack([self.signal, self.signal*.3])
        before = data.copy()
        self.assertIsNone(choose_speech_channel(data, lambda _: [])[0])
        np.testing.assert_array_equal(data, before)


if __name__ == '__main__':unittest.main()
