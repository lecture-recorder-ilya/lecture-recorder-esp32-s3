from copy import deepcopy
import unittest
from score_android_summary_live import score

class ScoringTests(unittest.TestCase):
    def values(self):
        row=dict(text='Число девять не равно семи.',start=0,end=4)
        case=dict(name='unit',partition='unit',rows=[row],academic_rows=[0],homework_rows=[],summary_min=1)
        result=dict(status='ready',report=dict(segments=[row],summary=[row['text']],summary_evidence=[dict(quote=row['text'],segment_id=0,start=0,end=4)]))
        return case,result

    def test_positive_requires_supported_quote_and_role(self):
        case,result=self.values();self.assertTrue(score(case,result)['passed'])
        case['academic_rows']=[];case['summary_min']=0
        self.assertFalse(score(case,result)['passed'])
        self.assertIn('summary:role',score(case,result)['errors'])

    def test_runtime_error_is_not_a_successful_refusal(self):
        case,result=self.values();case.update(academic_rows=[],summary_min=0)
        result=dict(status='refused',error='Syntax error in regexp',report=dict(segments=case['rows']))
        self.assertFalse(score(case,result)['passed'])
        result['error']='Не нашёл уверенных пунктов. Расшифровка сохранена'
        self.assertTrue(score(case,result)['passed'])

    def test_invented_number_and_time_fail(self):
        case,result=self.values()
        for field,value in [('quote','Число девяносто равно семи.'),('start',99)]:
            changed=deepcopy(result);changed['report']['summary_evidence'][0][field]=value
            self.assertIn('summary:citation',score(case,changed)['errors'])
            self.assertFalse(score(case,changed)['passed'])

    def test_empty_success_cannot_pass(self):
        case,result=self.values();result['report'].update(summary=[],summary_evidence=[])
        self.assertFalse(score(case,result)['passed'])

if __name__=='__main__':unittest.main()
