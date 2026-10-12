import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from teacher_remarks import remarks
import ai_worker
class RemarksTest(unittest.TestCase):
 def s(self,text):return [{'id':1,'start':0,'end':8,'text':text}]
 def test_presentation_requirement(self):self.assertEqual(remarks(self.s('В вашей презентации нужно указывать источники.'),{})[0]['category'],'important')
 def test_exam_and_organization(self):
  self.assertEqual(remarks(self.s('Это будет на экзамене.'),{})[0]['category'],'important')
  self.assertEqual(remarks(self.s('Говорите громче.'),{})[0]['category'],'other')
 def test_content_and_student_self_not_advice(self):
  for text in ['Иван Калита правил Москвой.','В моей презентации нужно добавить картинку.','Я должен добавить источник.']:
   self.assertEqual(remarks(self.s(text),{}),[])
 def test_student_presentation_is_kept(self):
  s=dict(self.s('Нужно указать источник.')[0],teacher_remark=True)
  self.assertEqual(ai_worker.validate_part({'excluded_asides':[{'segment_id':1,'kind':'off_topic_shout','confidence':1,'quote':s['text']}]},[s])['excluded_asides'],[])
unittest.main()
