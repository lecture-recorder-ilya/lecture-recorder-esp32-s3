"""Проверки синхронизации на синтетическом сигнале."""
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from compare import measure, read_pcm


class CompareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master, cls.fs = read_pcm(Path(__file__).with_name("reference.wav"), 1)

    def test_phone_stereo_with_offset_drift_gain_and_noise(self):
        rate = 48000
        stretch = 1.001
        lag = 0.8
        t = np.arange(29 * rate) / rate
        samples = np.interp((t - lag) * self.fs / stretch, np.arange(len(self.master)),
                            self.master, left=0, right=0) * 0.25
        samples += np.random.default_rng(0).normal(0, 0.0005, len(samples))
        stereo = np.column_stack((np.zeros_like(samples), samples))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "phone.wav"
            with wave.open(str(path), "wb") as out:
                out.setparams((2, 2, rate, 0, "NONE", "not compressed"))
                out.writeframes(np.rint(stereo * 32768).astype("<i2").tobytes())
            result = measure(path, 2, self.master, self.fs)
            for found, start in zip(result["marker_times_s"], (1, 25)):
                self.assertAlmostEqual(found, lag + start * stretch, delta=0.002)
            start = round((lag + 7 * stretch) * rate)
            end = round((lag + 22.25 * stretch) * rate)
            expected_peak = 20 * np.log10(np.max(np.abs(samples[start:end])))
            self.assertAlmostEqual(result["speech_peak_dbfs"], expected_peak, delta=0.02)
            self.assertIsNotNone(result["speech_plus_noise_over_background_db"])
            with self.assertRaises(ValueError):
                measure(path, 1, self.master, self.fs)

    def test_duplicate_playback_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "twice.wav"
            with wave.open(str(path), "wb") as out:
                out.setparams((1, 2, self.fs, 0, "NONE", "not compressed"))
                out.writeframes(np.tile(self.master * 32768, 2).astype("<i2").tobytes())
            with self.assertRaises(ValueError):
                measure(path, 1, self.master, self.fs)


if __name__ == "__main__":
    unittest.main()
