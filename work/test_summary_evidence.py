import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from ai_worker import validate_part,selected_notes

class SummaryTests(unittest.TestCase):
 def setUp(self):
  self.rows=[dict(id=0,start=0,end=3,text='Если функция непрерывна на отрезке, то она достигает максимума.'),
             dict(id=1,start=4,end=6,text='На следующую пару решите задачи пять и шесть.')]
 def test_only_verbatim_summary_survives(self):
  source=self.rows[0]['text'];value=validate_part({'summary':[{'quote':source,'segment_id':0},'Обсуждалось распределение времени и примеры.']},self.rows)
  self.assertEqual(value['summary'],[source]);self.assertEqual(value['summary_evidence'][0]['start'],0)
 def test_unrelated_point_cannot_replace_supported_quote(self):
  source=self.rows[0]['text'];value=validate_part({'summary':[{'point':'Преподаватель объяснил методы интегрирования.','quote':source,'segment_id':0}]},self.rows)
  self.assertEqual(value['summary'],[source])
 def test_wrong_segment_and_invented_quote_are_rejected(self):
  value=validate_part({'summary':[{'quote':self.rows[0]['text'],'segment_id':1},{'quote':'Нужно решить десять задач.','segment_id':0}]},self.rows)
  self.assertEqual(value['summary'],[])
 def test_quote_can_span_adjacent_rows(self):
  quote=self.rows[0]['text']+' '+self.rows[1]['text'];value=validate_part({'summary':[{'quote':quote,'segment_id':0}]},self.rows)
  self.assertEqual(value['summary'],[quote]);self.assertEqual(value['summary_evidence'][0]['end'],6)
 def test_final_selection_cannot_create_new_points(self):
  notes=[s['text'] for s in self.rows];self.assertEqual(selected_notes(notes,{'selected':[1,1,True,-1,99,'выдумка']}),[notes[1]])
  self.assertEqual(selected_notes(notes,{'summary':['Придуманный факт']}),notes)
  self.assertEqual(selected_notes(notes,{'selected':[]}),notes)
 def test_homework_uses_source_quote_and_no_invented_deadline(self):
  source=self.rows[1]['text']
  result={'homework':[{'task':'Решить десять задач','deadline':'В четверг','quote':source,'segment_id':1}]}
  self.assertEqual(validate_part(result,self.rows)['homework'],
                   [dict(task=source,quote=source,start=4,end=6,segment_id=1,deadline=None)])
  uncertain=[self.rows[0],dict(self.rows[1],needs_review=True)]
  self.assertEqual(validate_part(result,uncertain)['homework'],[])
 def test_homework_example_and_classwork_are_not_assigned(self):
  for source in ('Например, на следующую пару решите задачи пять и шесть.',
                 'Решите задачи пять и шесть сейчас.',
                 'На следующую пару не нужно решать задачи пять и шесть.'):
   rows=[dict(id=0,start=0,end=3,text=source)]
   result={'homework':[{'task':source,'quote':source,'segment_id':0}]}
   self.assertEqual(validate_part(result,rows)['homework'],[])
 def test_excerpt_cannot_drop_conditions_or_negation(self):
  value=validate_part({'summary':[{'quote':'она достигает максимума','segment_id':0}]},self.rows)
  self.assertEqual(value['summary'],[self.rows[0]['text']])
  rows=[dict(id=0,start=0,end=3,text='Функция не равна нулю.')]
  value=validate_part({'summary':[{'quote':'равна нулю','segment_id':0}]},rows)
  self.assertEqual(value['summary'],['Функция не равна нулю.'])
 def test_condition_split_between_phrase_rows_is_kept(self):
  rows=[dict(id=0,start=0,end=7,text='Если функция непрерывна на отрезке,'),
        dict(id=1,start=7,end=10,text='то она достигает максимума.')]
  value=validate_part({'summary':[{'quote':rows[1]['text'],'segment_id':1}]},rows)
  self.assertEqual(value['summary'],['Если функция непрерывна на отрезке, то она достигает максимума.'])
 def test_equal_timestamps_do_not_mix_source_rows(self):
  rows=[dict(id=0,start=1,end=2,text='Первая мысль.'),dict(id=1,start=1,end=2,text='Вторая мысль.')]
  value=validate_part({'summary':[{'quote':'Вторая мысль.','segment_id':1}]},rows)
  self.assertEqual(value['summary'],['Вторая мысль.']);self.assertEqual(value['summary_evidence'][0]['segment_id'],1)

if __name__=='__main__':unittest.main()
