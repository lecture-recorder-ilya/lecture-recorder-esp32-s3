import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from preview_history import PreviewHistory
class HistoryTest(unittest.TestCase):
 def test_five_minutes_and_new_recording(self):
  h=PreviewHistory()
  for t in range(0,400,5):h.update('a',t+2,[{'start':t,'end':t+2,'text':f'Уникальная тема номер {t}'}])
  self.assertTrue(all(r['end']>397-300 for r in h.rows));self.assertGreater(len(h.rows),12)
  self.assertEqual(h.update('b',2,[{'start':0,'end':2,'text':'Начало другой пары'}])[0]['id'],1)
 def test_silence_expires_by_time(self):
  h=PreviewHistory();h.update('a',10,[{'start':0,'end':10,'text':'Речь преподавателя'}]);self.assertEqual(len(h.update('a',20,[])),1);self.assertEqual(h.update('a',311,[]),[])
 def test_overlap_updates_instead_of_duplication(self):
  h=PreviewHistory();h.update('a',20,[{'start':13,'end':19,'text':'Князь был вынужден отказаться от притязаний на великое княжение'}])
  r=h.update('a',22,[{'start':13.1,'end':21,'text':'Князь был вынужден отказаться от притязаний на великое княжение и признать старшинство'}]);self.assertEqual(len(r),1);self.assertEqual(r[0]['id'],1);self.assertIn('старшинство',r[0]['text'])
 def test_repeated_phrase_at_later_time_is_retained(self):
  h=PreviewHistory();h.update('a',2,[{'start':0,'end':2,'text':'Это очень важно'}]);self.assertEqual(len(h.update('a',40,[{'start':38,'end':40,'text':'Это очень важно'}])),2)
 def test_adjacent_short_repetitions_are_one_interval(self):
  h=PreviewHistory()
  for t in range(173,178):h.update('a',t+1,[{'start':t,'end':t+1,'text':'Спасибо.'}])
  self.assertEqual(len(h.rows),1);self.assertEqual(h.rows[0]['start'],173);self.assertEqual(h.rows[0]['end'],178)
  h.update('a',182,[{'start':180,'end':182,'text':'Далее рассмотрим княжество'}])
  h.update('a',183,[{'start':182,'end':183,'text':'Спасибо.'}])
  self.assertEqual(len(h.rows),3)
 def test_review_marker_survives_overlap_and_repeat(self):
  h=PreviewHistory();h.update('a',2,[{'start':0,'end':2,'text':'Короткая фраза','needs_review':False}])
  rows=h.update('a',4,[{'start':2,'end':4,'text':'Короткая фраза','needs_review':True}]);self.assertEqual(len(rows),1);self.assertTrue(rows[0]['needs_review'])
  h=PreviewHistory();text='Преподаватель объясняет длинную фразу из нескольких разных слов'
  h.update('a',10,[{'start':0,'end':10,'text':text,'needs_review':True}])
  rows=h.update('a',12,[{'start':.1,'end':12,'text':text+' ещё','needs_review':False,'recognition':{'words':9}}]);self.assertFalse(rows[0]['needs_review']);self.assertEqual(rows[0]['recognition']['words'],9)
unittest.main()
