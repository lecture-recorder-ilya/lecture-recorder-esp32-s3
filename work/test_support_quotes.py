import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
import transcript_quality


class SupportQuoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'analysis').mkdir()
        self.path=self.root/'analysis/lecture-1.transcript.json'
        self.quote='Значение не равно пяти, поэтому знак минус сохраняется.'
        self.row=dict(id=30,start=1.125,end=4.875,text=self.quote,needs_review=False)

    def tearDown(self):
        self.temp.cleanup()

    def write(self,rows,**extra):
        self.path.write_text(json.dumps(dict(segments=rows,duration=30,**extra)))

    def read(self):
        return transcript_quality.report_for(self.root,'lecture-1.wav')

    def test_first_quote_has_literal_source_and_explicit_draft(self):
        self.write([self.row],summary=['Выдумано 999'],homework=[dict(task='Выдуманное ДЗ')])
        original=self.path.read_bytes()
        result=self.read()
        self.assertEqual(result['summary'],[self.quote])
        self.assertTrue(result['draft'])
        self.assertEqual(result['draft_kind'],'support_quotes')
        self.assertIn('Черновик',result['overview'])
        self.assertEqual(result['homework'],[])
        anchor=result['summary_evidence'][0]
        self.assertEqual((anchor['quote'],anchor['segment_id'],anchor['start'],anchor['end']),
                         (self.quote,30,1.125,4.875))
        self.assertEqual(anchor['source_status'],'confirmed')
        self.assertEqual(self.path.read_bytes(),original)

    def test_failure_and_restart_keep_quotes_available(self):
        self.write([self.row])
        for status in ('processing','error'):
            self.path.with_name('lecture-1.progress.json').write_text(json.dumps(dict(status=status)))
            importlib.reload(transcript_quality)
            self.assertEqual(self.read()['summary'],[self.quote])

    def test_finished_report_always_overrides_newer_draft(self):
        final=self.root/'analysis/lecture-1.json'
        final.write_text(json.dumps(dict(summary=[self.quote],segments=[self.row])))
        self.write([dict(self.row,text='Другой предварительный фрагмент расшифровки.')])
        result=self.read()
        self.assertEqual(result['summary'],[self.quote])
        self.assertFalse(result.get('draft'))
        self.assertNotIn('draft_kind',result)

    def test_noise_uncertainty_questions_and_homework_are_not_support_quotes(self):
        texts=['Чему равен ток при заданных условиях в этой задаче',
               'Правда ли что значение не равно пяти в этой задаче',
               'Сосед сказал, что значение не равно пяти в этой задаче.',
               'На дом решите задачу с отрицательным значением числа.',
               'Возможно, значение не равно пяти, поэтому знак сохраняется.',
               'Проверка микрофона, проверка звука перед началом записи.',
               'фыр '*40,'Если значение равно пяти,']
        for text in texts:
            with self.subTest(text=text):
                self.write([dict(self.row,text=text)])
                self.assertEqual(self.read()['summary'],[])
        self.write([dict(self.row,needs_review=True)])
        self.assertEqual(self.read()['summary'],[])

    def test_user_review_is_respected_and_untimed_source_rejected(self):
        self.write([dict(self.row,needs_review=True)])
        key=self.read()['segments'][0]['review_key']
        (self.root/'study').mkdir()
        (self.root/'study/lecture-1.notes.json').write_text(json.dumps(dict(transcript_review={key:dict(reviewed=True)})))
        self.assertEqual(self.read()['summary'],[self.quote])
        self.write([dict(text=self.quote)])
        self.assertEqual(self.read()['summary'],[])

    def test_audience_and_uncertain_neighbors_cannot_leak_into_quote(self):
        for role in ('student','audience'):
            self.write([dict(self.row,speaker_role=role)])
            self.assertEqual(self.read()['summary'],[])
        self.write([dict(self.row,text='Значение не равно пяти,'),
                    dict(id=31,start=4.875,end=6,text='поэтому знак минус сохраняется.',needs_review=True)])
        self.assertEqual(self.read()['summary'],[])

    def test_live_format_empty_transcript_and_cap(self):
        self.path=self.path.with_name('lecture-1.live.json')
        self.write([])
        self.assertEqual(self.read()['summary'],[])
        rows=[dict(self.row,id=i,start=i*4,end=i*4+3,text=f'Значение {i} не равно пяти, поэтому знак минус сохраняется.') for i in range(6)]
        self.write(rows)
        self.assertEqual(len(self.read()['summary']),3)


if __name__=='__main__':unittest.main()
