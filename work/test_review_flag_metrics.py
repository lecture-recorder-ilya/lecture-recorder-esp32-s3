"""Метрики флага учитывают пропуски и не прячут полностью потерянную речь."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'outputs/recorder')]
from audit_review_flags import extract,measure,flag


def row(text, review=False):
    return dict(text=text, needs_review=review, recognition={'word_evidence':[dict(text=w,confidence=.99) for w in text.split()]})


class Tests(unittest.TestCase):
    def test_missing_short_word_is_assigned_to_next_phrase(self):
        case=dict(id='x',reference='он не пришел',text='он пришел',word_errors=1,segments=[row('он'),row('пришел',True)])
        rows=extract(case);m=measure(rows,dict(kind='baseline'))
        self.assertEqual(m['short']['errors'],1);self.assertEqual(m['short']['detected'],1)
        self.assertEqual(m['fp'],0)

    def test_empty_hypothesis_keeps_all_deletions(self):
        case=dict(id='x',reference='он не пришел',text='',word_errors=3,segments=[])
        m=measure(extract(case),dict(kind='baseline'))
        self.assertEqual(m['all']['errors'],3);self.assertEqual(m['all']['detected'],0)

    def test_clean_flag_is_a_false_alert(self):
        case=dict(id='x',reference='пробирка стоит',text='пробирка стоит',word_errors=0,segments=[row('пробирка стоит',True)])
        rows=extract(case);m=measure(rows,dict(kind='baseline'))
        self.assertEqual(m['fp'],1);self.assertEqual(m['term']['false_alerts'],1)
        self.assertFalse(flag(rows[0],dict(kind='local',threshold=.7)))

    def test_metadata_without_word_confidence_uses_existing_flag(self):
        case=dict(id='x',reference='верно',text='верно',word_errors=0,segments=[dict(text='верно',needs_review=True)])
        self.assertTrue(flag(extract(case)[0],dict(kind='min',threshold=.5)))


if __name__=='__main__':unittest.main()
