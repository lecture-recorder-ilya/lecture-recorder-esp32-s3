"""Регрессии опытных правил: запрет выдуманных слов и критических подмен."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'outputs/recorder')]
from asr_low_snr_policy import choose_audio, recover_gaps, gap_windows


def word(text, start, confidence=.95):
    return dict(text=text, start=start, end=start+.2, confidence=confidence)


def evidence(words, confidence=.8):
    return dict(word_evidence=words, ctc_confidence=confidence)


class Tests(unittest.TestCase):
    def setUp(self):
        self.base = [word('сначала', 0), word('объясняем', .4), word('потом', 1.4), word('проверяем', 2)]
        self.full = self.base[:2]+[word('связь', .9)]+self.base[2:]

    def trace(self, ctc=None, rnnt=None, group=1):
        return [dict(group=group, ctc=self.full if ctc is None else ctc, rnnt=self.full if rnnt is None else rnnt)]

    def test_two_decoders_restore_only_the_gap(self):
        before = deepcopy(self.base)
        result, added = recover_gaps(evidence(self.base), self.trace())
        self.assertEqual([w['text'] for w in result['word_evidence']], [w['text'] for w in self.full])
        self.assertEqual([w for w in result['word_evidence'] if w not in added], before)
        self.assertEqual(added[0]['start'], .9)
        self.assertTrue(added[0]['needs_review'])
        self.assertEqual(self.base, before)

    def test_one_decoder_vote_cannot_insert(self):
        self.assertEqual(recover_gaps(evidence(self.base), self.trace(rnnt=[]))[1], [])

    def test_decoder_disagreement_cannot_insert(self):
        other = self.base[:2]+[word('деталь', .9)]+self.base[2:]
        self.assertEqual(recover_gaps(evidence(self.base), self.trace(rnnt=other))[1], [])

    def test_same_words_at_wrong_times_cannot_insert(self):
        other = deepcopy(self.full)
        other[2]['start'] += .3
        other[2]['end'] += .3
        self.assertEqual(recover_gaps(evidence(self.base), self.trace(rnnt=other))[1], [])

    def test_numbers_negations_and_operators_are_not_added(self):
        for value in ('не', 'без', 'три', 'двумя', 'миллиона', '15', 'плюс', 'сорока', 'ста', 'полутора'):
            with self.subTest(value=value):
                full = self.base[:2]+[word(value, .9)]+self.base[2:]
                self.assertEqual(recover_gaps(evidence(self.base), self.trace(full, full))[1], [])

    def test_edges_and_edge_retries_cannot_insert(self):
        prefix = [word('вступление', -.3)]+self.base
        self.assertEqual(recover_gaps(evidence(self.base), self.trace(prefix, prefix))[1], [])
        self.assertEqual(recover_gaps(evidence(self.base), self.trace(group=2))[1], [])

    def test_empty_noise_transcript_cannot_be_filled(self):
        self.assertEqual(recover_gaps(evidence([]), self.trace())[1], [])
        self.assertEqual(choose_audio(evidence([], 0), evidence(self.full, 1))[1], 'clean')

    def test_raw_choice_needs_margin_and_matching_anchors(self):
        self.assertEqual(choose_audio(evidence(self.base, .8), evidence(self.full, .85))[1], 'raw')
        self.assertEqual(choose_audio(evidence(self.base, .8), evidence(self.full, .82))[1], 'clean')
        unrelated = [word(t, i) for i, t in enumerate(('совершенно', 'другие', 'слова', 'здесь'))]
        self.assertEqual(choose_audio(evidence(self.base, .8), evidence(unrelated, 1))[1], 'clean')

    def test_raw_choice_cannot_erase_negation(self):
        original = [word(t, i) for i, t in enumerate(('сначала', 'сигнал', 'не', 'падает', 'затем', 'растет'))]
        other = [w for w in original if w['text'] != 'не']+[word('уверенно', 6)]
        self.assertEqual(choose_audio(evidence(original, .7), evidence(other, 1))[1], 'clean')

    def test_gap_crops_require_existing_voice(self):
        self.assertEqual(gap_windows(self.base, [], 3), [])
        self.assertTrue(gap_windows(self.base, [(0, 3)], 3))
        self.assertEqual(gap_windows([], [(0, 3)], 3), [])

    def test_equal_negation_count_does_not_allow_moving_it(self):
        original = [word(t, i) for i, t in enumerate(('сначала', 'не', 'измеряем', 'сигнал', 'потом', 'записываем'))]
        other = [word(t, i) for i, t in enumerate(('сначала', 'измеряем', 'сигнал', 'потом', 'не', 'записываем'))]
        self.assertEqual(choose_audio(evidence(original, .7), evidence(other, 1))[1], 'clean')

    def test_gap_crops_stay_inside_audio(self):
        ranges = gap_windows(self.base, [(0, 3)], 2.2)
        self.assertTrue(all(0 <= a < b <= 2.2 for a, b in ranges))


if __name__ == '__main__':
    unittest.main()
