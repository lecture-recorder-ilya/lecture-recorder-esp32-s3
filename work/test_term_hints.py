"""Подсказка не меняет отрицание и не заменяет акустические доказательства."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from asr_terms import apply_terms


def word(text, start, confidence=.8):
    return dict(text=text, start=start, end=start+.2, confidence=confidence)


class Tests(unittest.TestCase):
    def pair(self, before, after):
        return [word(before, .4, .6), word('показатель', .8, .99)], [word(after, .4), word('показатель', .8, .99)]

    def test_both_directions_of_negation_are_preserved(self):
        for before, after in [('зависимый','независимый'), ('неактивный','активный'), ('неточный','точный')]:
            a,b=self.pair(before,after);out,changes=apply_terms(a,[('rnnt',b)],[after])
            self.assertEqual(out[0]['text'],before);self.assertFalse(changes)
            self.assertEqual(out[0]['review_reason'],'term_negation_mismatch')

    def test_nominative_hint_uses_only_spoken_case(self):
        a,b=self.pair('пробилку','пробирку');before=deepcopy(a)
        out,changes=apply_terms(a,[('char',b)],['пробирка'])
        self.assertEqual(out[0]['text'],'пробирку');self.assertEqual(out[0]['start'],a[0]['start'])
        self.assertEqual(changes[0]['term'],'пробирка');self.assertEqual(a,before)

    def test_existing_valid_term_form_is_not_reinflected(self):
        a,b=self.pair('пробирка','пробирку');self.assertFalse(apply_terms(a,[('char',b)],['пробирка'])[1])

    def test_no_acoustic_word_means_no_term(self):
        a,_=self.pair('пробилку','пробирку');out,changes=apply_terms(a,[],['пробирка'])
        self.assertEqual(out[0]['text'],'пробилку');self.assertFalse(changes)

    def test_wrong_subject_without_support_has_no_replacement(self):
        a,b=self.pair('пробилку','пробирку');out,changes=apply_terms(a,[('char',b)],['транзистор','электрод'])
        self.assertEqual(out,a);self.assertFalse(changes)

    def test_inflected_numbers_and_negations_are_protected(self):
        for first, second in [('двумя','тремя'), ('пяти','шести'), ('не','ни'), ('2026','2027')]:
            a,b=self.pair(first,second);out,changes=apply_terms(a,[('rnnt',b)],[second])
            self.assertEqual(out,a);self.assertFalse(changes)


if __name__ == '__main__':unittest.main()
