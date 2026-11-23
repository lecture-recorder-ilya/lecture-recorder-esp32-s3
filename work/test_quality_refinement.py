import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from asr_guard import refine_words

def word(text,start,confidence=.99):return dict(text=text,start=start,end=start+.2,confidence=confidence)
class RefinementTests(unittest.TestCase):
 def test_truncated_word_requires_independent_repeat(self):
  p=[word('Сиг.',1,.84),word('У',4),word('вас',4.3),word('Сигма.',8,.75)];r=[word('Сигма',1,.66),word('у',4),word('вас',4.3)]
  out,audit,uncertain=refine_words(p,r);self.assertEqual(out[0]['text'],'Сигма.');self.assertEqual(audit[0]['from'],'Сиг.');self.assertEqual(p[0]['text'],'Сиг.')
  out,audit,_=refine_words(p[:3],r);self.assertEqual(out[0]['text'],'Сиг.');self.assertEqual(audit,[])
 def test_clear_word_never_replaced(self):
  p=[word('конце',1),word('XVI',2,.99),word('века.',3)];c=[word('конце',1),word('четырнадцатого',2),word('века',3)]
  self.assertEqual(refine_words(p,[],c)[0][1]['text'],'XVI')
 def test_uncertain_word_has_acoustic_aligned_neighbours(self):
  p=[word('проверим',1),word('агумент',2,.65),word('функции.',3)]
  c=[word('проверим',1),word('аргумент',2,.93),word('функции',3)]
  out,audit,_=refine_words(p,[],c);self.assertEqual(out[1]['text'],'аргумент');self.assertEqual(len(audit),1)
 def test_uncertain_number_is_kept_for_review(self):
  p=[word('конце',1),word('XVI',2,.65),word('века.',3)]
  c=[word('конце',1),word('четырнадцатого',2,.93),word('века',3)]
  out,audit,uncertain=refine_words(p,[],c)
  self.assertEqual(out[1]['text'],'XVI')
  self.assertTrue(out[1]['needs_review'])
  self.assertEqual(audit,[])
  self.assertIn('XVI',uncertain)
 def test_misaligned_or_missing_neighbour_blocks_rewrite(self):
  p=[word('проверим',1),word('агумент',2,.65),word('функции.',3)]
  for c in [[word('проверим',1),word('аргумент',5),word('функции',6)],[word('найдём',1),word('аргумент',2),word('функции',3)]]:
   self.assertEqual(refine_words(p,[],c)[1],[])
 def test_weak_character_excerpt_never_overrides_main(self):
  p=[word('это',1),word('формула?',2,.65)];c=[word('это',1),word('дарбара',2,.75)]
  self.assertEqual(refine_words(p,[],c)[0][1]['text'],'формула?')
 def test_no_unmatched_phrase_inserted(self):
  p=[word('Речь.',1)];c=[word('речь',1),word('подпишитесь',3),word('на',4),word('канал',5)]
  out,_,_=refine_words(p,[],c);self.assertEqual([w['text'] for w in out],['Речь.'])
 def test_weak_words_are_marked_for_review(self):
  self.assertEqual(refine_words([word('сил',1,.55)],[])[2],['сил'])
if __name__=='__main__':unittest.main()
