import time
from pathlib import Path
from preview_history import PreviewHistory
from speech_quality import usable,clean_asr_text
import study_store as store

class LiveDraft:
 def __init__(self):self.history=PreviewHistory();self.last_save=None;self.formulas=[]
 def update(self,name,seconds,segments,force=False):
  path=store.ROOT/'analysis'/(Path(name).stem+'.live.json')
  if self.history.file!=name:
   saved=store.read(path);self.history=PreviewHistory();self.history.file=name
   self.history.rows=[dict(s,text=clean_asr_text(s['text'])) for s in saved.get('segments',[]) if usable(s)]
   self.history.serial=max((s.get('id',0) for s in self.history.rows),default=0);self.last_save=None;self.formulas=saved.get('formulas',[])
  rows=self.history.update(name,0,segments)
  if not force and self.last_save is not None and time.monotonic()-self.last_save<10:return
  store.save(path,{'draft':True,'topic':'Текст текущей пары','overview':'','summary':[],'segments':rows,'duration':seconds,'updated':time.time(),'formulas':self.formulas,'highlights':[],'homework':[]})
  self.last_save=time.monotonic()
