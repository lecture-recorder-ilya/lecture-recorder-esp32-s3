import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from transcript_corrector import proofread
class CorrectionTest(unittest.TestCase):
 def report(self,text):return {'segments':[{'id':7,'start':10,'end':15,'text':text}]}
 def ref(self,topic):return {'title':topic,'url':'https://ru.wikipedia.org/wiki/Test','extract':'Куликовская битва состоялась 8 сентября 1380 года.'}
 def test_date_original_preserved(self):
  r=self.report('В 1382 году была Куликовская битва.');c=proofread(r,'История',self.ref)['corrections'][0]
  self.assertEqual(c['text'],'В 1380 году была Куликовская битва.');self.assertEqual(c['original'],r['segments'][0]['text'])
 def test_ambiguous_no_correction(self):
  for text in ['После Куликовской битвы в 1382 году произошло нападение.','В 1380 году была Куликовская битва.','Не в 1382 году была Куликовская битва.','В 1382 и 1380 году была Куликовская битва.']:
   self.assertEqual(proofread(self.report(text),'История',self.ref)['corrections'],[])
 def test_source_failure_does_not_edit(self):
  def fail(topic):raise OSError('offline')
  result=proofread(self.report('В 1382 году была Куликовская битва.'),'История',fail);self.assertEqual(result['corrections'],[]);self.assertEqual(result['status'],'partial')
 def test_other_subject_not_edited(self):self.assertEqual(proofread(self.report('В 1382 году была Куликовская битва.'),'Физика',self.ref)['corrections'],[])
 def test_public_name_needs_source(self):
  c=proofread(self.report('Иван Калитто собирал дань.'),'История',lambda t:{'title':'Иван I Калита','extract':'Иван Калита','url':'https://ru.wikipedia.org/wiki/Test'})['corrections'][0]
  self.assertEqual(c['text'],'Иван Калита собирал дань.')
  self.assertEqual(proofread(self.report('Даниил отвечает на вопрос.'),'История',self.ref)['corrections'],[])
unittest.main()
