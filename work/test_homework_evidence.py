"""Выдача ДЗ, вопрос, пример, переспрос и чужая реплика."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'outputs/recorder'))
from ai_worker import analysis_rows,validate_part


class HomeworkTests(unittest.TestCase):
    def test_distinct_assignment_evidence(self):
        for case in json.loads((ROOT/'tests/fixtures/summary/homework.json').read_text()):
            with self.subTest(case=case['name']):
                result=validate_part(case['proposal'],analysis_rows(case['rows']))
                kind=case['expected_kind']
                self.assertEqual(len(result['homework']),int(kind=='assignment'))
                if kind not in ('assignment','cancelled'):
                    self.assertEqual(result['homework_review'][0]['utterance_kind'],kind)
                    self.assertEqual(result['homework_review'][0]['start'],1)
                    self.assertEqual(result['homework_review'][0]['quote'],case['rows'][0]['text'])

    def test_teacher_answer_does_not_confirm_student_question(self):
        rows=[dict(id=0,start=1,end=4,text='На дом нужно решить задачу 15?',speaker_role='student'),
              dict(id=1,start=4,end=7,text='Да. На дом решите задачу 15.',speaker_role='teacher')]
        result=validate_part(dict(homework=[dict(quote=r['text'],segment_id=r['id']) for r in rows]),rows)
        self.assertEqual([v['quote'] for v in result['homework']],[rows[1]['text']])
        self.assertEqual(result['homework_review'][0]['utterance_kind'],'question')


if __name__=='__main__':unittest.main()
