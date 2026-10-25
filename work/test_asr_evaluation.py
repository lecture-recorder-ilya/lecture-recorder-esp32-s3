import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evaluate_asr import score,tokens

class EvaluationTests(unittest.TestCase):
 def test_case_punctuation_and_yo_are_equivalent(self):
  self.assertEqual(score('Ещё одна фраза.','ЕЩЕ одна, фраза!')['wer'],0)
 def test_substitution_insertion_and_deletion_count(self):
  self.assertEqual(score('один два три','один четыре три')['word_errors'],1)
  self.assertEqual(score('один два три','один три')['word_errors'],1)
  self.assertEqual(score('один два три','один два три четыре')['word_errors'],1)
 def test_silence_tracks_invented_words_without_division_by_zero(self):
  result=score('','Спасибо за внимание.');self.assertIsNone(result['wer']);self.assertEqual(result['hallucinated_words'],3)
  self.assertEqual(score('','')['hallucinated_words'],0)
 def test_important_numbers_and_negations_remain_distinct(self):
  self.assertEqual(score('не равно пять','равно шесть')['word_errors'],2)
  self.assertGreater(score('пять','5')['wer'],0)

if __name__=='__main__':unittest.main()
