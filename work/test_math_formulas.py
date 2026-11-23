import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from context_review import request,review_transcript
from math_formulas import collect,merge,supported_latex
from live_draft import LiveDraft
import study_store as store
import study_service

ROWS=[{'id':0,'start':0,'end':12,'text':'Найдем предел при икс стремится к нулю.'},
      {'id':1,'start':12,'end':24,'text':'Синус трех икс деленный на икс.'},
      {'id':2,'start':24,'end':36,'text':'Этот предел равен трем.'}]
QUOTE=' '.join(r['text'] for r in ROWS)
LATEX=r'\lim_{x\to 0}\frac{\sin(3x)}{x}=3'
ANSWER={'choices':[],'formulas':[{'latex':LATEX,'quote':QUOTE,'rows':[0,1,2],'complete':True,'explanation':'Полное выражение и произнесённый результат.'}]}

class MathTests(unittest.TestCase):
 def test_whole_expression_with_condition_and_result_spans_rows(self):
  value=request(ROWS);self.assertTrue(value['collect_math'])
  items=collect(value,ANSWER);self.assertEqual(len(items),1)
  self.assertEqual(items[0]['latex'],LATEX);self.assertEqual(items[0]['segment_ids'],[0,1,2]);self.assertEqual(items[0]['end'],36)
  self.assertEqual(items[0]['explanation'],'')
 def test_double_escape_normalized_without_invented_explanation(self):
  answer=dict(ANSWER,formulas=[dict(ANSWER['formulas'][0],latex=LATEX.replace('\\','\\\\'),explanation='Решение через известный предел равно единице.')])
  item=collect(request(ROWS),answer)[0];self.assertEqual(item['latex'],LATEX);self.assertEqual(item['explanation'],'')
 def test_omitted_spoken_condition_expands_quote_without_changing_formula(self):
  answer=dict(ANSWER,formulas=[dict(ANSWER['formulas'][0],quote=' '.join(r['text'] for r in ROWS[1:]),rows=[1,2])])
  item=collect(request(ROWS),answer)[0]
  self.assertEqual(item['quote'],QUOTE);self.assertEqual(item['segment_ids'],[0,1,2]);self.assertEqual(item['latex'],LATEX)
 def test_missing_result_and_open_expression_not_emitted(self):
  for latex,quote in [(r'\sin(3x)=','Синус трех икс равен.'),
                      (r'\sin(3x)\sim 3x','Синус трех икс чему эквивалентен?'),
                      (r'\frac{\sin(3x)}{','Синус трех икс деленный на икс.'),
                      (r'\sin(3x)+\ldots','Синус трех икс плюс что-то.')]:
   self.assertFalse(supported_latex(latex,quote))
  answer=dict(ANSWER,formulas=[dict(ANSWER['formulas'][0],complete=False)])
  self.assertEqual(collect(request(ROWS),answer),[])
 def test_unheard_number_operator_variable_or_function_blocked(self):
  for latex in [LATEX[:-1]+'5',LATEX.replace('3x','3y'),LATEX.replace('sin','cos'),LATEX.replace('3x','3x+2'),LATEX.replace('3x','3x^{2}')]:
   self.assertFalse(supported_latex(latex,QUOTE),latex)
 def test_fake_quotes_and_rows_are_rejected(self):
  for changed in [dict(quote='Придуманная формула.'),dict(rows=[0,2]),dict(rows=[0,1,99]),dict(rows=[True]),dict(rows=[1,2])]:
   answer=dict(ANSWER,formulas=[dict(ANSWER['formulas'][0],**changed)])
   self.assertEqual(collect(request(ROWS),answer),[])
 def test_complete_formula_replaces_partial_overlapping_quote(self):
  partial={'start':12,'latex':r'\sin(3x)','quote':ROWS[1]['text'],'segment_id':1}
  complete=collect(request(ROWS),ANSWER)
  items=merge([partial],complete);self.assertEqual(len(items),1);self.assertEqual(items[0]['latex'],LATEX)
  self.assertEqual(len(merge(items,complete)),1)
  later=dict(complete[0],start=100,end=140);self.assertEqual(len(merge(items,[later])),2)
 def test_math_collects_even_without_uncertain_word_candidates(self):
  rows,audit=review_transcript(ROWS,lambda messages,max_tokens:ANSWER)
  self.assertEqual(rows,ROWS);self.assertEqual(audit['checked_windows'],1);self.assertEqual(len(audit['formulas']),1)
 def test_live_formula_survives_next_text_and_restart(self):
  formulas=collect(request(ROWS),ANSWER)
  with tempfile.TemporaryDirectory() as directory,patch.object(store,'ROOT',Path(directory)),patch.object(study_service,'ROOT',Path(directory)),patch.object(study_service,'LIVE_DRAFT',LiveDraft()),patch.object(study_service,'PREVIEW',{'file':'a.wav'}):
   study_service.LIVE_DRAFT.update('a.wav',36,ROWS,force=True)
   self.assertEqual(study_service.publish_context('wrong.wav',[],formulas),0)
   study_service.publish_context('a.wav',[],formulas)
   study_service.LIVE_DRAFT.update('a.wav',40,[],force=True)
   path=Path(directory)/'analysis/a.live.json';self.assertEqual(store.read(path)['formulas'][0]['latex'],LATEX)
   fresh=LiveDraft();fresh.update('a.wav',42,[],force=True);self.assertEqual(fresh.formulas[0]['latex'],LATEX)
   fresh.update('other.wav',1,[],force=True);self.assertEqual(fresh.formulas,[])

if __name__=='__main__':unittest.main()
