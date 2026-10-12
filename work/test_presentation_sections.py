import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from presentation_sections import presentations,roles
import ai_worker
class PresentationTest(unittest.TestCase):
 def segment(self,i,t,text):return {'id':i,'start':t,'end':t+5,'text':text}
 def test_announced_presentation_and_teacher_close(self):
  rows=[self.segment(0,0,'Сейчас выступает одногруппник.'),self.segment(1,20,'Тема моего доклада: Иван Калита.'),self.segment(2,40,'Князь правил Москвой.'),self.segment(3,60,'Спасибо за доклад.')]
  sections=presentations(rows,80);self.assertEqual(len(sections),1);self.assertEqual(sections[0]['title'],'Иван Калита')
  # A teacher announcement and student introduction are one presentation.
  result=roles(rows,sections);self.assertEqual(result['0']['role'],'teacher');self.assertEqual(result['2']['role'],'student');self.assertEqual(result['3']['role'],'teacher')
 def test_student_introduction_following_announcement(self):
  rows=[self.segment(0,0,'Передаю слово.'),self.segment(1,5,'Тема моего доклада: князь Даниил.'),self.segment(2,30,'Спасибо за внимание.')]
  sections=presentations(rows,40);self.assertEqual(len(sections),1);self.assertFalse(sections[0]['ongoing']);self.assertEqual(roles(rows,sections)['2']['role'],'student')
 def test_no_ordinary_question_or_topic_mention(self):
  rows=[self.segment(0,0,'Кто подготовил презентацию?'),self.segment(1,5,'Мы обсуждали доклад на прошлой паре.'),self.segment(2,10,'Спасибо.')]
  self.assertEqual(presentations(rows,20),[]);self.assertEqual(roles(rows,[]),{})
 def test_protected_student_text(self):
  s=dict(self.segment(0,0,'Это текст презентации.'),presentation=True)
  p={'excluded_asides':[{'segment_id':0,'kind':'off_topic_shout','confidence':1,'quote':s['text']}]}
  self.assertEqual(ai_worker.validate_part(p,[s])['excluded_asides'],[])
 def test_unclosed_presentation_and_voice_override(self):
  rows=[self.segment(0,0,'Моя презентация посвящена истории.'),self.segment(1,20,'Давайте уточним.')]
  sections=presentations(rows,40);self.assertTrue(sections[0]['ongoing']);self.assertEqual(roles(rows,sections,[{'start':20,'end':25}])['1']['role'],'teacher')
unittest.main()
