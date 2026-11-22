import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from speech_audio import normalize_audio
from asr_terms import apply_terms
from asr_segments import phrase_rows
from asr_guard import speech_windows,unrecognized_voice
from asr_windows import boundary_at_pause
from quality_asr import Decoder


def word(text,start,confidence=.98):
 return dict(text=text,start=start,end=start+.3,confidence=confidence)

class AudioTests(unittest.TestCase):
 def test_single_click_does_not_suppress_quiet_speech(self):
  audio=(.02*np.sin(np.arange(32000)*.13)).astype(np.float32);audio[10]=1;original=audio.copy()
  enhanced=normalize_audio(audio)
  self.assertGreater(np.std(enhanced[100:]),np.std(original[100:])*7)
  self.assertTrue(np.array_equal(audio,original));self.assertLessEqual(float(abs(enhanced).max()),1)
 def test_empty_silent_and_nonfinite_input_are_safe(self):
  for audio in (np.array([],dtype=np.float32),np.zeros(1000),np.array([float('nan'),float('inf'),-float('inf')])):
   out=normalize_audio(audio);self.assertTrue(np.all(np.isfinite(out)));self.assertTrue(np.all(out==0))
  with self.assertRaises(ValueError):normalize_audio(np.zeros((2,10)))
 def test_pause_windows_are_ordered_bounded_and_cover_long_voice(self):
  windows=speech_windows([(9,10),(1,2)],12);self.assertEqual(len(windows),2);self.assertLess(windows[0][1],windows[1][0])
  windows=speech_windows([(0,70)],70,max_seconds=24);self.assertEqual(windows,[(0,24),(24,48),(48,70)])
  with self.assertRaises(ValueError):speech_windows([(0,1)],1,max_seconds=0)


 def test_boundary_uses_shared_context_and_leaves_nominal_silence_alone(self):
  samples=np.tile(np.array([.03,-.03],dtype=np.float32),40000)
  samples[29000:37000]=0
  cut=boundary_at_pause(samples,48000)
  self.assertEqual(cut,32800)
  self.assertEqual(boundary_at_pause(samples[16000:],32000)+16000,cut)
  self.assertEqual(boundary_at_pause(samples,32800),32800)
  self.assertEqual(boundary_at_pause(samples,0),0)

class UnrecognizedAudioTests(unittest.TestCase):
 def test_covered_voice_and_silence_are_not_marked(self):
  word_spans=[dict(start=.2,end=.9),dict(start=5.2,end=5.9)]
  self.assertEqual(unrecognized_voice([(0,1),(5,6)],word_spans,0,6),[])
  self.assertEqual(unrecognized_voice([],[],0,6),[])

 def test_potential_gap_is_clipped_to_owned_emission_window(self):
  spans=[dict(start=.2,end=.75),dict(start=3.4,end=3.9)]
  self.assertEqual(unrecognized_voice([(0,4)],spans,1,3),[(1,3)])
  self.assertEqual(unrecognized_voice([(0,4)],spans,1,1.7),[])

 def test_offsets_reach_review_without_entering_text_or_summary(self):
  from ai_worker import analysis_rows
  from transcript_cache import checkpoint,valid
  from transcript_quality import annotate
  text='Первая фраза. Вторая фраза.'
  words=[word('Первая',.1),word('фраза.',.6),word('Вторая',4.1),word('фраза.',4.6)]
  info=dict(word_evidence=words,ctc_confidence=.99,unrecognized_voice=[(2,3.5),(7,8.5)])
  rows=phrase_rows(text,info,20,20,25)
  self.assertEqual(rows[0]['text']+' '+rows[1]['text'],text)
  self.assertNotIn('unrecognized_audio',rows[0]['recognition'])
  self.assertEqual(rows[1]['recognition']['unrecognized_audio'],[dict(start=22,end=23.5)])
  self.assertFalse(analysis_rows(rows)[1]['needs_review'])
  before=annotate(dict(segments=[dict(rows[1],recognition={})]))['segments'][0]
  decisions={before['review_key']:{'reviewed':True}}
  expected={'engine':'test'}
  cache=checkpoint(expected,rows,25,25*16000,True)
  self.assertTrue(valid(cache,expected,25*16000,20*16000))
  report=annotate(cache,decisions)
  self.assertEqual(report['segments'][1]['quality']['unrecognized_audio'],[dict(start=22,end=23.5)])
  self.assertTrue(report['segments'][1]['needs_review'])
  self.assertFalse(report['segments'][1]['reviewed'])
  self.assertEqual(report['segments'][1]['text'],'Вторая фраза.')
  self.assertEqual(report['quality']['pending'],1)

