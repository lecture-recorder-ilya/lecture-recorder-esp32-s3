import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from asr_guard import supported_text,speech_windows,prepare
class GuardTests(unittest.TestCase):
 def result(self,tokens,times,lp=None):return SimpleNamespace(tokens=tokens,timestamps=times,logprobs=lp or [-.01]*len(tokens))
 def test_high_confidence_words_on_silence_rejected(self):
  r=self.result(['11',' сентября',' 2001',' года.'],[.1,4,8,12]);self.assertEqual(supported_text(r,[]),'')
 def test_brief_voice_does_not_license_quiet_tail(self):
  r=self.result(['Да.',' Подпишитесь',' на',' канал.'],[.4,3,5,7]);self.assertEqual(supported_text(r,[(.2,.7)]),'Да.')
 def test_quiet_confident_speech_retained(self):
  r=self.result(['Век','тор','ное',' про','из','ведение.'],[.3,.4,.5,1,1.1,1.2],[-.3]*6);self.assertEqual(supported_text(r,[(.2,1.4)]),'Векторное произведение.')
 def test_low_confidence_guess_rejected(self):
  r=self.result(['Недостоверно.'],[.5],[-2]);self.assertEqual(supported_text(r,[(.1,1)]),'')
 def test_final_dot_in_silence_does_not_discard_word(self):
  r=self.result(['Работа','.'],[.4,9]);self.assertEqual(supported_text(r,[(.2,.8)]),'Работа.')
 def test_context_word_emitted_in_one_window_only(self):
  r=self.result(['Сила'],[1]);self.assertEqual(supported_text(r,[(.5,1.5)],0,1),'');self.assertEqual(supported_text(r,[(.5,1.5)],1,2),'Сила')
 def test_split_on_long_real_pause(self):
  self.assertEqual(len(speech_windows([(1,2),(8,9)],10)),2)
 def test_second_model_cannot_drop_a_separate_question(self):
  from asr_guard import choose_candidate
  ctc=[{'text':'Речь','start':0,'confidence':.95},{'text':'Вопрос?','start':8,'confidence':.95}]
  rnnt=[{'text':'Речь','start':0,'confidence':.99},{'text':'ещё','start':1,'confidence':.99}]
  self.assertIs(choose_candidate(ctc,rnnt),ctc)
 def test_acoustic_refinement_flags_conflicting_numbers_and_negations(self):
  from asr_guard import refine_words
  for old,new in [('не','ни'),('пять','шесть'),('три','плюс'),('задачу','20')]:
   primary=[dict(text=t,start=i,confidence=c) for i,(t,c) in enumerate([('слово',.99),(old,.68),('сказано',.99)])]
   alternative=[dict(text=t,start=i,confidence=.99) for i,t in enumerate(['слово',new,'сказано'])]
   result,changes,_=refine_words(primary,(),alternative)
   self.assertEqual(result[1]['text'],old)
   self.assertTrue(result[1]['needs_review'])
   self.assertFalse(changes)
   self.assertNotIn('needs_review',primary[1])
 def test_preparation_does_not_edit_input(self):
  import numpy as np
  x=np.full(16000,.03,dtype=np.float32);before=x.copy();y=prepare(x);self.assertTrue(np.array_equal(x,before));self.assertLess(np.std(y[4000:]),1e-5)
if __name__=='__main__':unittest.main()
