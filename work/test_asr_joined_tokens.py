import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
from transcript_quality import annotate, report_for


def report(text):
    return dict(duration=3, segments=[dict(id=0, start=0, end=2, text=text, needs_review=False,
                recognition=dict(ctc_confidence=.99, word_evidence=[dict(text=text, start=0, end=2, confidence=.99)]))])


class JoinedTokensTests(unittest.TestCase):
    def test_internal_punctuation_marks_joined_tokens_without_rewriting(self):
        for text in ['начало.,конец.', 'начало,.конец', 'начало?!конец']:
            with self.subTest(text=text):
                raw = report(text)
                before = copy.deepcopy(raw)
                row = annotate(raw)['segments'][0]
                self.assertEqual(raw, before)
                self.assertTrue(row['needs_review'])
                self.assertEqual(row['text'], text)
                self.assertEqual((row['start'], row['end']), (0, 2))
                self.assertIn('В распознавании склеены части слов', row['quality']['reasons'])

    def test_numbers_names_abbreviations_and_normal_punctuation_are_unchanged(self):
        for text in ['3.14', '8:00', '3..5', 'А.С.', 'Иванов-Петров', "д'Артаньян", 'из-за', 'Пример...', 'C++', 'Node.js', 'слово,', 'Слово?!']:
            with self.subTest(text=text):
                self.assertFalse(annotate(report(text))['segments'][0]['needs_review'])

    def test_missing_or_invalid_evidence_is_compatible(self):
        for value in [None, [], {}, 'text', [None], [dict(text=7)]]:
            with self.subTest(value=value):
                raw = report('Обычная фраза.')
                raw['segments'][0]['recognition']['word_evidence'] = value
                self.assertFalse(annotate(raw)['segments'][0]['needs_review'])

    def test_human_confirmation_is_preserved(self):
        raw = report('начало.,конец.')
        key = annotate(raw)['segments'][0]['review_key']
        result = annotate(raw, {key: dict(reviewed=True)})
        self.assertTrue(result['segments'][0]['reviewed'])
        self.assertEqual(result['quality']['pending'], 0)

    def test_existing_transcript_reaches_normal_report_route_without_new_asr(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'analysis').mkdir()
            raw = report('начало.,конец.')
            path = root / 'analysis/fixture.transcript.json'
            path.write_text(json.dumps(raw))
            before = path.read_bytes()
            row = report_for(root, 'fixture.wav')['segments'][0]
            self.assertTrue(row['needs_review'])
            self.assertEqual(row['start'], 0)
            self.assertEqual(row['text'], raw['segments'][0]['text'])
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
