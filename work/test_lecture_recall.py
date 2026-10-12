import sys,unittest,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from lecture_recall import cue_query,passages,shortlist,ranked_results
class RecallTest(unittest.TestCase):
 def test_reference_plus_question(self):
  rows=[{'start':10,'end':15,'text':'На предыдущей лекции мы говорили о Куликовской битве.'},{'start':16,'end':20,'text':'Кто командовал русским войском?'}]
  self.assertIn('Кто командовал',cue_query(rows,30)['query']);self.assertIsNone(cue_query(rows,400));self.assertIsNone(cue_query(rows,17))
 def test_no_reference(self):self.assertIsNone(cue_query([{'start':0,'end':5,'text':'Князь правил Москвой.'}],20))
 def test_low_score_and_repeated_nearby_results(self):
  rows=[{'file':'a','start':0},{'file':'a','start':10},{'file':'b','start':0}]
  self.assertEqual(len(ranked_results(rows,[.86,.85,.4])),1)
 def test_only_past_same_subject(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'study').mkdir();(root/'analysis').mkdir();(root/'recordings').mkdir()
   (root/'study/folders.json').write_text(json.dumps({k:{'subject':v} for k,v in [('a.wav','История'),('b.wav','Физика'),('c.wav','История'),('d.wav','История')]}))
   for name in ('a','b','c','d'):
    (root/'recordings'/(name+'.wav')).touch();(root/'analysis'/(name+'.live.json')).write_text(json.dumps({'segments':[{'start':0,'end':5,'text':'Куликовская битва'}]}))
   read=lambda p:json.loads(p.read_text());items=passages(root,'c.wav',read);self.assertEqual([v['file'] for v in items],['a.wav'])
unittest.main()
