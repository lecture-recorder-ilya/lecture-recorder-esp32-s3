import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from long_take import RATE, inspect, make


class LongTakeTest(unittest.TestCase):
    def test_faults(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "master.wav"
            make(source, None)
            clean = inspect(source, 1)
            self.assertEqual(clean["markers_s"], [1, 31, 61, 91, 121, 151, 181])
            self.assertTrue(all(b["relative_timing_jump_ms"] == 0 for b in clean["blocks"]))
            with wave.open(str(source)) as wav:
                params = wav.getparams()
                pcm = np.frombuffer(wav.readframes(wav.getnframes()), "<i2").copy()
            pcm[121*RATE:122*RATE] = 0
            pcm[13*RATE:13*RATE+100] = 32767
            pcm = np.delete(pcm, np.s_[70*RATE:70*RATE+1600])
            faulty = Path(folder) / "fault.wav"
            with wave.open(str(faulty), "wb") as wav:
                wav.setparams(params)
                wav.writeframes(pcm.tobytes())
            result = inspect(faulty, 1)
            self.assertIsNone(result["markers_s"][4])
            self.assertEqual(result["blocks"][0]["rail_samples"], 100)
            self.assertEqual(result["blocks"][2]["relative_timing_jump_ms"], -100)


if __name__ == "__main__":
    unittest.main()
