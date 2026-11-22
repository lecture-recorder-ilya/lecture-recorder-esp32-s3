import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from asr_units import restore_spoken_units


def word(text, start, end, confidence=.97):
    return dict(text=text, start=start, end=end, confidence=confidence)


def symbol(text, start=.8, score=-.03, punctuation='.'):
    return SimpleNamespace(tokens=[' 700', text, punctuation], timestamps=[.2, start, 1.2],
                           logprobs=[-.01, score, -.02])


class SpokenUnits(unittest.TestCase):
    def setUp(self):
        self.primary = [word('700', .20, .68)]
        self.heard = [word('рублей', .82, 1.16)]

    def test_keeps_spoken_form_time_and_punctuation(self):
        for glyph, name in [('₽', 'рублей'), ('%', 'процента'), ('€', 'евро'), ('$', 'доллар')]:
            with self.subTest(name=name):
                result, changes = restore_spoken_units(self.primary, symbol(glyph), symbol('▁'+glyph),
                                                       [word(name, .82, 1.16)])
                self.assertEqual([w['text'] for w in result], ['700', name+'.'])
                self.assertEqual((result[1]['start'], result[1]['end']), (.82, 1.16))
                self.assertEqual(result[1]['original_text'], glyph+'.')
                self.assertTrue(result[1]['needs_review'])
                self.assertEqual(changes[0]['source'], 'spoken-unit-consensus')
                self.assertEqual(self.primary, [word('700', .20, .68)])

    def test_disagreement_low_scores_and_other_time(self):
        for second, heard in [(symbol('$'), self.heard), (symbol('₽', 1.5), self.heard),
                              (symbol('₽', score=-1), self.heard), (symbol(' ₽'), []),
                              (symbol('₽'), [word('долларов', .82, 1.16)]),
                              (symbol('₽'), [word('рублей', .82, 1.16, .70)])]:
            result, changes = restore_spoken_units(self.primary, symbol('₽'), second, heard)
            self.assertEqual(result, self.primary)
            self.assertEqual(changes, [])

    def test_needs_numeric_anchor_and_clear_gap(self):
        for primary in [[], [word('тема', .20, .68)], [word('700', .0, .12)],
                        [*self.primary, word('лекция', 1.0, 1.2)],
                        [*self.primary, word('рублей.', 1.19, 1.4)], [word('700₽.', .2, .68)]]:
            self.assertEqual(restore_spoken_units(primary, symbol('₽'), symbol('₽'), self.heard),
                             (primary, []))


if __name__ == '__main__':
    unittest.main()
