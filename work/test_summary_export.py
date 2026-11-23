import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from summary_sources import reconcile
from summary_history import save,restore,versions
from transcript_quality import markdown


class ExportTests(unittest.TestCase):
    def note(self):
        quote='Значение икс равно пятидесяти.'
        return reconcile(dict(summary=[quote],summary_evidence=[dict(quote=quote,segment_id=7,start=1.25,end=4.5)],
            segments=[dict(id=7,start=1.25,end=4.5,text=quote)]),fresh=True)

    def test_export_and_restore_preserve_quotes_and_original_times(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lecture.json';old=self.note();save(path,old);before=path.read_bytes()
            new=copy.deepcopy(old);new['segments'][0].update(id=30,start=12.5,end=16.75);new=reconcile(new)
            save(path,new);revision=versions(path)[0]
            text=markdown(new)
            self.assertIn('Источник [0:12.500–0:16.750]',text)
            self.assertIn('Исходная привязка [0:01.250–0:04.500]',text)
            path.with_suffix('.md').write_text(text,encoding='utf-8')
            restored=restore(path,revision);text=markdown(restored)
            self.assertEqual(path.read_bytes(),before)
            self.assertIn('Источник [0:01.250–0:04.500]: «Значение икс равно пятидесяти.»',text)
            self.assertEqual(path.with_suffix('.md').read_text(),text+'\n')
            self.assertNotIn('Источник [0:12.500',path.with_suffix('.md').read_text())
            self.assertEqual(len(versions(path)),2)

    def test_unresolved_source_never_exports_invented_zero(self):
        report=self.note();report['segments']=[]
        text=markdown(report)
        self.assertIn('Источник нужно сверить',text)
        self.assertIn('Исходная привязка [0:01.250–0:04.500]',text)
        self.assertNotIn('Источник [0:00',text)

    def test_review_sections_preserve_citations(self):
        report=self.note();anchor=report['summary_evidence'][0]
        report['formula_review']=[dict(anchor,review_note='Формулу нужно сверить: минус не совпал.')]
        report['homework_review']=[dict(anchor,review_note='Это переспрос, выдачу ДЗ нужно сверить.')]
        text=markdown(report)
        self.assertIn('минус не совпал',text);self.assertIn('Это переспрос',text)
        self.assertGreaterEqual(text.count('[0:01.250–0:04.500]'),3)

    def test_corrupt_history_does_not_replace_current_version(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lecture.json';save(path,self.note());save(path,dict(summary=['Новый пункт']))
            before=path.read_bytes();revision=versions(path)[0]
            (path.parent/'history'/path.stem/(revision+'.json')).write_text('{}')
            with self.assertRaises(ValueError):restore(path,revision)
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):restore(path,'../lecture')

    def test_legacy_formula_is_rechecked_on_export(self):
        report=dict(segments=[dict(id=0,start=1.25,end=4.5,text='Икс не равен пяти.')],
                    formulas=[dict(quote='Икс не равен пяти.',segment_id=0,start=1.25,end=4.5,latex='x=5')])
        text=markdown(report)
        self.assertIn('Формулу нужно сверить',text)
        self.assertNotIn('$$\nx=5',text)
        self.assertIn('[0:01.250–0:04.500]',text)


if __name__=='__main__':unittest.main()
