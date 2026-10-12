import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from final_review import review
class ReviewTests(unittest.TestCase):
 def test_salvages_repetition_and_preserves_original(self):
  text='Вы получите результат, то есть в результате, то есть в результате, то есть в результате, то есть в результате, то есть в результате'
  rows=[{'id':0,'start':0,'end':10,'text':text}]
  cleaned,audit=review(rows,'Математика')
  self.assertEqual(len(cleaned),1);self.assertLess(len(cleaned[0]['text']),len(text))
  self.assertEqual(rows[0]['text'],text);self.assertEqual(cleaned[0]['original_text'],text)
 def test_keeps_real_repeats_and_student_words(self):
  rows=[{'id':i,'start':i*2,'end':i*2+1,'text':'Спасибо.'} for i in range(3)]
  cleaned,audit=review(rows,'Математика');self.assertEqual(cleaned,rows)
 def test_removes_boilerplate_with_audit(self):
  rows=[{'id':0,'start':0,'end':1,'text':'ПОДПИСЫВАЮЩИЕСЬ НА КАНАЛ.'}]
  cleaned,audit=review(rows,'Математика');self.assertEqual(cleaned,[]);self.assertEqual(len(audit['removed']),1)
 def test_offline_keeps_source(self):
  def unavailable(topic):raise OSError('offline')
  rows=[{'id':0,'start':0,'end':1,'text':'Куликовская битва произошла в 1382 году.'}]
  cleaned,audit=review(rows,'История России',unavailable)
  self.assertEqual(cleaned,rows);self.assertEqual(audit['source_check'],'partial')
if __name__=='__main__':unittest.main()
