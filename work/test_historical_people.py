import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from historical_people import identified_people,person_query
from learning_moments import moments_for_report
class PeopleTest(unittest.TestCase):
 def test_ruler_and_inflection(self):self.assertEqual(identified_people('Князь Иван Калитто собирал дань.')[0][0],'Иван Калита')
 def test_artists(self):self.assertEqual(identified_people('Художник Андрей Рудлёв создал икону.')[0][0],'Андрей Рублёв')
 def test_classmates(self):
  for text in ['Даниил, ответь пожалуйста.','Следующий Александр Невский.','Студент Иван Калита присутствует.','Князь Алексей Петров.']:
   self.assertEqual(identified_people(text),[])
 def test_single_ambiguous_first_name(self):self.assertEqual(identified_people('Князь Даниил укреплял город.'),[])
 def test_route_query_is_canonical_and_anchored(self):
  item={'image_query':'Иван Калита','quote':'Князь Иван Калитто правил Москвой.'};self.assertEqual(person_query(item),'Иван Калита')
  self.assertIsNone(person_query(dict(item,image_query='Пётр Иванов')))
 def test_report_dedup_and_other_subject(self):
  segments=[{'id':i,'start':i*5,'end':i*5+5,'text':'Художник Андрей Рудлёв создавал иконы.'} for i in range(3)]
  self.assertEqual(len([m for m in moments_for_report({'segments':segments},'История России') if m['kind']=='person']),1)
  self.assertEqual([m for m in moments_for_report({'segments':segments},'Физика') if m['kind']=='person'],[])
 def test_private_queries_even_in_generated_moments(self):
  from historical_people import private_name_query
  self.assertTrue(private_name_query('Даниил','Даниил отвечает на вопрос'))
  self.assertTrue(private_name_query('Иван Калита','Студент Иван Калита присутствует'))
  self.assertFalse(private_name_query('Иван Калита','Князь Иван Калита собирал дань'))
unittest.main()
