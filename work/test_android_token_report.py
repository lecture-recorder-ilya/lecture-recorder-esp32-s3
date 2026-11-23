from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from compare_android_token_times import compare
from evaluate_asr import score


def report(text,reference='место да'):
    case=dict(id='x',repeat=0,pcm_sha256='same',reference=reference,text=text,duration=2,
              segments=[dict(text=text,start=0,end=1,needs_review=False,word_times=[])],
              **score(reference,text))
    return dict(cases=[case],summary={})


class Tests(unittest.TestCase):
    def test_equal_wer_does_not_hide_lost_true_word(self):
        before,after=report('место а да'),report('место а')
        self.assertEqual(before['cases'][0]['word_errors'],after['cases'][0]['word_errors'])
        result=compare(before,after,dict(x=dict(target='да')))
        self.assertIn('lost_target_да',result['regressions'][0]['regressions'])

    def test_digit_three_is_not_new_target_loss(self):
        result=compare(report('три','три'),report('3','три'),dict(x=dict(target='три')))
        self.assertFalse(any('lost_target' in x for x in result['cases'][0]['regressions']))

    def test_input_changes_are_rejected(self):
        before=report('да');after=deepcopy(before);after['cases'][0]['pcm_sha256']='changed'
        with self.assertRaises(ValueError):compare(before,after,dict(x={}))

    def test_word_time_must_stay_inside_phrase(self):
        before=report('да');after=deepcopy(before)
        after['cases'][0]['segments'][0]['word_times']=[[0,2,1500]]
        with self.assertRaises(ValueError):compare(before,after,dict(x={}))


if __name__=='__main__':unittest.main()
