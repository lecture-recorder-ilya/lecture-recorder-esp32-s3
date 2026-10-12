import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from passive_teacher import observe,public
class TeacherTest(unittest.TestCase):
 def test_no_choice_after_short_or_one_sample(self):
  s={};observe(s,[1,0],0,3);self.assertEqual(s,{})
  observe(s,[1,0],0,8);self.assertEqual(public(s)['status'],'learning')
 def test_dominant_voice_and_short_interruption(self):
  s={}
  for i in range(9):observe(s,[1,.1],i*20,i*20+8)
  observe(s,[0,1],190,198)
  self.assertEqual(s['teacher'],0);self.assertEqual(public(s)['status'],'probable')
  self.assertFalse(any(v['start']==190 for v in public(s)['teacher_ranges']))
 def test_same_voice_variation_does_not_split(self):
  s={}
  for i in range(9):observe(s,[1,.1 if i%2 else .5],i*20,i*20+8)
  self.assertEqual(len(s['groups']),1);self.assertEqual(s['teacher'],0)
 def test_ambiguous_equal_speakers_wait(self):
  s={}
  for i in range(20):observe(s,[1,0] if i%2 else [0,1],i*20,i*20+8)
  self.assertIsNone(s['teacher'])
 def test_overlap_not_counted_and_public_no_voiceprints(self):
  s={};observe(s,[1,0],0,8);observe(s,[1,0],2,10)
  self.assertEqual(s['groups'][0]['seconds'],8);self.assertNotIn('groups',public(s))
 def test_only_recent_ranges(self):
  s={}
  for i in range(30):observe(s,[1,0],i*20,i*20+8)
  self.assertTrue(all(r['end']>288 for r in s['ranges']))
 def test_sentence_splits_can_form_sustained_speech(self):
  from passive_teacher import sustained_window
  segments=[{'start':i*2,'end':i*2+2,'text':'Речь преподавателя о теме занятия'} for i in range(4)]
  self.assertEqual(sustained_window(segments,8),(0,8))
  self.assertIsNone(sustained_window([{'start':0,'end':2,'text':'Да конечно'}],2))
  self.assertIsNone(sustained_window(segments,60))
unittest.main()
