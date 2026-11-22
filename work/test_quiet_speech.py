import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from asr_segments import phrase_rows
from quality_asr import Decoder
from speech_gate import SpeechProfile, speech_profile


def result(tokens, times, confidence=.99):
    return SimpleNamespace(tokens=tokens, timestamps=times, logprobs=[math.log(confidence)] * len(tokens))


class QuietSpeechTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.full(32000, .008, dtype=np.float32)
        self.profile = SpeechProfile([], [], [], quiet=((.60, 1.52),))
        self.decoder = Decoder()
        self.models = {
            'ctc': Mock(recognize=Mock(return_value=result(['Говори,', ' пожалуйста.'], [.32, .72]))),
            'rnnt': Mock(recognize=Mock(return_value=result(['Говори', ' пожалуйста.'], [.34, .72], .71))),
            'char': Mock(recognize=Mock(return_value=result(['говори', ' пожалуйста'], [.32, .72]))),
        }

    def decode(self, start=0, end=2):
        with patch.object(self.decoder, '_load', side_effect=self.models.__getitem__):
            return self.decoder.transcribe(self.audio, speech=self.profile, emit_start=start, emit_end=end)

    def test_only_quiet_candidate_is_analyzed_after_amplification(self):
        weak = [.01] * 15 + [.59] * 22 + [.02] * 25
        strong = [.01] * 15 + [.85] * 22 + [.02] * 25
        with patch('speech_gate._probabilities', side_effect=[weak, strong]) as probabilities:
            profile = speech_profile(self.audio)
        self.assertFalse(profile.padded)
        self.assertFalse(profile.anchored)
        self.assertEqual(len(profile.quiet), 1)
        np.testing.assert_array_equal(probabilities.call_args.args[0], self.audio * 4)
        np.testing.assert_array_equal(self.audio, np.full(32000, .008, dtype=np.float32))
        for values, audio in [(weak, self.audio * 12), ([.12] * 62, self.audio), (strong, self.audio)]:
            with patch('speech_gate._probabilities', return_value=values) as probabilities:
                self.assertFalse(speech_profile(audio).quiet)
                probabilities.assert_called_once()

    def test_agreement_keeps_original_time_and_review_metadata(self):
        text = self.decode()
        self.assertEqual(text, 'Говори, пожалуйста.')
        row, = phrase_rows(text, self.decoder.last, 32, 32, 34)
        self.assertEqual((row['start'], row['end']), (32.62, 33.06))
        self.assertTrue(row['needs_review'])
        first, second = row['recognition']['word_evidence']
        self.assertEqual(first['review_reason'], 'quiet_speech_consensus')
        self.assertAlmostEqual(first['confidence'], .71)
        self.assertLess(first['start'], second['start'])
        self.assertEqual(self.decode(end=.9), 'Говори,')
        self.assertEqual(self.decode(start=.9), 'пожалуйста.')

    def test_disagreement_weak_scores_and_misalignment_stay_empty(self):
        for character in [
            result(['говори', ' громче'], [.32, .72]),
            result(['говори', ' пожалуйста'], [.32, .72], .80),
            result(['говори', ' пожалуйста'], [.32, 1.01]),
        ]:
            with self.subTest(character=character.tokens):
                self.models['char'].recognize.return_value = character
                self.assertEqual(self.decode(), '')
                self.assertEqual(self.decoder.last['word_evidence'], [])
        self.models['ctc'].recognize.return_value = result(['Говори.'], [.32])
        self.models['rnnt'].recognize.reset_mock()
        self.assertEqual(self.decode(), '')
        self.models['rnnt'].recognize.assert_not_called()

    def test_digit_separators_are_not_treated_as_agreement(self):
        self.models['ctc'].recognize.return_value = result(['Сумма', ' 1,2.'], [.32, .72])
        self.models['rnnt'].recognize.return_value = result(['Сумма', ' 12.'], [.32, .72])
        self.assertEqual(self.decode(), '')
        self.models['char'].recognize.assert_not_called()

    def test_word_in_overlapping_context_is_emitted_once(self):
        from quiet_speech import confirmed_quiet_words

        left = dict(text='Речь', start=4.70, end=4.80)
        right = dict(text='слышна.', start=4.86, end=4.96)
        shift = 4.60
        from_second_window = [dict(word, start=word['start'] - shift, end=word['end'] - shift)
                              for word in [left, right]]
        with patch('quiet_speech._consensus', side_effect=[[left, right], from_second_window]):
            text, details = confirmed_quiet_words(np.zeros(160000), [(.15, 4.70), (4.90, 9.60)], 0, 10, Mock())
        self.assertEqual(text, 'Речь слышна.')
        self.assertEqual(details['words'], 2)

    def test_saved_transcript_checks_quiet_candidate(self):
        import qwen_transcribe

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / 'test.wav'
            report = root / 'result.json'
            with wave.open(str(audio), 'wb') as stream:
                stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                stream.writeframes((self.audio * 32768).astype('<i2').tobytes())
            with patch('speech_gate.speech_profile', return_value=self.profile), \
                 patch.object(Decoder, '_load', side_effect=self.models.__getitem__):
                qwen_transcribe.run(audio, report, root / 'progress.json')
            saved = json.loads(report.with_suffix('.transcript.json').read_text())
            self.assertTrue(saved['complete'])
            self.assertEqual(saved['segments'][0]['text'], 'Говори, пожалуйста.')
            self.assertTrue(saved['segments'][0]['needs_review'])

    def test_live_recognizes_only_agreed_candidate(self):
        import study_service

        pcm = (self.audio * 32768).astype('<i2').tobytes()
        with patch.dict(study_service.QUALITY_CURSOR, {'file': 'test.wav', 'end': 0}), \
             patch.object(study_service, 'quality_ready', return_value=True), \
             patch.object(study_service, 'read_pcm', return_value=pcm), \
             patch.object(study_service.store, 'audio', return_value=Path('test.wav')), \
             patch.object(study_service, 'speech_profile', return_value=self.profile), \
             patch.object(study_service.QUALITY_DECODER, '_load', side_effect=self.models.__getitem__):
            response = study_service.monitor_quality('test.wav', 32000, flush=True)
            self.assertEqual(response['segments'][0]['text'], 'Говори, пожалуйста.')
            study_service.QUALITY_CURSOR['end'] = 0
            self.models['char'].recognize.return_value = result(['другие', ' слова'], [.32, .72])
            response = study_service.monitor_quality('test.wav', 32000, flush=True)
            self.assertEqual(response['segments'], [])
            self.assertIn('подтверждённой речи нет', response['message'])


if __name__ == '__main__':
    unittest.main()
