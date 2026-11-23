import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
import uuid
import wave

SOURCE = Path(__file__).resolve().parents[1] / 'outputs/recorder'
sys.path.insert(0, str(SOURCE))
import review_cards as cards
import study_store as store
from transcript_quality import fingerprint


class ReviewCardsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root = store.ROOT
        store.ROOT = Path(self.temp.name)
        (store.ROOT / 'recordings').mkdir()
        self.name = 'lecture-2026-11-24-10-00-00.wav'
        self.other = 'lecture-2026-11-24-11-00-00.wav'
        for name in (self.name, self.other):
            with wave.open(str(store.ROOT / 'recordings' / name), 'wb') as audio:
                audio.setparams((1, 2, 16000, 0, 'NONE', 'none'))
                audio.writeframes(b'\0\0' * 160000)
        self.row = dict(id=41, start=1.125, end=3.875, text='Икс не равен пяти.')
        self.report([self.row])

    def tearDown(self):
        store.ROOT = self.old_root
        self.temp.cleanup()

    def report(self, rows):
        store.save(store.ROOT / 'analysis' / (Path(self.name).stem + '.json'), dict(segments=rows))

    def body(self, **extra):
        body = dict(file=self.name, request_id=uuid.uuid4().hex)
        body.update(extra)
        return body

    def create(self, source=True):
        key = cards.list_cards(self.name)['sources'][0]['key'] if source else None
        body = self.body(action='create', question='Каково условие?', answer='Икс не равен пяти.', source_key=key)
        return body, cards.apply(body)['card']

    def test_literal_quote_and_precise_times_are_server_owned(self):
        source = cards.list_cards(self.name)['sources'][0]
        body = self.body(action='create', question='Условие?', answer='Ответ', source_key=source['key'],
                         source=dict(quote='Икс равен шести.', start=9, end=10))
        saved = cards.apply(body)['card']['source']
        self.assertEqual((saved['quote'], saved['start'], saved['end'], saved['segment_id']),
                         (self.row['text'], 1.125, 3.875, 41))
        self.assertEqual(saved['source_status'], 'confirmed')
        self.assertFalse(saved['text_reviewed'])
        self.assertIn('вручную', saved['source_note'])
        with self.assertRaises(ValueError):
            cards.apply(dict(body, request_id=uuid.uuid4().hex, source_key='invented'))

    def test_manual_cards_survive_an_unreadable_audio_header(self):
        (store.ROOT / 'recordings' / self.name).write_bytes(b'')
        _, item = self.create(source=False)
        saved = cards.list_cards(self.name)
        self.assertEqual(saved['sources'], [])
        self.assertEqual(saved['cards'][0]['id'], item['id'])

    def test_repeated_creation_and_grading_do_not_duplicate(self):
        body, card = self.create()
        for _ in range(3):
            self.assertTrue(cards.apply(body)['replayed'])
        review = self.body(action='review', card_id=card['id'], result='remember')
        cards.apply(review)
        for _ in range(3):
            self.assertEqual(cards.apply(review)['card']['review_count'], 1)
        cards.apply(self.body(action='review', card_id=card['id'], result='again'))
        saved = cards.list_cards(self.name)['cards']
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]['review_count'], saved[0]['remembered_count'], saved[0]['again_count']), (2, 1, 1))
        with self.assertRaises(ValueError):
            cards.apply(dict(body, answer='Другой ответ'))

    def test_parallel_retries_are_one_card(self):
        body = self.body(action='create', question='Вопрос?', answer='Ответ')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(cards.apply, [body] * 8))
        self.assertEqual(len({item['card']['id'] for item in results}), 1)
        self.assertEqual(len(cards.list_cards(self.name)['cards']), 1)

    def test_restart_and_separate_storage_preserve_old_notes(self):
        legacy = dict(markers=[dict(id='marker', start=2)], photos=[], custom='сохранить')
        store.save(store.note_path(self.name), legacy)
        before = store.note_path(self.name).read_bytes()
        body, card = self.create()
        code = ('import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                'import review_cards,study_store;study_store.ROOT=Path(sys.argv[2]);'
                'print(json.dumps(review_cards.apply(json.load(sys.stdin))))')
        result = subprocess.run([sys.executable, '-c', code, str(SOURCE), str(store.ROOT)],
                                input=json.dumps(body), capture_output=True, text=True, check=True)
        replay = json.loads(result.stdout)
        self.assertEqual(replay['card']['id'], card['id'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(store.note_path(self.name).read_bytes(), before)
        self.assertTrue((store.ROOT / 'study' / (Path(self.name).stem + '.review-cards.json')).is_file())

    def test_recording_scope_and_missing_transcript(self):
        self.assertEqual(cards.list_cards(self.other)['sources'], [])
        body, card = self.create(source=False)
        self.assertIsNone(card['source'])
        self.assertEqual(cards.list_cards(self.other)['cards'], [])
        with self.assertRaises(ValueError):
            cards.apply(self.body(file=self.other, action='review', card_id=card['id'], result='again'))

    def test_shift_rebinds_but_word_change_and_duplicate_need_review(self):
        _, card = self.create()
        self.report([dict(self.row, id=99, start=5, end=8)])
        source = cards.list_cards(self.name)['cards'][0]['source']
        self.assertEqual((source['start'], source['end'], source['segment_id']), (5, 8, 99))
        self.assertEqual(source['original_source']['start'], 1.125)
        self.report([dict(self.row, id=99, start=5, end=8), dict(self.row, id=100, start=8, end=9)])
        source = cards.list_cards(self.name)['cards'][0]['source']
        self.assertEqual(source['source_status'], 'needs_review')
        self.assertNotIn('start', source)
        self.report([dict(self.row, text='Икс равен пяти.')])
        source = cards.list_cards(self.name)['cards'][0]['source']
        self.assertEqual(source['quote'], self.row['text'])
        self.assertEqual(source['source_status'], 'needs_review')
        self.assertNotIn('start', source)

    def test_stale_selection_rejected_without_losing_existing_card(self):
        body, card = self.create()
        self.report([dict(self.row, text='Икс не равен шести.')])
        with self.assertRaises(ValueError):
            cards.apply(dict(body, request_id=uuid.uuid4().hex))
        self.assertEqual(cards.list_cards(self.name)['cards'][0]['id'], card['id'])

    def test_user_review_decisions_are_used_without_claiming_human_gold(self):
        self.row['needs_review'] = True
        self.report([self.row])
        before = cards.list_cards(self.name)['sources'][0]
        self.assertTrue(before['text_needs_review'])
        store.save(store.note_path(self.name), dict(transcript_review={fingerprint(self.row): dict(reviewed=True)}))
        after = cards.list_cards(self.name)['sources'][0]
        self.assertTrue(after['text_reviewed'])
        self.assertFalse(after['text_needs_review'])
        self.assertEqual(after['key'], before['key'])

    def test_delete_and_late_retry_cannot_resurrect_card(self):
        original, card = self.create()
        request = self.body(action='delete', card_id=card['id'])
        self.assertTrue(cards.apply(request)['deleted'])
        self.assertTrue(cards.apply(request)['replayed'])
        self.assertIsNone(cards.apply(original)['card'])
        self.assertEqual(cards.list_cards(self.name)['cards'], [])
        importlib.reload(cards)
        self.assertTrue(cards.apply(original)['deleted'])

    def test_invalid_times_and_payloads(self):
        self.report([dict(self.row, start=True), dict(self.row, end=11), dict(text='Нет времени')])
        self.assertEqual(cards.list_cards(self.name)['sources'], [])
        for payload in [dict(action='create', question='', answer='А'),
                        dict(action='create', question='В', answer='А' * 8001),
                        dict(action='review', card_id='card12345', result='other')]:
            with self.assertRaises(ValueError):
                cards.apply(self.body(**payload))
        with self.assertRaises(ValueError):
            cards.list_cards('../outside.wav')


if __name__ == '__main__':
    unittest.main()
