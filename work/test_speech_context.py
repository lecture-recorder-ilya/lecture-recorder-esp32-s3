import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import lesson_schedule
from speech_context import context_for_recording
from speech_quality import usable,clean_asr_text
class ContextTest(unittest.TestCase):
 def test_schedule_uses_recording_date(self):
  entry={'date':'2026-10-07','start':'14:00','end':'15:30','subject':'Линейная алгебра','type':'Практика','variants':[]}
  with tempfile.TemporaryDirectory() as d,patch.object(lesson_schedule,'DATA',{'entries':[entry]}):
   value=context_for_recording('lecture-2026-10-07-14-24-14-49000.wav',root=Path(d))
  self.assertIsNone(value['prompt']);self.assertEqual('Линейная алгебра',value['subject'])
 def test_dictionary_repetition_is_rejected(self):
  self.assertFalse(usable({'text':'князь '*40}))
 def test_outro_hallucination(self):
  for text in ('Продолжение следует...', 'Лекция. Предмет.', 'ПОДПИСЫВАЮЩИЕСЬ НА КАНАЛ.', 'Подписывайтесь на канал!'):
   self.assertEqual(clean_asr_text(text), '')
  self.assertEqual(clean_asr_text('В примере написано: подписывайтесь на канал.'), 'В примере написано: подписывайтесь на канал.')
  self.assertEqual(clean_asr_text('В книге написано: продолжение следует.'), 'В книге написано: продолжение следует.')
 def test_unknown_has_no_prompt(self):
  self.assertIsNone(context_for_recording('outside.wav')['prompt'])
 def test_manual_and_merged(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'study').mkdir()
   (root/'study/folders.json').write_text(json.dumps({'a.wav':{'subject':'Физика'},'b.wav':{'subject':'История России'}}))
   (root/'study/join.notes.json').write_text(json.dumps({'parts':[{'file':'a.wav','start':0,'duration':10},{'file':'b.wav','start':10,'duration':10}]}))
   self.assertEqual('Физика',context_for_recording('join.wav',0,root)['subject'])
   self.assertEqual('История России',context_for_recording('join.wav',10,root)['subject'])
   self.assertIsNone(context_for_recording('a.wav',0,root)['prompt'])
 def test_unrecognized_manual_subject_does_not_invent_terms(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'study').mkdir();(root/'study/folders.json').write_text(json.dumps({'a.wav':{'subject':'Новый предмет'}}))
   self.assertIsNone(context_for_recording('a.wav',root=root)['prompt'])
 def test_explicit_names_are_scoped_to_recording(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'study').mkdir();(root/'study/a.notes.json').write_text(json.dumps({'asr_terms':'Морозов Илья, Ключевский'}))
   self.assertEqual(context_for_recording('a.wav',root=root)['prompt'],'Морозов Илья, Ключевский')
   self.assertIsNone(context_for_recording('b.wav',root=root)['prompt'])
 def test_terms_validation(self):
  from speech_context import normalize_terms
  self.assertEqual(normalize_terms('Ключевский; Ключевский'), 'Ключевский')
  with self.assertRaises(ValueError):normalize_terms('Лекция. Предмет.')
  with self.assertRaises(ValueError):normalize_terms('а'*301)
unittest.main()
