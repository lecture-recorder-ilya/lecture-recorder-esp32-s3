import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from summary_quality import build,digest


class QualityTests(unittest.TestCase):
    def fixture(self):
        cases=[dict(name='empty_weak',rows=[dict(needs_review=True)],proposal={}),
               dict(name='cancelled',rows=[],proposal=dict(homework=[dict(quote='Отменено')])),
               dict(name='formula',rows=[],proposal=dict(formulas=[dict(quote='Икс не равен пяти.')])),
               dict(name='confirmed',rows=[],proposal=dict(summary=['Цитата']))]
        results=[{},dict(),dict(formula_review=[{}]),dict(summary=['Цитата'])]
        old=[{},dict(homework=[{}]),dict(formulas=[{}]),dict(summary=['Цитата'])]
        for case in cases:case['attempts']=['искусственная трасса только для unit-теста']
        raw=json.dumps(dict(cases=cases)).encode()
        comparison=dict(input_sha256=hashlib.sha256(raw).hexdigest(),cases=[dict(name=c['name'],proposal_sha256=digest(c['proposal']),
            versions={'old':dict(mac=o),'рабочая_копия':dict(mac=n)}) for c,o,n in zip(cases,old,results)])
        return raw,comparison

    def test_confirmed_disputed_discarded_and_weak_empty_are_separate(self):
        raw,comparison=self.fixture();report=build(raw,comparison,'live')
        self.assertEqual(report['current'],dict(confirmed=1,disputed=1,discarded=1))
        self.assertEqual(report['empty_model_on_weak_input'],1)
        self.assertEqual(report['versions']['old']['published'],3)

    def test_changed_response_file_cannot_share_an_audit(self):
        raw,comparison=self.fixture()
        with self.assertRaises(ValueError):build(raw+b' ',comparison,'live')

    def test_changed_proposal_cannot_share_an_audit(self):
        raw,comparison=self.fixture();comparison['cases'][1]['proposal_sha256']='wrong'
        with self.assertRaises(ValueError):build(raw,comparison,'fixed')

    def test_fixed_case_without_generation_is_not_a_live_run(self):
        raw,comparison=self.fixture();data=json.loads(raw);data['cases'][0].pop('attempts')
        raw=json.dumps(data).encode();comparison['input_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):build(raw,comparison,'live')


if __name__=='__main__':unittest.main()