class TermTests(unittest.TestCase):
 def setUp(self):
  self.primary=[word('Теорема',0),word('Лагранджо.',1,.72)]
  self.other=[word('Теорема',.02),word('Лагранжа.',1.1,.8)]
 def test_user_term_selects_only_aligned_acoustic_candidate(self):
  before=copy.deepcopy(self.primary);out,changes=apply_terms(self.primary,[('rnnt',self.other)],['теорема Лагранжа'])
  self.assertEqual(out[1]['text'],'Лагранжа.');self.assertEqual(out[1]['original_text'],'Лагранджо.')
  self.assertEqual(changes[0]['source'],'user-term-acoustic-pass');self.assertEqual(self.primary,before)
 def test_glossary_alone_cannot_invent_term(self):
  out,changes=apply_terms(self.primary,[],['Лагранжа']);self.assertEqual(out[1]['text'],self.primary[1]['text']);self.assertEqual(changes,[])
  self.assertTrue(out[1]['needs_review']);self.assertEqual(out[1]['review_reason'],'term_mismatch')
 def test_clear_or_unanchored_or_distant_word_is_preserved(self):
  for primary,other in [(list(map(dict,self.primary)),self.other), (self.primary,[word('Лагранжа',1.1)]), (self.primary,[word('Теорема',0),word('Лагранжа',6)])]:
   if len(other)==2 and other[1]['start']==1.1:primary[1]['confidence']=.98
   self.assertEqual(apply_terms(primary,[('rnnt',other)],['Лагранжа'])[1],[])
 def test_numbers_and_negations_cannot_be_rewritten_by_hints(self):
  for before,after in [('пять','шесть'),('не','ни'),('1234','1235'),('минус','синус')]:
   primary=[word('Равно',0),word(before,1,.6)];other=[word('Равно',0),word(after,1,.99)]
   self.assertEqual(apply_terms(primary,[('rnnt',other)],[after])[1],[])

class PhraseTests(unittest.TestCase):
 def recognition(self,words):return dict(selected='ctc',ctc_confidence=.95,word_evidence=words,refinements=[])
 def test_sentences_and_pauses_have_word_timestamps(self):
  words=[word('Первая',.4),word('фраза.',1),word('Другая',5),word('мысль.',6)]
  rows=phrase_rows('Первая фраза. Другая мысль.',self.recognition(words),10,10,20,7)
  self.assertEqual([row['id'] for row in rows],[7,8]);self.assertEqual([row['start'] for row in rows],[10.4,15])
  self.assertEqual([row['end'] for row in rows],[11.3,16.3]);self.assertEqual(rows[1]['text'],'Другая мысль.')
  self.assertEqual(rows[1]['words'][0]['start'],15);self.assertEqual(rows[0]['timing'],'asr_words')
 def test_context_boundaries_clip_timestamps_without_losing_text(self):
  rows=phrase_rows('Граница.',self.recognition([word('Граница.',1.9)]),18,20,21)
  self.assertEqual(rows[0]['text'],'Граница.');self.assertEqual(rows[0]['start'],20);self.assertLessEqual(rows[0]['words'][0]['end'],21)
 def test_changed_word_keeps_original_only_in_its_phrase(self):
  words=[word('Первая.',0),dict(word('Лагранжа.',3,.7),original_text='Лагранджо.',needs_review=True)]
  info=self.recognition(words);info['refinements']=[dict(start=3,source='user-term-acoustic-pass')]
  rows=phrase_rows('Первая. Лагранжа.',info,0,0,5)
  self.assertNotIn('original_text',rows[0]['recognition']);self.assertEqual(rows[1]['recognition']['original_text'],'Лагранджо.')
  self.assertFalse(rows[0]['needs_review']);self.assertTrue(rows[1]['needs_review'])
 def test_invalid_or_misaligned_evidence_uses_honest_excerpt_fallback(self):
  for words in ([word('Другое.',0)],[dict(text='Текст.',start=float('nan'),end=1)],[]):
   rows=phrase_rows('Текст.',self.recognition(words),0,0,8)
   self.assertEqual(rows[0]['text'],'Текст.');self.assertEqual(rows[0]['timing'],'audio_excerpt');self.assertNotIn('words',rows[0])
 def test_removed_boilerplate_does_not_reset_remaining_word_time(self):
  words=[word('Подписывайтесь',0),word('на',.4),word('канал.',.8),
         word('Задача',4),word('семнадцать.',4.4)]
  rows=phrase_rows('Задача семнадцать.',self.recognition(words),0,0,7)
  self.assertEqual([row['text'] for row in rows],['Задача семнадцать.'])
  self.assertEqual(rows[0]['start'],4)
  self.assertEqual(rows[0]['timing'],'asr_words')
 def test_long_unpunctuated_text_is_readable_without_lost_words(self):
  words=[word('слово'+str(i),i*.4) for i in range(50)];text=' '.join(w['text'] for w in words)
  rows=phrase_rows(text,self.recognition(words),0,0,22)
  self.assertEqual(' '.join(row['text'] for row in rows),text);self.assertGreater(len(rows),1)

 def test_duration_limit_prefers_clause_boundary_without_losing_words(self):
  words=[word(value,i*.6) for i,value in enumerate(
   'Если функция строго возрастает на отрезке, то её максимум находится на правом конце.'.split())]
  text=' '.join(w['text'] for w in words)
  rows=phrase_rows(text,self.recognition(words),0,0,15)
  self.assertEqual(rows[0]['text'],'Если функция строго возрастает на отрезке,')
  self.assertEqual(' '.join(row['text'] for row in rows),text)
  self.assertTrue(all(row['end']-row['start']<=7 for row in rows))

