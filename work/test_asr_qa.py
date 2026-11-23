import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from asr_qa import audit, lock_control, summarize
from evaluate_asr import audio_sha256


class IndependentAsrTests(unittest.TestCase):
    def audit_pair(self, reference, hypothesis, subset='openstt_lectures'):
        return audit(dict(id='test', subset=subset, audio_sha256='sha', reference=reference),
                     dict(text=hypothesis, elapsed_seconds=.5, duration=2))

    def test_contiguous_words_are_one_phrase_omission(self):
        result = self.audit_pair('это начало пропавшей целой фразы и конец', 'это начало и конец')
        self.assertEqual(result['phrase_deletions'], [[2, 5]])
        self.assertEqual(result['phrase_count'], 1)
        self.assertEqual(self.audit_pair('один два три', 'один')['phrase_count'], 0)

    def test_negation_shift_and_number_replacement_are_visible(self):
        result = self.audit_pair('не делим на 15 и прибавляем единицу',
                                 'делим на 50 и не прибавляем единицу')
        self.assertEqual(result['numbers'], dict(reference=1, lost_or_changed=1, inserted_or_changed=1))
        self.assertEqual(result['negations'], dict(reference=1, lost_or_changed=1, inserted_or_changed=1))

    def test_empty_and_no_speech_results_have_separate_denominators(self):
        rows = [self.audit_pair('это вся фраза', ''), self.audit_pair('', 'один', 'no_speech')]
        summary = summarize(rows)
        self.assertEqual(summary['openstt_lectures']['empty_decodes'], 1)
        self.assertIsNone(summary['no_speech']['wer'])
        self.assertEqual(summary['no_speech']['no_speech_words'], 1)

    def test_lock_keeps_reference_private_and_refuses_changed_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio, manifest = root / 'a.wav', root / 'manifest.json'
            audio.write_bytes(b'original')
            manifest.write_text(json.dumps([dict(id='a', audio='a.wav', reference='эталон',
                                                 audio_sha256=audio_sha256(audio), subset='no_speech')]))
            lock = lock_control(manifest)
            self.assertNotIn('reference', lock['cases'][0])
            self.assertIn('reference_sha256', lock['cases'][0])
            audio.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'не совпадает'):
                lock_control(manifest)


if __name__ == '__main__':
    unittest.main()
