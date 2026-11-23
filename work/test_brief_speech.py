import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from asr_segments import phrase_rows
from quality_asr import Decoder
from speech_gate import SpeechProfile, speech_profile


def result(tokens, times, confidence=.99):
    return SimpleNamespace(tokens=tokens, timestamps=times, logprobs=[math.log(confidence)] * len(tokens))


def model_set(**results):
    return {kind: Mock(recognize=Mock(return_value=values)) for kind, values in results.items()}


class BriefSpeechTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.ones(16000, dtype=np.float32) * .02
        self.profile = SpeechProfile([], [(.10, .90)], [], ((.40, .60),))
        # These mocks provide the full character model, regardless of local weights.
        self.decoder = Decoder(allow_fast_character=False)

    def decode(self, models, start=0, end=1):
        with patch.object(self.decoder, '_load', side_effect=models.__getitem__):
            return self.decoder.transcribe(self.audio, speech=self.profile, emit_start=start, emit_end=end)

    def test_only_zero_skips_vad(self):
        with patch('speech_gate._MODEL') as model:
            self.assertEqual(speech_profile(np.zeros(16000)).padded, [])
            self.assertEqual(speech_profile(np.empty(0)).padded, [])
            model.audio_forward.assert_not_called()
            model.audio_forward.return_value = np.zeros(32)
            tiny = np.zeros(16000, dtype=np.float32)
            tiny[300] = 1 / 32768
            speech_profile(tiny)
            model.audio_forward.assert_called_once()

    def test_isolated_brief_range_alongside_regular_speech(self):
        probabilities = [0.] * 4 + [.99] * 20 + [0.] * 40 + [.98] * 5 + [0.] * 20
        with patch('speech_gate._probabilities', return_value=probabilities):
            profile = speech_profile(np.zeros(len(probabilities) * 512))
        self.assertEqual(len(profile.strict), 1)
        self.assertEqual(len(profile.brief), 1)
        self.assertGreater(profile.brief[0][0], profile.anchored[-1][1] + .60)
        self.assertGreaterEqual(profile.padded[-1][1], profile.brief[-1][1])

    def test_only_agreed_word_with_original_timing_survives(self):
        models = model_set(rnnt=result(['Три', '.'], [.60, 1.10]),
                           char=result(['т', 'р', 'и'], [.60, .64, .68]))
        self.assertEqual(self.decode(models), 'Три.')
        row, = phrase_rows('Три.', self.decoder.last, 20., 20., 21.)
        self.assertEqual((row['start'], row['end']), (20.45, 20.57))
        self.assertTrue(row['needs_review'])
        self.assertEqual(row['recognition']['word_evidence'][0]['review_reason'], 'brief_speech_consensus')
        self.assertEqual(self.decode(models, end=.51), '')
        self.assertEqual(self.decode(models, start=.51), 'Три.')

    def test_tiny_word_requires_third_agreeing_pass(self):
        for third, expected in [('да', 'Да.'), ('на', '')]:
            models = model_set(rnnt=result(['Да.'], [.63]), char=result(['да'], [.65]),
                               ctc=result([third], [.64]))
            self.assertEqual(self.decode(models), expected)
        models['ctc'].recognize.return_value = result(['да'], [.35])
        self.assertEqual(self.decode(models), '')

    def test_quiet_noise_or_disagreement_cannot_fill_the_gap(self):
        for value in [result(['мир'], [.60]), result(['три'], [.94]),
                      result(['три'], [.6], .75), result(['три', ' да'], [.58, .68])]:
            models = model_set(rnnt=result(['Три.'], [.60]), char=value)
            self.assertEqual(self.decode(models), '')
        models = model_set(rnnt=result(['Три.'], [.6], .60))
        self.assertEqual(self.decode(models), '')

    def test_marginal_voice_requires_same_word_after_shift(self):
        for token, time, expected in [('Три.', .76, 'Три.'), ('Три.', 1.02, ''), ('Мир.', .76, '')]:
            models = model_set(rnnt=None, char=result(['три'], [.63]))
            models['rnnt'].recognize.side_effect = [result(['Три.'], [.60], .74), result([token], [time], .88)]
            self.assertEqual(self.decode(models), expected)

    def test_no_word_from_padding_after_file_end(self):
        samples = self.audio[:3200]
        profile = SpeechProfile([], [(0., .2)], [], ((.03, .18),))
        models = model_set(rnnt=result(['Три.'], [.48]), char=result(['три'], [.48]))
        with patch.object(self.decoder, '_load', side_effect=models.__getitem__):
            self.assertEqual(self.decoder.transcribe(samples, speech=profile), '')

    def test_character_pass_keeps_spoken_currency_after_a_number(self):
        profile = SpeechProfile([(0., 1.)], [(0., 1.)], [(0., 1.)])
        signs = result(['15', ' ₽'], [.22, .60])
        models = model_set(ctc=signs, rnnt=signs, char=result(['15', ' рублей'], [.22, .60]))
        with patch.object(self.decoder, '_load', side_effect=models.__getitem__):
            self.assertEqual(self.decoder.transcribe(self.audio, speech=profile), '15 рублей')
        self.assertEqual(models['char'].recognize.call_count, 1)

    def test_skip_character_model_only_when_review_and_units_cannot_use_it(self):
        profile = SpeechProfile([(0., 1.)], [(0., 1.)], [(0., 1.)])
        for token, terms, confidence, calls in [('Мир.', [], .88, 0), ('15', [], .96, 0),
                                               ('Мир.', ['предел'], .96, 1), ('Мир.', [], .74, 1)]:
            models = model_set(ctc=result([token], [.22]), rnnt=result([token], [.22], confidence),
                               char=result([token], [.22]))
            with patch.object(self.decoder, '_load', side_effect=models.__getitem__):
                self.decoder.transcribe(self.audio, terms=terms, speech=profile)
            self.assertEqual(models['char'].recognize.call_count, calls)


if __name__ == '__main__':
    unittest.main()
