import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from ai_worker import validate_part
class FocusTest(unittest.TestCase):
 def setUp(self):
  self.segments=[dict(id=0,start=0,end=30,text='В 1380 году произошла Куликовская битва.'),dict(id=1,start=30,end=33,text='Пацаны, идём вечером играть в футбол!'),dict(id=2,start=33,end=50,text='А почему князь отправился на битву?')]
 def candidate(self,**change):
  value=dict(segment_id=1,quote=self.segments[1]['text'],kind='off_topic_shout',confidence=.99);value.update(change);return value
 def test_exact_brief_aside_and_preserve_question(self):
  v=validate_part({'excluded_asides':[self.candidate()],'topics':[{'segment_id':1,'title':'Футбол'},{'segment_id':2,'title':'Причины битвы'}]},self.segments)
  self.assertEqual([s['id'] for s in v['excluded_asides']],[1]);self.assertEqual(v['topics'][0]['title'],'Причины битвы')
 def test_uncertain_or_unanchored_stays(self):
  for item in [self.candidate(confidence=.7),self.candidate(quote='Придуманная цитата'),self.candidate(segment_id=99),self.candidate(segment_id=True)]:
   self.assertEqual(validate_part({'excluded_asides':[item]},self.segments)['excluded_asides'],[])
 def test_cannot_erase_main_explanation(self):
  item=self.candidate(segment_id=0,quote=self.segments[0]['text']);self.assertEqual(validate_part({'excluded_asides':[item]},self.segments)['excluded_asides'],[])
  short=[dict(id=1,start=0,end=3,text=self.segments[1]['text'])];self.assertEqual(validate_part({'excluded_asides':[self.candidate()]},short)['excluded_asides'],[])
unittest.main()
