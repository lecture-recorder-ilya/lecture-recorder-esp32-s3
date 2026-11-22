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
                 'На дом решите задачу 15. Сдавать её не надо.',
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
  rows=[dict(id=0,start=0,end=7,text='Если определитель равен нулю,'),
        dict(id=1,start=7,end=10,text='то система не имеет единственного решения.')]
  value=validate_part({'summary':[{'quote':rows[1]['text'],'segment_id':1}]},rows)
  self.assertEqual(value['summary'],['Если определитель равен нулю, то система не имеет единственного решения.'])
 def test_summary_preserves_number_from_evidence(self):
  source='Значение сопротивления равно 150 ом.'
  rows=[dict(id=0,start=0,end=3,text=source)]
  proposal={'point':'Сопротивление равно 15 ом.', 'quote':source,'segment_id':0}
  self.assertEqual(validate_part({'summary':[proposal]},rows)['summary'],[source])
  proposal['quote']='Значение сопротивления равно 15 ом.'
  self.assertEqual(validate_part({'summary':[proposal]},rows)['summary'],[])
 def test_uncertain_number_or_negation_does_not_become_a_summary_fact(self):
  for source in ('Сопротивление равно пятнадцати омам.', 'Этот метод не сходится.'):
   with self.subTest(source=source):
    rows=[dict(id=0,start=0,end=3,text=source,needs_review=True)]
    proposal={'summary':[{'quote':source,'segment_id':0}]}
    self.assertEqual(validate_part(proposal,rows)['summary'],[])
    rows[0]['needs_review']=False
    self.assertEqual(validate_part(proposal,rows)['summary'],[source])
 def test_deadline_requires_complete_number(self):
  source='На дом решите задачу 15. Сдайте до 15 ноября.'
  rows=[dict(id=0,start=0,end=5,text=source)]
  for deadline, expected in [('до 1', None), ('до 15 ноября', 'до 15 ноября')]:
   with self.subTest(deadline=deadline):
    result=validate_part({'homework':[dict(quote=source,segment_id=0,deadline=deadline)]},rows)
    self.assertEqual(result['homework'][0]['deadline'],expected)
 def test_tentative_or_negated_deadline_does_not_remove_homework(self):
  cases=[
   ('На дом решите задачу 15. Сдайте до пятницы, но срок пока не утверждён.', 'до пятницы', None),
   ('На дом решите задачу 15. Сдать, возможно, до пятницы.', 'возможно, до пятницы', None),
   ('На дом решите задачу 15. Сдайте не к пятнице, а к понедельнику.', 'к пятнице', None),
   ('На дом решите задачу 15. Сдайте не к пятнице, а к понедельнику.', 'к понедельнику', 'к понедельнику'),
   ('На дом решите задачу 15. Сдайте не позже пятницы.', 'не позже пятницы', 'не позже пятницы'),
   ('На дом решите задачу 15. Сдать до пятницы не надо, сдайте к понедельнику.', 'до пятницы', None),
   ('На дом решите задачу 15. Сдать до пятницы не надо, сдайте к понедельнику.', 'к понедельнику', 'к понедельнику'),
  ]
  for source, deadline, expected in cases:
   with self.subTest(deadline=deadline,source=source):
    rows=[dict(id=0,start=0,end=5,text=source)]
    result=validate_part({'homework':[dict(quote=source,segment_id=0,deadline=deadline)]},rows)
    self.assertEqual(result['homework'][0]['quote'],source)
    self.assertEqual(result['homework'][0]['deadline'],expected)
 def test_equal_timestamps_do_not_mix_source_rows(self):
  rows=[dict(id=0,start=1,end=2,text='Первая мысль.'),dict(id=1,start=1,end=2,text='Вторая мысль.')]
  value=validate_part({'summary':[{'quote':'Вторая мысль.','segment_id':1}]},rows)
  self.assertEqual(value['summary'],['Вторая мысль.']);self.assertEqual(value['summary_evidence'][0]['segment_id'],1)

 def test_approximate_deadlines_stay_unspecified(self):
  for phrase, deadline in [
   ('Сдайте примерно до пятницы.', 'до пятницы'),
   ('Сдайте примерно до пятницы.', 'примерно до пятницы'),
   ('Сдайте приблизительно до пятницы.', 'до пятницы'),
   ('Сдайте около 15 ноября.', '15 ноября'),
   ('Сдайте до 15 ноября, предварительно.', 'до 15 ноября'),
  ]:
   with self.subTest(phrase=phrase,deadline=deadline):
    source='На дом решите задачу 15. '+phrase
    value=validate_part({'homework':[dict(quote=source,segment_id=0,deadline=deadline)]},
                        [dict(id=0,start=0,end=5,text=source)])
    self.assertEqual(value['homework'][0]['task'],source)
    self.assertIsNone(value['homework'][0]['deadline'])

 def test_deadline_cannot_truncate_a_date_or_time(self):
  for phrase, deadline, expected in [
   ('Сдайте до 15.11.', 'до 15', None),
   ('Сдайте до 15/11.', 'до 15', None),
   ('Сдайте до 15:30.', 'до 15', None),
   ('Сдайте до 15.11.', 'до 15.11', 'до 15.11'),
   ('Сдайте до 15:30.', 'до 15:30', 'до 15:30'),
  ]:
   with self.subTest(phrase=phrase,deadline=deadline):
    source='На дом решите задачу 15. '+phrase
    value=validate_part({'homework':[dict(quote=source,segment_id=0,deadline=deadline)]},
                        [dict(id=0,start=0,end=5,text=source)])
    self.assertEqual(value['homework'][0]['deadline'],expected)

 def test_incomplete_or_distant_condition_cannot_yield_summary(self):
  for rows in [
   [dict(id=0,start=0,end=3,text='то система не имеет единственного решения.')],
   [dict(id=0,start=0,end=3,text='Если определитель равен нулю,')],
   [dict(id=0,start=0,end=3,text='Если определитель равен нулю')],
   [dict(id=0,start=0,end=3,text='При условии, что определитель равен нулю')],
   [dict(id=0,start=0,end=3,text='Если, например, определитель равен нулю,')],
   [dict(id=0,start=0,end=3,text='Если определитель равен нулю,'),
    dict(id=1,start=10,end=13,text='то система не имеет единственного решения.')],
   [dict(id=0,start=0,end=3,text='Если функция гладкая,',needs_review=True),
    dict(id=1,start=3,end=6,text='то существует производная.')],
  ]:
   with self.subTest(rows=rows):
    value=validate_part({'summary':[dict(quote=rows[-1]['text'],segment_id=rows[-1]['id'])]},rows)
    self.assertEqual(value['summary'],[])

 def test_condition_without_comma_keeps_both_rows(self):
  rows=[dict(id=0,start=0,end=3,text='Если определитель равен нулю'),
        dict(id=1,start=3,end=6,text='то система не имеет единственного решения.')]
  for row in rows:
   value=validate_part({'summary':[dict(quote=row['text'],segment_id=row['id'])]},rows)
   self.assertEqual(value['summary'],[' '.join(r['text'] for r in rows)])
   self.assertEqual((value['summary_evidence'][0]['start'],value['summary_evidence'][0]['end']),(0,6))

 def test_numbers_negations_and_complete_conditions_remain_verbatim(self):
  for source in ('Сопротивление равно не 15, а 150 ом.',
                 'Сопротивление примерно 150 ом, точное значение не измерено.',
                 'Этот метод не сходится.',
                 'Когда началась промышленная революция?',
                 'Если функция непрерывна, она ограничена.',
                 'То есть функция ограничена на отрезке.'):
   with self.subTest(source=source):
    rows=[dict(id=0,start=0,end=3,text=source)]
    value=validate_part({'summary':[dict(quote=source,segment_id=0)]},rows)
    self.assertEqual(value['summary'],[source])

if __name__=='__main__':unittest.main()