class DecoderTests(unittest.TestCase):
 def test_decode_skips_long_pauses_and_preserves_global_word_time(self):
  decoder=Decoder();calls=[]
  class Model:
   def recognize(self,audio,**kwargs):
    calls.append(len(audio));return SimpleNamespace(tokens=['Первая',' фраза.'],timestamps=[.4,.8],logprobs=[-.01,-.01])
  with patch('speech_gate.anchored_speech_ranges',side_effect=lambda _,core:core),patch.object(decoder,'_load',return_value=Model()):
   result=decoder.transcribe(np.ones(12*16000,dtype=np.float32)*.01,speech=[(1,3),(8,10)])
  self.assertEqual(result,'Первая фраза. Первая фраза.')
  self.assertEqual(len(calls),4);self.assertLess(max(calls),4*16000)
  self.assertEqual(decoder.last['speech_windows'],2)
  self.assertLessEqual(decoder.last['decoded_seconds'],6)
  starts=[w['start'] for w in decoder.last['word_evidence']];self.assertEqual(starts,sorted(starts));self.assertGreater(starts[2],7)
 def test_silence_does_not_load_models_or_emit_words(self):
  decoder=Decoder()
  with patch.object(decoder,'_load') as load:
   self.assertEqual(decoder.transcribe(np.zeros(16000),speech=[]),'');load.assert_not_called()
 def test_repeated_phrase_does_not_hide_the_next_sentence(self):
  decoder=Decoder()
  model=SimpleNamespace(recognize=lambda *_args, **_kwargs: SimpleNamespace(
   tokens=['Да',' да',' да',' да',' да.',' Задача',' семнадцать.'],
   timestamps=[.4,.7,1.0,1.3,1.6,3.1,3.5],logprobs=[-.02]*7))
  with patch('speech_gate.anchored_speech_ranges',side_effect=lambda _,core:core),patch.object(decoder,'_load',return_value=model):
   text=decoder.transcribe(np.ones(5*16000,dtype=np.float32)*.018,speech=[(.3,4.2)])
  rows=phrase_rows(text,decoder.last,0,0,5)
  self.assertEqual([row['text'] for row in rows],['Задача семнадцать.'])
  self.assertEqual(rows[0]['words'][-1]['word'],'семнадцать.')
  self.assertLess(rows[0]['recognition']['unrecognized_audio'][0]['end'],rows[0]['start'])
 def test_original_is_retried_only_after_both_clean_passes_miss(self):
  samples=np.ones(3*16000,dtype=np.float32)*.03
  for other in ('семнадцать','семь'):
   with self.subTest(second_decoder=other):
    decoder=Decoder()
    calls=[]
    def load(kind):
     def recognize(audio,**_):
      has_signal=bool(np.any(audio))
      calls.append((kind,has_signal))
      token='семнадцать' if kind=='ctc' else other
      return SimpleNamespace(tokens=[token] if has_signal else [],
                             timestamps=[.4] if has_signal else [],logprobs=[-.02] if has_signal else [])
     return SimpleNamespace(recognize=recognize)
    with patch('speech_gate.anchored_speech_ranges',side_effect=lambda _,core:core), \
         patch('speech_audio.enhance_audio',side_effect=lambda audio,*_,**__:np.zeros_like(audio)), \
         patch.object(decoder,'_load',side_effect=load):
     result=decoder.transcribe(samples,speech=[(.3,2.0)])
    self.assertEqual(calls,[('ctc',False),('rnnt',False),('ctc',True),('rnnt',True)])
    if other=='семнадцать':
     self.assertEqual(result,'семнадцать')
     self.assertTrue(decoder.last['word_evidence'][0]['needs_review'])
    else:
     self.assertEqual(result,'')
    self.assertTrue(np.all(samples==np.float32(.03)))

class AnalysisTests(unittest.TestCase):
 def test_summary_prompt_excludes_word_arrays_without_losing_flags(self):
  import ai_worker,json
  original=dict(id=7,start=10,end=15,text='Слова преподавателя.',needs_review=True,presentation=True,
                recognition={'word_evidence':[{'text':'слово','alternatives':['вариант']*20}]*1000},words=[{'word':'слово'}]*1000)
  before=copy.deepcopy(original);result=ai_worker.analysis_rows([original])
  self.assertEqual(result,[dict(id=7,start=10,end=15,text='Слова преподавателя.',needs_review=True,presentation=True)])
  self.assertLess(len(json.dumps(result,ensure_ascii=False)),300);self.assertEqual(original,before)

if __name__=='__main__':unittest.main()
