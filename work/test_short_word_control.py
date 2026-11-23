"""Потеря настоящего слова не скрывается уже ошибочными ответами или формой числа."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from audit_short_word_control import candidate_texts, measure, replay, retained
from prepare_short_word_control import crop_bounds, select


class Tests(unittest.TestCase):
    def test_digit_three_is_preserved_but_negative_is_not_guessed(self):
        self.assertEqual(retained('три','три','3.'),(1,1))
        self.assertEqual(retained('не','не','Мне.'),(0,1))

    def test_single_low_confidence_rule_can_drop_real_negative(self):
        case=dict(windows=[dict(final=[dict(word='Не',conf=.6,start=0,end=.12),
                                      dict(word='.',conf=.9,start=.3,end=.34)])])
        self.assertEqual(replay(case,'single_conf_below_070'),'')
        self.assertIn('Не',replay(case,'single_span_over_1s'))

    def test_candidate_must_use_same_pcm(self):
        base=[dict(id='x',pcm_sha256='a',reference='да')]
        other=[dict(id='x',pcm_sha256='b',reference='да',text='')]
        with self.assertRaises(ValueError):candidate_texts(base,other)

    def test_prior_error_is_not_counted_as_added_loss(self):
        cases=[dict(id='correct',subset='isolated',reference='не',text='Не.'),
               dict(id='already_wrong',subset='isolated',reference='не',text='Мне.')]
        manifest={r['id']:dict(target='не') for r in cases}
        result=measure(cases,manifest,dict(correct='',already_wrong=''))
        self.assertEqual(result['targets']['не']['added_losses'],1)
        self.assertEqual(result['targets']['не']['baseline_retained'],1)

    def test_selection_excludes_old_sources_and_crops_keep_both_boundaries(self):
        rows=[dict(id=t+'-old',talk_id='old',transcript=t) for t in ('не','три','да')]
        rows += [dict(id=t+'-new',talk_id='new',transcript=t+' слово') for t in ('не','три','да')]
        chosen=select(rows,{r['id'] for r in rows[:3]},1)
        self.assertTrue(all(r['id'].endswith('new') for r in chosen))
        word=lambda a,b:dict(text='не',start=a,end=b)
        case=dict(chunks=[dict(offset=0,trace=[dict(ctc=[word(.2,.28)],rnnt=[word(.16,.24)])])])
        bounds=crop_bounds(case,'не',1)
        self.assertEqual(bounds['start_frame'],1600)
        self.assertEqual(bounds['end_frame'],5440)


if __name__=='__main__':unittest.main()
