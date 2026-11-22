"""Фиксированные ловушки конспекта; не выдаются за ответы живой модели."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/recorder'))
import ai_worker


class NextSummaryTests(unittest.TestCase):
    def rows(self, text, **extra):
        return [dict(id=7,start=1,end=4,text=text,**extra)]

    def test_fixed_response_suite(self):
        for case in json.loads((ROOT/'tests/fixtures/summary/traps.json').read_text()):
            with self.subTest(case=case['name']):
                result=ai_worker.validate_part(case['proposal'],case['rows'])
                for field,expected in case['expected_mac'].items():
                    if field=='deadline':actual=(result.get('homework') or [{}])[0].get('deadline')
                    else:actual=len(result[field.removesuffix('_count')]) if field.endswith('_count') else result[field]
                    self.assertEqual(actual,expected)

    def test_uncertain_non_numeric_claim_stays_in_transcript_only(self):
        text = 'Выяснилось, что происходит акриваация моторных отделов мозг.'
        rows = self.rows(text,needs_review=True)
        result = ai_worker.validate_part(dict(summary=[dict(quote=text,segment_id=7)]),rows)
        self.assertEqual(result['summary'],[])
        self.assertEqual(rows[0]['text'],text)

    def test_cancelled_assignment_same_or_next_row_is_not_homework(self):
        for separate in (False, True):
            text = 'На дом решите задачу 15.'
            rows = self.rows(text if separate else text+' Задание отменяется.')
            if separate: rows.append(dict(id=8,start=4,end=6,text='Задание отменяется.'))
            result = ai_worker.validate_part(dict(homework=[dict(quote=rows[0]['text'],segment_id=7)]),rows)
            self.assertEqual(result['homework'],[])

    def test_transferred_deadline_requires_latest_context(self):
        for separate in (False, True):
            text = 'На дом решите задачу 15. Сдайте до пятницы.'
            correction = 'Нет, срок переносится на понедельник.'
            rows = self.rows(text if separate else text+' '+correction)
            if separate: rows.append(dict(id=8,start=4,end=6,text=correction))
            for deadline, expected in [('до пятницы',None),('на понедельник','на понедельник')]:
                result = ai_worker.validate_part(dict(homework=[dict(quote=rows[0]['text'],segment_id=7,deadline=deadline)]),rows)
                task = result['homework'][0]
                self.assertEqual(task['deadline'],expected)
                self.assertEqual(task['quote'],text+' '+correction)
                self.assertEqual(task['end'],6 if separate else 4)

    def test_unsupported_formula_is_not_a_lecture_fact(self):
        for text, latex, extra in [
            ('Икс равен пяти.','x=50',{}),
            ('Икс равен пятнадцати.','x=5',{}),
            ('Икс равен пятидесяти.','x=5',{}),
            ('Икс не равен пяти.','x=5',{}),
            ('Икс равен пяти или пятидесяти.','x=5',dict(needs_review=True)),
            ('Икс плюс три равен.','x+3=3',{}),
            ('Если икс равен пяти,','x=5',{}),
        ]:
            with self.subTest(text=text,latex=latex):
                part=dict(formulas=[dict(quote=text,segment_id=7,latex=latex)])
                self.assertEqual(ai_worker.validate_part(part,self.rows(text,**extra))['formulas'],[])

    def test_supported_formula_and_quoted_explanation_remain(self):
        for text, latex in [('Икс равен пяти.','x=5'),('Икс не равен пяти.',r'x\ne 5'),
                            ('Икс равен пятнадцати.','x=15'),('Икс равен пятидесяти.','x=50'),
                            ('Сила равна массе, умноженной на ускорение.','F=ma')]:
            with self.subTest(text=text):
                part=dict(formulas=[dict(quote=text,segment_id=7,latex=latex,explanation='Выдуманное объяснение')])
                formula=ai_worker.validate_part(part,self.rows(text))['formulas'][0]
                self.assertEqual(formula['latex'],latex)
                self.assertEqual(formula['explanation'],'')
                self.assertEqual((formula['start'],formula['end']),(1,4))

    def test_replaced_summary_preserves_exact_previous_document(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lecture.json'
            old=dict(summary=['Икс равен пяти.'],summary_evidence=[dict(quote='Икс равен пяти.',segment_id=7,start=1,end=4)])
            ai_worker.save(path,old);before=path.read_bytes()
            new=dict(summary=['Икс равен пятидесяти.'],summary_evidence=[dict(quote='Икс равен пятидесяти.',segment_id=9,start=10,end=14)])
            ai_worker.save_summary(path,new)
            self.assertEqual(json.loads(path.read_text()),new)
            history=list((path.parent/'history'/path.stem).glob('*.json'))
            self.assertEqual(len(history),1)
            self.assertEqual(history[0].read_bytes(),before)
            ai_worker.save_summary(path,new)
            self.assertEqual(len(list((path.parent/'history'/path.stem).glob('*.json'))),1)

    def test_summary_archive_failure_preserves_current_document(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lecture.json';ai_worker.save(path,dict(summary=['Старый пункт']))
            before=path.read_bytes();(path.parent/'history').write_text('blocked')
            with self.assertRaises(OSError):ai_worker.save_summary(path,dict(summary=['Новый пункт']))
            self.assertEqual(path.read_bytes(),before)

    def test_summary_write_failure_keeps_previous_document_and_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lecture.json';ai_worker.save(path,dict(summary=['Старый пункт']))
            before=path.read_bytes();path.with_suffix('.json.tmp').mkdir()
            with self.assertRaises(OSError):ai_worker.save_summary(path,dict(summary=['Новый пункт']))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(next((path.parent/'history'/path.stem).glob('*.json')).read_bytes(),before)

    def test_uncertain_or_conditionless_highlight_is_not_a_confirmed_rule(self):
        for rows in [self.rows('Это важно, учитывайте акриваацию.',needs_review=True),
                     self.rows('то это важно для решения.')]:
            quote=rows[0]['text']
            part=dict(highlights=[dict(quote=quote,segment_id=7,point='Утверждение модели',kind='importance',cue='важно')])
            self.assertEqual(ai_worker.validate_part(part,rows)['highlights'],[])


if __name__ == '__main__':
    unittest.main()
