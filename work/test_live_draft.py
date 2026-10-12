import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import study_store as store
from live_draft import LiveDraft
class DraftTest(unittest.TestCase):
 def test_long_retention_and_restart(self):
  with tempfile.TemporaryDirectory() as d,patch.object(store,'ROOT',Path(d)):
   draft=LiveDraft()
   for t in (0,400,800):
    draft.last_save=None;draft.update('a.wav',t+5,[{'start':t,'end':t+5,'text':f'Содержательная тема номер {t}'}])
   path=store.ROOT/'analysis/a.live.json';self.assertEqual(len(store.read(path)['segments']),3)
   draft=LiveDraft();draft.update('a.wav',810,[{'start':805,'end':810,'text':'Следующая тема'}]);self.assertEqual(len(store.read(path)['segments']),4)
   draft.update('b.wav',2,[{'start':0,'end':2,'text':'Другая пара'}]);self.assertEqual(len(store.read(store.ROOT/'analysis/b.live.json')['segments']),1)
 def test_final_tail_persists_during_throttle(self):
  with tempfile.TemporaryDirectory() as d,patch.object(store,'ROOT',Path(d)):
   draft=LiveDraft();draft.update('a.wav',1,[{'start':0,'end':1,'text':'Первая фраза'}])
   draft.update('a.wav',3,[{'start':2,'end':3,'text':'Вторая фраза'}])
   self.assertEqual(len(store.read(store.ROOT/'analysis/a.live.json')['segments']),1)
   draft.update('a.wav',5,[{'start':4,'end':5,'text':'Последняя фраза','needs_review':True}],force=True)
   saved=store.read(store.ROOT/'analysis/a.live.json');self.assertEqual(len(saved['segments']),3);self.assertTrue(saved['segments'][-1]['needs_review']);self.assertEqual(saved['duration'],5)
unittest.main()
