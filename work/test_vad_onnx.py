import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from speech_gate import _BRIEF, _PADDED, _STRICT, _WEAK
from vad_onnx import BLOCK, FRAME, RATE, VoiceDetector, speech_intervals


class DetectionParity(unittest.TestCase):
    def test_frame_probabilities_match_packaged_model_across_blocks_and_calls(self):
        from silero_vad import load_silero_vad

        stock, detector = load_silero_vad(sequence=True), VoiceDetector()
        noise = np.random.default_rng(17).normal(0, .08, 2 * BLOCK + 29).astype('f')
        for n in (0, 17, FRAME, FRAME + 1, BLOCK - 1, BLOCK, BLOCK + 1, len(noise), 379):
            with self.subTest(samples=n):
                np.testing.assert_array_equal(detector.audio_forward(noise[:n]), stock.audio_forward(noise[:n]))

    def test_intervals_match_packaged_thresholds_padding_and_partial_last_frame(self):
        from silero_vad import get_speech_timestamps_from_probs

        rng = np.random.default_rng(37)
        for settings in (_STRICT, _PADDED, _WEAK, _BRIEF):
            threshold = settings['threshold']
            levels = [0., threshold - .15, threshold - .151, threshold - .01, threshold, 1.]
            for _ in range(100):
                sequence = np.repeat(rng.choice(levels, 60), rng.integers(1, 30, size=60)).tolist()
                size = len(sequence) * FRAME - int(rng.integers(FRAME))
                stock = get_speech_timestamps_from_probs(sequence, audio_length_samples=size, **settings)
                ranges = [(row['start'] / RATE, row['end'] / RATE) for row in stock]
                self.assertEqual(speech_intervals(sequence, size, **settings), ranges)


if __name__ == '__main__':
    unittest.main()
